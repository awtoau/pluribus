#!/usr/bin/env python3.15t
"""Build a known-design signature specimen for EP4CGX150 (Quartus map/fit/asm/cpf) in tmp/sig/<name>/ (never the corpus).

  python3.15t scripts/cycloneiv_clean_sig_build.py NAME [NAME ...] [--jobs 3] [--force]

Per tmp/sig/<name>/: sig.toml (top, files = [paths relative to the dir; .v .sv .vhd .qip .hex],
  device, vhdl_2008 = false, qsf = [extra lines]) + the (third-party, untracked) sources + LICENCE-NOTE.txt.
Outputs: quartus/ (project), bitstream.rbf, fit.rpt, fit.json (resource summary from the fit report), logs/<step>.log.
Log: tmp/logs/cycloneiv_clean_sig_build.log.  Reuses cycloneiv_fuzz.run (stall guard 60 s, no output AND no CPU).
Host guard: heavy_guard lease per job (quartus_chain_cyc4 GB).  Overall limit per step is a backstop only (stall is the guard).
"""
import argparse
import json
import logging
import re
import shutil
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_fuzz as fz  # noqa: E402
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

SIG = REPO / "tmp" / "sig"
LOG = REPO / "tmp" / "logs" / "cycloneiv_clean_sig_build.log"
# Backstop only: stall (60 s) is the primary guard.  Specimens are larger than corpus designs; 600 s covers a 64-pt FFT fit by >10x.
LIMITS = {"quartus_map": 600, "quartus_fit": 900, "quartus_asm": 60, "quartus_cpf": 30}
log = logging.getLogger("sig_build")


def project(d, spec):
    dev = spec.get("device", fz.DEVICE)
    lines = ['set_global_assignment -name FAMILY "Cyclone IV GX"', f"set_global_assignment -name DEVICE {dev}",
             f"set_global_assignment -name TOP_LEVEL_ENTITY {spec['top']}"]
    for f in spec["files"]:
        ext = Path(f).suffix.lower()
        kind = {".v": "VERILOG_FILE", ".sv": "SYSTEMVERILOG_FILE", ".vhd": "VHDL_FILE", ".vhdl": "VHDL_FILE", ".qip": "QIP_FILE",
                ".hex": None, ".mif": None, ".svh": None, ".vh": None}[ext]
        if kind:
            extra = " -library " + spec["library"] if spec.get("library") and kind == "VHDL_FILE" else ""
            lines.append(f"set_global_assignment -name {kind} ../{f}{extra}")
    lines += ['set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
              "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1", *spec.get("qsf", [])]
    q = d / "quartus"
    q.mkdir()
    (q / "build.qsf").write_text("\n".join(lines) + "\n")
    (q / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    for f in spec["files"]:          # memory-init files are looked up relative to the project dir
        if Path(f).suffix.lower() in (".hex", ".mif"):
            shutil.copyfile(d / f, q / Path(f).name)
    return q


def fit_summary(rpt):
    out = {}
    pats = {"les": r"Total logic elements\s*;\s*([\d,]+)", "comb": r"Total combinational functions\s*;\s*([\d,]+)",
            "regs": r"Dedicated logic registers\s*;\s*([\d,]+)", "m9k": r"Total memory bits\s*;\s*([\d,]+)",
            "m9k_blocks": r"M9Ks\s*;\s*([\d,]+)", "mult9": r"Embedded Multiplier 9-bit elements\s*;\s*([\d,]+)",
            "pins": r"Total pins\s*;\s*([\d,]+)"}
    t = rpt.read_text(errors="replace")
    for k, p in pats.items():
        m = re.search(p, t)
        out[k] = int(m.group(1).replace(",", "")) if m else None
    return out


def build(name, force):
    d = SIG / name
    spec = tomllib.loads((d / "sig.toml").read_text())
    if (d / "bitstream.rbf").exists() and not force:
        log.info("%s: bitstream exists, skip (--force to rebuild)", name)
        return name, "skip"
    for p in ("quartus", "logs"):
        shutil.rmtree(d / p, ignore_errors=True)
    q = project(d, spec)
    qb = Path(toolchain.quartus_bin())
    steps = [("quartus_map", [qb / "quartus_map", "build"]), ("quartus_fit", [qb / "quartus_fit", "build"]),
             ("quartus_asm", [qb / "quartus_asm", "build"]),
             ("quartus_cpf", [qb / "quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    with heavy_guard.lease(heavy_guard.JOB_GB["quartus_chain_cyc4"], "quartus_chain_cyc4", log):
        for step, cmd in steps:
            if step == "quartus_cpf" and not (q / "build.sof").exists():
                tl = q / "build_time_limited.sof"
                if tl.exists():          # OpenCore Plus: asm writes only a time-limited .sof; quartus_cpf refuses it
                    shutil.copyfile(tl, d / "bitstream_time_limited.sof")
                    fs = fit_summary(q / "build.fit.rpt")
                    shutil.copyfile(q / "build.fit.rpt", d / "fit.rpt")
                    (d / "fit.json").write_text(json.dumps(fs, indent=1))
                    log.info("%s: TIME-LIMITED sof only (no rbf) %s", name, fs)
                    return name, "time-limited-sof " + json.dumps(fs)
            if not fz.run(step, cmd, q, d / "logs", LIMITS):
                tail = (d / "logs" / f"{step}.log").read_text(errors="replace").splitlines()
                errs = [l for l in tail if "Error" in l][:6]
                log.error("%s: FAILED at %s: %s", name, step, errs)
                return name, "FAIL " + step + " " + (errs[0] if errs else "")
    shutil.copyfile(q / "build.rbf", d / "bitstream.rbf")
    shutil.copyfile(q / "build.sof", d / "bitstream.sof")
    shutil.copyfile(q / "build.fit.rpt", d / "fit.rpt")
    fs = fit_summary(d / "fit.rpt")
    (d / "fit.json").write_text(json.dumps(fs, indent=1))
    log.info("%s: OK %s", name, fs)
    return name, "ok " + json.dumps(fs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    fz.log.setLevel(logging.INFO)
    fz.QTMP.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(min(a.jobs, 4)) as ex:
        for n, r in ex.map(lambda n: build(n, a.force), a.names):
            print(f"{n}: {r}", flush=True)


if __name__ == "__main__":
    main()
