#!/usr/bin/env python3.15t
"""Cyclone IV E fabric fuzz corpus: generate tiny WYSIWYG designs, build each with Quartus
(map/fit/asm/eda/cpf), keep the post-fit .vo (oracle) and the uncompressed .rbf.

Per design corpus/cycloneiv/<name>/ (only src/ + design.toml tracked):
  quartus/ (project), postfit.vo, bitstream.rbf, build.pin, fit.rpt, logs/<step>.log

  python3.15t scripts/cycloneiv_fuzz.py --generate            # write design dirs
  python3.15t scripts/cycloneiv_fuzz.py --build [--match 'lut_*'] [--force]
Analysis: scripts/cycloneiv_fuzz_analyze.py.  Log: tmp/logs/cycloneiv_fuzz.log
"""
import argparse
import fnmatch
import logging
import os
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor

import psutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus" / "cycloneiv"
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

DEVICE = "EP4CE6E22C8"
FAMILY = "Cyclone IV E"
KEEP = {"src", "design.toml"}
# Host-process guard: stall = 60 s silent; overall = 3x the measured worst step time on EP4CE6
# (docs/cycloneiv-bitstream.md "Fabric decode"); expiry kills the step and fails the design.
# rnd_* designs (thousands of LEs) use OVERALL_RND_S: 3x the worst rnd step measured (same doc).
STALL_S = 60
CPU_POLL_S = 5        # CPU-progress sample interval for the stall check
OVERALL_S = {"quartus_map": 30, "quartus_fit": 32, "quartus_asm": 10, "quartus_eda": 5, "quartus_cpf": 2,
             "quartus_cdb": 6}
OVERALL_RND_S = {"quartus_map": 180, "quartus_fit": 300, "quartus_asm": 30, "quartus_eda": 60,
                 "quartus_cpf": 6, "quartus_cdb": 30}
# gx*: EP4CGX150/110.  First values are a measurement run's backstop; cut to 3x the measured worst.
OVERALL_GX_S = {"quartus_map": 900, "quartus_fit": 2400, "quartus_asm": 120, "quartus_eda": 300,
                "quartus_cpf": 30, "quartus_cdb": 120}
MAX_JOBS = 4          # Quartus processes at once (shared box, #122)
JOB_MIN_GB = 20       # available RAM before a job starts (#122)
log = logging.getLogger("cycloneiv_fuzz")

# Fixed fabric sites for the fuzz cells (smoke_lut placed its LE at X1_Y18; LUT at N even, its FF at N+1).
LUT_SITES = [("LCCOMB_X1_Y18_N0", "a"), ("LCCOMB_X1_Y18_N2", "b"), ("LCCOMB_X10_Y10_N16", "c")]
FF_SITE = "FF_X1_Y18_N1"
# Address sweep: every N at X1_Y18, every Y at X1 N0, every X at Y18 N0 (non-LAB sites fail to fit).
SWEEP_SITES = sorted({f"LCCOMB_X1_Y18_N{n}" for n in range(0, 32, 2)}
                     | {f"LCCOMB_X1_Y{y}_N0" for y in range(1, 24)}
                     | {f"LCCOMB_X{x}_Y18_N0" for x in range(1, 34)})
FF_LUT_SITE = "LCCOMB_X1_Y18_N0"
PINS = {"a": "PIN_28", "b": "PIN_30", "c": "PIN_31", "d": "PIN_32", "y": "PIN_42",
        "clk": "PIN_23", "clrn": "PIN_33", "ena": "PIN_34", "sclr": "PIN_38", "sload": "PIN_39",
        "asdata": "PIN_43", "q": "PIN_44"}


def lut_design(mask, site):
    v = ("module top(input a, b, c, d, output y);\n"
         f"  cycloneive_lcell_comb #(.lut_mask(16'h{mask:04X}), .sum_lutc_input(\"datac\"), "
         ".dont_touch(\"on\"))\n"
         "    lut (.dataa(a), .datab(b), .datac(c), .datad(d), .combout(y));\nendmodule\n")
    qsf = [f"set_location_assignment {site} -to lut"]
    qsf += [f"set_location_assignment {PINS[p]} -to {p}" for p in "abcdy"]
    return v, qsf


FF_PORTS = ("clrn", "ena", "sclr", "sload")


def ff_design(ctrl, power_up):
    """dffeas fed by a fixed LUT (a&b) at FF_LUT_SITE; `ctrl` = which control pins are used."""
    ins = ["a", "b", "clk"] + list(ctrl) + (["asdata"] if "sload" in ctrl else [])
    ports = [".d(n)", ".clk(clk)", ".q(q)"]
    for c in ctrl:
        ports.append(f".{c}({c})")
    if "sload" in ctrl:
        ports.append(".asdata(asdata)")
    v = (f"module top(input {', '.join(ins)}, output q);\n  wire n;\n"
         "  cycloneive_lcell_comb #(.lut_mask(16'h8888), .sum_lutc_input(\"datac\"), .dont_touch(\"on\"))\n"
         "    lut (.dataa(a), .datab(b), .combout(n));\n"
         f"  dffeas #(.power_up(\"{power_up}\"), .is_wysiwyg(\"true\")) r ({', '.join(ports)});\n"
         "endmodule\n")
    qsf = [f"set_location_assignment {FF_LUT_SITE} -to lut", f"set_location_assignment {FF_SITE} -to r"]
    qsf += [f"set_location_assignment {PINS[p]} -to {p}" for p in ins + ["q"]]
    return v, qsf


def specs():
    out = {}
    for si, (site, tag) in enumerate(LUT_SITES):
        masks = [1 << k for k in range(16)] + [0xFFFF ^ (1 << k) for k in range(16)]
        if si == 0:
            masks += [0x0000, 0xFFFF, 0xAAAA, 0xCCCC, 0xF0F0, 0xFF00, 0x6996, 0x8000 | 0x0001]
        for m in masks:
            v, q = lut_design(m, site)
            out[f"lut_{tag}_{m:04x}"] = {"top": "top", "verilog": v, "qsf": q,
                                         "purpose": f"lut_mask {m:04x} at {site}",
                                         "exercises": ["lut_mask"]}
    # power_up high only on the base design: Quartus builds it by push-back (inverted D via a new
    # LUT, sload=1, inverted output) and rejects it with clrn (error 14053) and sclr (no fit).
    for pu in ("low", "high"):
        for k in range(len(FF_PORTS) + 1):
            for ctrl in ([()] if k == 0 else [(c,) for c in FF_PORTS] if k == 1 and pu == "low" else []):
                v, q = ff_design(ctrl, pu)
                nm = "ff_" + pu + ("_" + "_".join(ctrl) if ctrl else "_base")
                out[nm] = {"top": "top", "verilog": v, "qsf": q,
                           "purpose": f"dffeas power_up={pu} controls={list(ctrl)} at {FF_SITE}",
                           "exercises": ["dffeas"] + list(ctrl)}
    v, q = ff_design(FF_PORTS, "low")
    out["ff_low_all"] = {"top": "top", "verilog": v, "qsf": q,
                         "purpose": f"dffeas all controls at {FF_SITE}", "exercises": ["dffeas", *FF_PORTS]}
    # Site sweep for the LE address model: masks 0001 and 0002 differ only in mask bits 0/1.
    for site in SWEEP_SITES:
        for m in (0x0001, 0x0002):
            v, q = lut_design(m, site)
            tag = site.replace("LCCOMB_", "").lower()
            out[f"site_{tag}_{m:04x}"] = {"top": "top", "verilog": v, "qsf": q,
                                          "purpose": f"site sweep lut_mask {m:04x} at {site}",
                                          "exercises": ["lut_mask", "le_address"]}
    # Held-out sites for the LE address model: random (X, Y, N) combinations the sweeps never
    # built together, random masks; scored only by simulation (cycloneiv_sim_check.py --model).
    # ho: used to find the lane-7 rule (now training); ho2: fresh held-out set after that fix.
    cols = [x for x in range(1, 34) if x not in (15, 20, 27)]
    rows = [y for y in range(1, 24) if y not in range(12, 17)]
    for pre, seed in (("ho", 20261024), ("ho2", 20261025)):
      rnd = random.Random(seed)
      for _ in range(16):
        x, y, n = rnd.choice(cols), rnd.choice(rows), 2 * rnd.randrange(16)
        site = f"LCCOMB_X{x}_Y{y}_N{n}"
        for _m in range(2):
            m = rnd.randrange(1, 0xFFFF)
            v, q = lut_design(m, site)
            out[f"{pre}_x{x}_y{y}_n{n}_{m:04x}"] = {"top": "top", "verilog": v, "qsf": q,
                                                 "purpose": f"held-out lut_mask {m:04x} at {site}",
                                                 "exercises": ["lut_mask", "le_address", "held_out"]}
    import cycloneiv_rnd_designs
    out.update(cycloneiv_rnd_designs.rnd_specs())
    out.update(cycloneiv_rnd_designs.gx_specs())
    return out


def toml_list(xs):
    return "[" + ", ".join('"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"' for x in xs) + "]"


def family_of(device):
    return "Cyclone IV GX" if device.startswith("EP4CGX") else FAMILY


def is_big(name):
    return name.startswith("rnd_") or name.startswith("gx")


def generate():
    for name, s in specs().items():
        d = CORPUS / name
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / "src" / "top.v").write_text(s["verilog"])
        (d / "design.toml").write_text(
            f'top = "{s["top"]}"\npurpose = "{s["purpose"]}"\nexercises = {toml_list(s["exercises"])}\n'
            f"qsf = {toml_list(s['qsf'])}\n"
            + (f'device = "{s["device"]}"\n' if "device" in s else ""))
    log.info("generated %d designs", len(specs()))


def run(step, cmd, cwd, logdir, limits=OVERALL_S):
    overall = limits[step]
    logdir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace")
    lines = queue.Queue()

    def pump():
        for ln in proc.stdout:
            lines.put(ln)
        lines.put(None)
    threading.Thread(target=pump, daemon=True).start()
    last = ""
    ps = psutil.Process(proc.pid)
    cpu_last, progress_t = -1.0, time.monotonic()
    with open(logdir / f"{step}.log", "w") as fh:
        while True:
            now = time.monotonic()
            left = overall - (now - t0)
            try:
                ln = lines.get(timeout=max(0.1, min(CPU_POLL_S, left)))
                progress_t = time.monotonic()
            except queue.Empty:
                # stall = no output AND no CPU-time growth for STALL_S (the router runs silent)
                try:
                    c = sum(ps.cpu_times()[:2])
                except psutil.NoSuchProcess:
                    c = cpu_last
                if c > cpu_last:
                    cpu_last, progress_t = c, time.monotonic()
                stalled = time.monotonic() - progress_t >= STALL_S
                if left > 0 and not stalled:
                    continue
                proc.kill()
                proc.wait()
                why = f"OVERALL {overall}s" if left <= 0 else f"STALL {STALL_S}s without output or CPU"
                log.error("[%s] killed: %s, elapsed %.1fs, loadavg %s, last: %r", step, why,
                          time.monotonic() - t0, os.getloadavg(), last.strip())
                return False
            if ln is None:
                break
            fh.write(ln)
            last = ln
    rc = proc.wait()
    el = time.monotonic() - t0
    if rc:
        log.error("[%s] rc=%d after %.1fs, last: %r", step, rc, el, last.strip())
        return False
    log.info("[%s] ok %.1fs", step, el)
    return True


def build_one(name):
    d = CORPUS / name
    spec = tomllib.loads((d / "design.toml").read_text())
    for p in d.iterdir():
        if p.name not in KEEP:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    q = d / "quartus"
    q.mkdir()
    dev = spec.get("device", DEVICE)
    lines = [f'set_global_assignment -name FAMILY "{family_of(dev)}"', f"set_global_assignment -name DEVICE {dev}",
             f"set_global_assignment -name TOP_LEVEL_ENTITY {spec['top']}",
             "set_global_assignment -name VERILOG_FILE ../src/top.v",
             'set_global_assignment -name EDA_SIMULATION_TOOL "QuestaSim (Verilog)"',
             'set_global_assignment -name EDA_OUTPUT_DATA_FORMAT "VERILOG HDL" -section_id eda_simulation',
             'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
             *spec.get("qsf", [])]
    (q / "build.qsf").write_text("\n".join(lines) + "\n")
    (q / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = Path(toolchain.quartus_bin())
    limits = OVERALL_GX_S if name.startswith("gx") else OVERALL_RND_S if is_big(name) else OVERALL_S
    steps = [("quartus_map", [qb / "quartus_map", "build"]), ("quartus_fit", [qb / "quartus_fit", "build"]),
             ("quartus_asm", [qb / "quartus_asm", "build"]),
             ("quartus_eda", [qb / "quartus_eda", "build", "--simulation", "--tool=modelsim", "--format=verilog"]),
             ("quartus_cpf", [qb / "quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    for step, cmd in steps:
        if not run(step, cmd, q, d / "logs", limits):
            return step
    if not rcf_export(q, d, qb, limits):
        return "quartus_cdb"
    vo = next((q / "simulation").rglob("*.vo"))
    for src, dst in ((vo, "postfit.vo"), (q / "build.rbf", "bitstream.rbf"), (q / "build.pin", "build.pin"),
                     (q / "build.fit.rpt", "fit.rpt")):
        shutil.copyfile(src, d / dst)
    (q / "build.sof").unlink()
    return None


def rcf_export(q, d, qb, limits):
    """Full routing of every net -> <design>/routing.rcf.  quartus_cdb rewrites build.qsf even with
    --write_settings_files=off, so the .qsf is restored afterwards."""
    keep = (q / "build.qsf").read_bytes()
    ok = run("quartus_cdb", [qb / "quartus_cdb", "build", "-c", "build", "--back_annotate=routing",
                             "--write_settings_files=off"], q, d / "logs", limits)
    (q / "build.qsf").write_bytes(keep)
    if ok:
        shutil.copyfile(q / "build.rcf", d / "routing.rcf")
    return ok


def rcf_only(name):
    """RCF for a design built before the RCF step existed: export from a scratch copy of its
    project (the build may be a symlink into another checkout; nothing is written there)."""
    d = CORPUS / name
    work = REPO / "tmp" / "cycloneiv" / "rcf_work" / name
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree((d / "quartus").resolve(), work, ignore=shutil.ignore_patterns("*.rbf", "*.sof"))
    try:
        ok = rcf_export(work, d, Path(toolchain.quartus_bin()), OVERALL_S)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return None if ok else "quartus_cdb"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--match", default="*")
    ap.add_argument("--force", action="store_true", help="rebuild designs that already have bitstream.rbf")
    ap.add_argument("--rcf-only", action="store_true", help="export routing.rcf for built designs lacking it")
    ap.add_argument("--jobs", type=int, default=1, help=f"parallel Quartus builds (max {MAX_JOBS})")
    a = ap.parse_args()
    a.jobs = max(1, min(a.jobs, MAX_JOBS))
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_fuzz.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    if a.generate:
        generate()
    if a.build or a.rcf_only:
        if a.rcf_only:
            names = sorted(p.name for p in CORPUS.iterdir() if (p / "bitstream.rbf").exists()
                           and fnmatch.fnmatch(p.name, a.match) and not (p / "routing.rcf").exists())
            fn = rcf_only
        else:
            names = sorted(p.name for p in CORPUS.iterdir() if (p / "design.toml").exists()
                           and fnmatch.fnmatch(p.name, a.match)
                           and (a.force or not (p / "bitstream.rbf").exists()))
            fn = build_one
        log.info("%d designs to process, %d jobs", len(names), a.jobs)
        bad = {}

        def one(n):
            heavy_guard.wait_available(log, n, JOB_MIN_GB)
            t0 = time.monotonic()
            f = fn(n)
            log.info("%s: %s (%.1fs)", n, "ok" if f is None else f"FAIL at {f}", time.monotonic() - t0)
            if f:
                bad[n] = f
        with heavy_guard.heavy_lock("cycloneiv_fuzz", log):
            with ThreadPoolExecutor(a.jobs) as ex:
                list(ex.map(one, names))
        log.info("done %d, failed %d %s", len(names) - len(bad), len(bad), bad)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
