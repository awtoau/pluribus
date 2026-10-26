#!/usr/bin/env python3.15t
"""Re-run decomp.bt -> load.py -> verilog.py on the existing corpus builds (no Quartus).

Use after a lifter change so `bitstreams`/`luts`/`ffs` and each `lifted.v` match the lifter.
One design at a time (no parallel lifts, #111).  Per-step limit: load 3.5 s + verilog ~1 s
on a ~2 MB image; 60 s no-progress limit per step.

Usage: PLURIBUS_SQLITE_PATH=<corpus db> python3.15t scripts/cyclonev_corpus_relift.py [design ...]
Log: tmp/logs/cyclonev_corpus_relift.log
"""
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "tmp" / "logs" / "cyclonev_corpus_relift.log"
DEVICE = os.environ.get("PLURIBUS_CV_DEVICE", "5CEBA4U19C8")
STEP_LIMIT_S = 60   # expected < 5 s per step; 60 s = hung, step fails and is logged


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


def step(name, design, cmd):
    t0 = time.time()
    try:
        r = subprocess.run([str(c) for c in cmd], cwd=REPO, capture_output=True, text=True, timeout=STEP_LIMIT_S)
    except subprocess.TimeoutExpired:
        log(f"FAIL {design} {name}: exceeded {STEP_LIMIT_S}s")
        return False
    if r.returncode != 0:
        log(f"FAIL {design} {name} rc={r.returncode} after {time.time() - t0:.1f}s: "
            f"{(r.stderr or r.stdout).strip().splitlines()[-1:]}")
        return False
    return True


def main():
    if "PLURIBUS_SQLITE_PATH" not in os.environ:
        sys.exit("set PLURIBUS_SQLITE_PATH to the corpus DB (copy)")
    designs = sys.argv[1:] or sorted(p.parent.name for p in (REPO / "corpus" / os.environ.get("PLURIBUS_CV_CORPUS", "cyclonev")).glob("*/decomp.bt"))
    bad = 0
    for d in designs:
        ddir = REPO / "corpus" / os.environ.get("PLURIBUS_CV_CORPUS", "cyclonev") / d
        label = f"cv_corpus_{d}"
        ok = step("load", d, ["python3.15t", "load.py", "--lifter", "cyclonev", "--device", DEVICE,
                              "--label", label, "--config", ddir / "decomp.bt"])
        ok = ok and step("verilog", d, ["python3.15t", "verilog.py", "--bitstream", label, "--top", d,
                                        "--out", ddir / "lifted.v"])
        bad += not ok
    log(f"relift: {len(designs) - bad}/{len(designs)} ok")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
