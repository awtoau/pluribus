#!/usr/bin/env python3.15t
"""Re-run the Quartus knob/probe builds that back the oracle corrections (docs/altera/cycloneV/cyclonev-blockmux-fuzz-status.md
"Mismatch resolution": opt, LAB clock/enable/clear, DSP, CMUX), one build at a time under heavy_lock.

Outputs: tmp/cyclonev_blockmux_fuzz/<build>/<build>.rbf (+ Mistral .bt for cross-reference) and results.json.
The native decoder re-derives each finding from those .rbf files: scripts/cyclonev_native_verify.py probes.
Log: tmp/logs/cyclonev_native_probes.log
"""
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import heavy_guard  # noqa: E402
import cyclonev_blockmux_fuzz as fz  # noqa: E402

if __name__ == "__main__":
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_native_probes.log"))])
    log = logging.getLogger("cyclonev_native_probes")
    heavy_guard.wait_available(log, "cyclonev_native_probes")
    with heavy_guard.heavy_lock("cyclonev_native_probes", log):
        res = fz.run_resolve(log)
        fz.merge_results(res)
    log.info("done: %d builds, %d errors", len(res), sum(1 for e in res.values() if e.get("error")))
