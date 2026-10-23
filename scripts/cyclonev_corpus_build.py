#!/usr/bin/env python3
"""Build every Cyclone V corpus design end to end and load it into the DB.

Per design in corpus/cyclonev/<name>/ (only src/ and design.toml are tracked):
  quartus/          Quartus project dir (revision "build"), raw, as Quartus left it (no .sof)
  build.qsf, postfit.vo, bitstream.rbf, *.rpt, build.pin   copies at fixed names
  decomp.bt         mistral-cv decomp of bitstream.rbf
  lifted.v          load.py (cyclonev lifter) + verilog.py on decomp.bt
  route_report.txt  quartus_sta report_timing -show_routing (quartus/route.tcl)
  compare.json      scripts/cyclonev_postfit_compare.py summary
  logs/<step>.log   each tool's own output
Rebuild = delete everything except src/ + design.toml, rebuild, replace DB rows.
Layout, tables, example SQL: corpus/README.md.

Usage:
  python3.15t scripts/cyclonev_corpus_build.py              # every design
  python3.15t scripts/cyclonev_corpus_build.py --only adder12 mult9x9
  python3.15t scripts/cyclonev_corpus_build.py --skip-quartus  # re-parse/compare existing outputs
DB: $PLURIBUS_SQLITE_PATH, default corpus/cyclonev/corpus.db.
Log: tmp/logs/cyclonev_corpus_build.log
"""
import argparse
import hashlib
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus" / "cyclonev"
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(CORPUS / "corpus.db"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import toolchain  # noqa: E402

DEVICE = "5CEBA4U19C8"
LOG_PATH = REPO / "tmp" / "logs" / "cyclonev_corpus_build.log"
KEEP = {"src", "design.toml"}
PY = shutil.which("python3.15t") or sys.executable

# Host-process guard (agent-rules): stall = no output line for 60 s -> kill + fail.
# Overall = 3x the measured cold worst case per step (docs/cyclonev-postfit-oracle.md).
STALL_S = 60
OVERALL_S = {"quartus_map": 12, "quartus_fit": 23, "quartus_asm": 6,
             "quartus_eda": 3, "quartus_cpf": 2, "quartus_sta": 4, "decomp": 4,
             "load": 2, "verilog": 2}

log = logging.getLogger("cyclonev_corpus_build")


def setup_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)


def run(step, cmd, cwd, logdir, env=None):
    """Run one tool; its output -> logdir/<step>.log.  Returns True on rc 0."""
    overall = OVERALL_S[step]
    logdir.mkdir(parents=True, exist_ok=True)
    log.info("+ [%s] %s", step, " ".join(str(c) for c in cmd))
    t0 = time.monotonic()
    proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace", env=env)
    lines = queue.Queue()

    def pump():
        for ln in proc.stdout:
            lines.put(ln)
        lines.put(None)
    threading.Thread(target=pump, daemon=True).start()
    last = ""
    with open(logdir / f"{step}.log", "w") as fh:
        while True:
            left = overall - (time.monotonic() - t0)
            try:
                ln = lines.get(timeout=max(0.1, min(STALL_S, left)))
            except queue.Empty:
                proc.kill()
                proc.wait()
                el = time.monotonic() - t0
                why = "OVERALL limit %ds" % overall if left <= STALL_S else "STALL %ds silent" % STALL_S
                log.error("[%s] killed: %s, elapsed %.1fs, loadavg %s, last line: %r",
                          step, why, el, os.getloadavg(), last.strip())
                return False
            if ln is None:
                break
            fh.write(ln)
            last = ln
    rc = proc.wait()
    el = time.monotonic() - t0
    if rc != 0:
        log.error("[%s] rc=%d after %.1fs, last line: %r", step, rc, el, last.strip())
        return False
    log.info("[%s] ok %.1fs", step, el)
    return True


# Routing oracle: every clock gets a 10 ns clock (derive_clocks); all I/O is tied to a
# virtual clock so pad->reg, reg->pad and pad->pad paths are constrained and reported;
# -recovery adds async clear/preset paths.  -nworst 10 = up to 10 paths per endpoint.
ROUTE_TCL = """project_open build -revision build
create_timing_netlist
derive_clocks -period 10
create_clock -name vio -period 10
set_input_delay -clock vio 0 [all_inputs]
set_output_delay -clock vio 0 [all_outputs]
update_timing_netlist
foreach kind {setup recovery} {
  report_timing -$kind -npaths 100000 -nworst 10 -detail full_path -show_routing -file route_report.txt -append
}
delete_timing_netlist
project_close
"""


def clean(ddir):
    for p in ddir.iterdir():
        if p.name in KEEP:
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def write_project(ddir, spec, srcs):
    qdir = ddir / "quartus"
    qdir.mkdir()
    lines = ['set_global_assignment -name FAMILY "Cyclone V"',
             f"set_global_assignment -name DEVICE {DEVICE}",
             f"set_global_assignment -name TOP_LEVEL_ENTITY {spec['top']}"]
    lines += [f"set_global_assignment -name VERILOG_FILE ../src/{s.name}" for s in srcs]
    lines += ['set_global_assignment -name EDA_SIMULATION_TOOL "QuestaSim (Verilog)"',
              'set_global_assignment -name EDA_OUTPUT_DATA_FORMAT "VERILOG HDL" '
              "-section_id eda_simulation"]
    lines += list(spec.get("qsf", []))
    (qdir / "build.qsf").write_text("\n".join(lines) + "\n")
    (qdir / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    return qdir


def quartus(ddir, spec, srcs):
    qb = Path(toolchain.quartus_bin())
    qdir = write_project(ddir, spec, srcs)
    logs = ddir / "logs"
    steps = [("quartus_map", [qb / "quartus_map", "build"]),
             ("quartus_fit", [qb / "quartus_fit", "build"]),
             ("quartus_asm", [qb / "quartus_asm", "build"]),
             ("quartus_eda", [qb / "quartus_eda", "build", "--simulation",
                              "--tool=modelsim", "--format=verilog"]),
             ("quartus_cpf", [qb / "quartus_cpf", "-c", "build.sof", "build.rbf"]),
             ("quartus_sta", [qb / "quartus_sta", "-t", "route.tcl"])]
    (qdir / "route.tcl").write_text(ROUTE_TCL)
    for step, cmd in steps:
        if not run(step, cmd, qdir, logs):
            return step
    (qdir / "build.sof").unlink()
    copies = {"build.qsf": "build.qsf", "simulation/questa/build.vo": "postfit.vo",
              "build.rbf": "bitstream.rbf", "build.map.rpt": "map.rpt",
              "build.fit.rpt": "fit.rpt", "build.asm.rpt": "asm.rpt",
              "build.eda.rpt": "eda.rpt", "build.pin": "build.pin",
              "route_report.txt": "route_report.txt"}
    for src, dst in copies.items():
        shutil.copyfile(qdir / src, ddir / dst)
    return None


def decomp_and_lift(ddir, name):
    logs = ddir / "logs"
    if not run("decomp", [toolchain.mistral_cv(), "decomp", DEVICE, "bitstream.rbf",
                          "decomp.bt"], ddir, logs):
        return "decomp"
    label = lift_label(name)
    env = dict(os.environ)
    if not run("load", [PY, REPO / "load.py", "--lifter", "cyclonev", "--device", DEVICE,
                        "--label", label, "--config", ddir / "decomp.bt"], REPO, logs, env):
        return "load"
    if not run("verilog", [PY, REPO / "verilog.py", "--bitstream", label, "--top", name,
                           "--out", ddir / "lifted.v"], REPO, logs, env):
        return "verilog"
    return None


def lift_label(name):
    return f"cv_corpus_{name}"


def toolchain_version(ddir):
    """Quartus version string from the .vo header (`// VERSION "..."`)."""
    for ln in (ddir / "postfit.vo").open():
        if ln.startswith("// VERSION"):
            return ln.split('"')[1]
    return None


def record_build(name, ddir, spec, srcs, status):
    """Replace this design's postfit_builds row (cascade clears atoms/conns/compare)."""
    import db
    import schema
    from sqlalchemy import delete, insert
    t = schema.postfit_builds
    with db.engine().begin() as conn:
        conn.execute(delete(t).where(t.c.design == name))
        return conn.execute(insert(t).values(
            design=name, family="cyclonev", device=DEVICE, top=spec["top"],
            toolchain=toolchain_version(ddir) if (ddir / "postfit.vo").exists() else None,
            src_sha256={s.name: hashlib.sha256(s.read_bytes()).hexdigest() for s in srcs},
            qsf=list(spec.get("qsf", [])), purpose=spec.get("purpose"),
            exercises=list(spec.get("exercises", [])),
            built_at=datetime.now(timezone.utc), out_dir=str(ddir.relative_to(REPO)),
            lift_label=lift_label(name), status=status,
        )).inserted_primary_key[0]


def build_one(name, skip_quartus):
    ddir = CORPUS / name
    spec = tomllib.loads((ddir / "design.toml").read_text())
    srcs = sorted((ddir / "src").glob("*.v"))
    if not srcs:
        log.error("%s: no src/*.v", name)
        return "src"
    t0 = time.monotonic()
    fail = None
    if not skip_quartus:
        clean(ddir)
        fail = quartus(ddir, spec, srcs) or decomp_and_lift(ddir, name)
    status = "ok" if fail is None else f"fail:{fail}"
    bid = record_build(name, ddir, spec, srcs, status)
    if fail is None:
        import cyclonev_vo_parse
        import cyclonev_postfit_compare
        import cyclonev_route_parse
        cyclonev_vo_parse.load_vo(bid, ddir / "postfit.vo")
        n_hops = cyclonev_route_parse.load_routes(bid, ddir / "route_report.txt")
        log.info("%s: %d route hops", name, n_hops)
        summary = cyclonev_postfit_compare.compare_build(bid, ddir)
        (ddir / "compare.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    log.info("%s: %s (%.1fs)", name, status, time.monotonic() - t0)
    return fail


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="design names (default: all)")
    ap.add_argument("--skip-quartus", action="store_true",
                    help="reuse existing outputs; only re-parse + re-compare")
    args = ap.parse_args()
    setup_logging()
    import schema
    schema.init()
    names = args.only or sorted(p.name for p in CORPUS.iterdir()
                                if (p / "design.toml").exists())
    log.info("DB %s; %d designs; NoGIL=%s", os.environ["PLURIBUS_SQLITE_PATH"], len(names),
             not getattr(sys, "_is_gil_enabled", lambda: True)())
    results = {n: build_one(n, args.skip_quartus) for n in names}
    for n, f in results.items():
        log.info("RESULT %-18s %s", n, "ok" if f is None else f"FAIL at {f}")
    sys.exit(0 if all(f is None for f in results.values()) else 1)


if __name__ == "__main__":
    main()
