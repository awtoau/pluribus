#!/usr/bin/env python3.15t
"""quartus_map + quartus_fit (+ quartus_eda with --eda) for a signature specimen in tmp/sig/<name>/, #165.

  python3.15t scripts/cycloneiv_clean_sig_netlist.py NAME [NAME ...] [--jobs 3] [--force] [--eda]

No quartus_asm / quartus_cpf.  Normal map/fit evaluation outputs only; nothing about licensing is patched or bypassed.
--eda: post-fit .vo for UNLICENSED designs only.  For OpenCore Plus cores quartus_eda refuses (error 204012: no netlist output
for time-limited cores), so licensed Altera IP stops at the map/fit reports (per-entity resource tables).
Per tmp/sig/<name>/: [postfit.vo], fit.rpt, map.rpt, fit.json (resource summary).  Log: tmp/logs/cycloneiv_clean_sig_netlist.log.
Limits: stall guard 60 s (cycloneiv_fuzz.run); per-step overall limit is a backstop (>3x the longest measured step here).
"""
import argparse
import json
import logging
import shutil
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_clean_sig_build as sb  # noqa: E402
import cycloneiv_fuzz as fz  # noqa: E402
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

SIG = sb.SIG
LOG = REPO / "tmp" / "logs" / "cycloneiv_clean_sig_netlist.log"
LIMITS = {"quartus_map": 900, "quartus_fit": 1200, "quartus_eda": 300}
EDA_QSF = ['set_global_assignment -name EDA_SIMULATION_TOOL "QuestaSim (Verilog)"',
           'set_global_assignment -name EDA_OUTPUT_DATA_FORMAT "VERILOG HDL" -section_id eda_simulation']
log = logging.getLogger("sig_netlist")


def build(name, force, eda):
    d = SIG / name
    spec = tomllib.loads((d / "sig.toml").read_text())
    if (d / "map.rpt").exists() and not force:
        log.info("%s: postfit.vo exists, skip", name)
        return name, "skip"
    spec["qsf"] = list(spec.get("qsf", [])) + EDA_QSF
    for p in ("quartus", "logs"):
        shutil.rmtree(d / p, ignore_errors=True)
    q = sb.project(d, spec)
    qb = Path(toolchain.quartus_bin())
    steps = [("quartus_map", [qb / "quartus_map", "build"]), ("quartus_fit", [qb / "quartus_fit", "build"]),
             ]
    if eda:
        steps.append(("quartus_eda", [qb / "quartus_eda", "build", "--simulation", "--tool=modelsim", "--format=verilog"]))
    with heavy_guard.lease(heavy_guard.JOB_GB["quartus_chain_cyc4"], "quartus_chain_cyc4", log):
        for step, cmd in steps:
            if not fz.run(step, cmd, q, d / "logs", LIMITS):
                tail = (d / "logs" / f"{step}.log").read_text(errors="replace").splitlines()
                errs = [x for x in tail if "Error" in x][:4]
                log.error("%s: FAILED at %s: %s", name, step, errs)
                return name, "FAIL " + step + " " + (errs[0] if errs else "")
    if eda:
        shutil.copyfile(next((q / "simulation").rglob("*.vo")), d / "postfit.vo")
    shutil.copyfile(q / "build.fit.rpt", d / "fit.rpt")
    shutil.copyfile(q / "build.map.rpt", d / "map.rpt")
    fs = sb.fit_summary(d / "fit.rpt")
    (d / "fit.json").write_text(json.dumps(fs, indent=1))
    shutil.rmtree(q / "db", ignore_errors=True)
    shutil.rmtree(q / "incremental_db", ignore_errors=True)
    log.info("%s: OK %s", name, fs)
    return name, "ok " + json.dumps(fs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--eda", action="store_true")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    fz.log.setLevel(logging.INFO)
    fz.QTMP.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(min(a.jobs, 4)) as ex:
        for n, r in ex.map(lambda n: build(n, a.force, a.eda), a.names):
            print(f"{n}: {r}", flush=True)


if __name__ == "__main__":
    main()
