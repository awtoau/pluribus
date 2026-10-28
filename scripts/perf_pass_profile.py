#!/usr/bin/env python3.15t
"""Before/after of the perf-pass stages through scripts/profile_stages.py, each under a memory lease.
Before = legacy env switches (PLURIBUS_ACTIVE/PLANE_HAS/UNIQUE=legacy, PLURIBUS_DECODE=scalar).
Output tmp/perf_pass_profile.json, log tmp/logs/perf_pass_profile.log."""
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard  # noqa: E402

LEGACY = dict(PLURIBUS_ACTIVE="legacy", PLURIBUS_PLANE_HAS="searchsorted", PLURIBUS_UNIQUE="legacy", PLURIBUS_DECODE="scalar")
STAGES = [("decode", 1.0), ("asm_active", heavy_guard.JOB_GB["cyc4_dec_active"]), ("ddb_trace", heavy_guard.JOB_GB["cyc4_tracer"])]
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.FileHandler(REPO / "tmp/logs/perf_pass_profile.log"), logging.StreamHandler()])
log = logging.getLogger("perf_pass_profile")


def main():
    out = {}
    for stage, gb in STAGES:
        for label, extra in (("before", LEGACY), ("after", {})):
            env = dict(os.environ, **extra)
            with heavy_guard.lease(gb, f"perf_pass_{stage}_{label}", log.info):
                p = subprocess.run([sys.executable, str(REPO / "scripts/profile_stages.py"), "--stages", stage],
                                   env=env, capture_output=True, text=True)
            log.info("%s %s rc=%d", stage, label, p.returncode)
            if p.returncode:
                log.error("%s", (p.stdout + p.stderr)[-2000:])
                continue
            res = json.load(open(REPO / "tmp/profile_stages.json"))
            out[f"{stage}/{label}"] = res
            log.info("%s %s %s", stage, label, json.dumps(res)[:1500])
    json.dump(out, open(REPO / "tmp/perf_pass_profile.json", "w"), indent=1)


if __name__ == "__main__":
    main()
