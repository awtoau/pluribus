#!/usr/bin/env python3.15t
"""Cross-LAB carry specimens (#165): a 40-bit adder (40 carry LEs > 16 per LAB) on EP4CGX150, one build per seed.

  python3.15t scripts/cycloneiv_clean_carry_specimens.py [--seeds 1,2,3]     # log tmp/logs/cycloneiv_clean_carry_specimens.log
Builds corpus/cycloneiv/gx150_cc_<seed:03d> (src/, design.toml tracked; bitstream.rbf, postfit.vo, routing.rcf, build.pin local) so the
structural check / equivalence scripts run on them unchanged.  Sampling plan: 3 builds (seeds), no placement constraint (the fitter places the chain).
Black box: quartus only.  Build limits as cycloneiv_clean_lut_specimens (map 180 s, fit 600 s, asm 60 s, cpf 10 s: first-run backstops).
"""
import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("carry_specimens")
DEVICE = "EP4CGX150DF31C7"
BITS = 40
LIMITS = {"quartus_map": 180, "quartus_fit": 600, "quartus_asm": 60, "quartus_cpf": 10, "quartus_eda": 120, "quartus_cdb": 120}
TOP = f"module top(input [{BITS - 1}:0] a, input [{BITS - 1}:0] b, output [{BITS}:0] s);\n  assign s = a + b;\nendmodule\n"


def build(seed):
    import cycloneiv_fuzz as fz
    import toolchain
    name = f"gx150_cc_{seed:03d}"
    d = Path(REPO) / "corpus" / "cycloneiv" / name
    shutil.rmtree(d, ignore_errors=True)
    (d / "src").mkdir(parents=True)
    q = d / "quartus"
    q.mkdir()
    (d / "src" / "top.v").write_text(TOP)
    qsf = [f"set_global_assignment -name SEED {seed}"]
    (d / "design.toml").write_text('top = "top"\npurpose = "cross-LAB carry chain: %d-bit adder"\nexercises = ["carry"]\nqsf = %s\ndevice = "%s"\n'
                                   % (BITS, json.dumps(qsf), DEVICE))
    full = ['set_global_assignment -name FAMILY "Cyclone IV GX"', f"set_global_assignment -name DEVICE {DEVICE}",
            "set_global_assignment -name TOP_LEVEL_ENTITY top", "set_global_assignment -name VERILOG_FILE ../src/top.v",
            'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
            "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1",
            'set_global_assignment -name EDA_SIMULATION_TOOL "QuestaSim (Verilog)"',
            'set_global_assignment -name EDA_OUTPUT_DATA_FORMAT "VERILOG HDL" -section_id eda_simulation'] + qsf
    (q / "build.qsf").write_text("\n".join(full) + "\n")
    (q / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = toolchain.quartus_bin()
    t0 = time.time()
    steps = [("quartus_map", [f"{qb}/quartus_map", "build"]), ("quartus_fit", [f"{qb}/quartus_fit", "build"]),
             ("quartus_asm", [f"{qb}/quartus_asm", "build"]),
             ("quartus_eda", [f"{qb}/quartus_eda", "build", "--simulation", "--tool=modelsim", "--format=verilog"]),
             ("quartus_cpf", [f"{qb}/quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    for step, cmd in steps:
        if not fz.run(step, cmd, q, d / "logs", LIMITS):
            raise SystemExit(f"{name}: {step} failed")
    if not fz.rcf_export(q, d, Path(qb), LIMITS):
        raise SystemExit(f"{name}: routing export failed")
    import glob
    shutil.copyfile(next(glob.iglob(str(q / "simulation" / "**" / "*.vo"), recursive=True)), d / "postfit.vo")
    shutil.copyfile(q / "build.rbf", d / "bitstream.rbf")
    shutil.copyfile(q / "build.pin", d / "build.pin")
    json.dump({"status": "ok", "attempts": 1, "elapsed_s": round(time.time() - t0, 1)}, open(d / "rebuild.json", "w"))
    shutil.rmtree(q)
    log.info("%s ok %.0fs", name, time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1,2,3")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_carry_specimens.log"))])
    import heavy_guard
    with heavy_guard.lease(6, "cyc4_carry_specimens", log):
        for s in (int(x) for x in a.seeds.split(",")):
            build(s)


if __name__ == "__main__":
    main()
