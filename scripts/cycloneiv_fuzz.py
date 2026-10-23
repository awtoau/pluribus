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
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus" / "cycloneiv"
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

DEVICE = "EP4CE6E22C8"
FAMILY = "Cyclone IV E"
KEEP = {"src", "design.toml"}
# Host-process guard: stall = 60 s silent; overall = 3x the cold worst case per step on EP4CE6
# (measured on the first builds, docs/cycloneiv-bitstream.md), x LIMIT_SCALE.
STALL_S = 60
OVERALL_S = {"quartus_map": 180, "quartus_fit": 300, "quartus_asm": 120, "quartus_eda": 120,
             "quartus_cpf": 60}
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
    return out


def toml_list(xs):
    return "[" + ", ".join('"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"' for x in xs) + "]"


def generate():
    for name, s in specs().items():
        d = CORPUS / name
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / "src" / "top.v").write_text(s["verilog"])
        (d / "design.toml").write_text(
            f'top = "{s["top"]}"\npurpose = "{s["purpose"]}"\nexercises = {toml_list(s["exercises"])}\n'
            f"qsf = {toml_list(s['qsf'])}\n")
    log.info("generated %d designs", len(specs()))


def run(step, cmd, cwd, logdir):
    overall = OVERALL_S[step]
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
    with open(logdir / f"{step}.log", "w") as fh:
        while True:
            left = overall - (time.monotonic() - t0)
            try:
                ln = lines.get(timeout=max(0.1, min(STALL_S, left)))
            except queue.Empty:
                proc.kill()
                proc.wait()
                why = f"OVERALL {overall}s" if left <= STALL_S else f"STALL {STALL_S}s silent"
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
    lines = [f'set_global_assignment -name FAMILY "{FAMILY}"', f"set_global_assignment -name DEVICE {DEVICE}",
             f"set_global_assignment -name TOP_LEVEL_ENTITY {spec['top']}",
             "set_global_assignment -name VERILOG_FILE ../src/top.v",
             'set_global_assignment -name EDA_SIMULATION_TOOL "QuestaSim (Verilog)"',
             'set_global_assignment -name EDA_OUTPUT_DATA_FORMAT "VERILOG HDL" -section_id eda_simulation',
             'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
             *spec.get("qsf", [])]
    (q / "build.qsf").write_text("\n".join(lines) + "\n")
    (q / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = Path(toolchain.quartus_bin())
    steps = [("quartus_map", [qb / "quartus_map", "build"]), ("quartus_fit", [qb / "quartus_fit", "build"]),
             ("quartus_asm", [qb / "quartus_asm", "build"]),
             ("quartus_eda", [qb / "quartus_eda", "build", "--simulation", "--tool=modelsim", "--format=verilog"]),
             ("quartus_cpf", [qb / "quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    for step, cmd in steps:
        heavy_guard.wait_available(log, f"{name} {step}", 4)
        if not run(step, cmd, q, d / "logs"):
            return step
    vo = next((q / "simulation").rglob("*.vo"))
    for src, dst in ((vo, "postfit.vo"), (q / "build.rbf", "bitstream.rbf"), (q / "build.pin", "build.pin"),
                     (q / "build.fit.rpt", "fit.rpt")):
        shutil.copyfile(src, d / dst)
    (q / "build.sof").unlink()
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--match", default="*")
    ap.add_argument("--force", action="store_true", help="rebuild designs that already have bitstream.rbf")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_fuzz.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    if a.generate:
        generate()
    if a.build:
        names = sorted(p.name for p in CORPUS.iterdir() if (p / "design.toml").exists()
                       and fnmatch.fnmatch(p.name, a.match)
                       and (a.force or not (p / "bitstream.rbf").exists()))
        log.info("%d designs to build", len(names))
        bad = {}
        with heavy_guard.heavy_lock("cycloneiv_fuzz", log):
            for n in names:
                t0 = time.monotonic()
                f = build_one(n)
                log.info("%s: %s (%.1fs)", n, "ok" if f is None else f"FAIL at {f}", time.monotonic() - t0)
                if f:
                    bad[n] = f
        log.info("built %d, failed %d %s", len(names) - len(bad), len(bad), bad)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
