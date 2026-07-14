#!/usr/bin/env python3
"""Full pipeline for every Hantek firmware version, then the
cross-bitstream pad comparison.

Three firmware dumps of the same board exist; all three drive the
identical 45-pad set (confirmed 2026-07-14).  Running all of them and
diffing the pad table is the standard way to tell a *lifter* gap (pad
stitched in one firmware, stranded in another) from a genuine
design-level difference.

    python3 scripts/run_hantek_all.py            # all three
    python3 scripts/run_hantek_all.py V07 V4     # a subset

V2 has no committed .config in awto-2000 (read-only live RE project),
so it is unpacked into pluribus tmp/ on first run.  Everything else
reads the .config already sitting beside the .bin there.

Logs: tmp/pipeline_<label>_<stage>.log, tmp/compare_pads.log
"""

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AW2 = "/mnt/2tb/git/awto-2000/fpga"
PINS = f"{AW2}/aw2-pins.tsv"
if not os.path.exists(PINS):
    PINS = f"{AW2}/aw2/aw2-pins.tsv"

# label -> (config path, raw .bin to unpack if the config is missing)
RUNS = {
    "V02": ("tmp/v2/DS1302_V02.bin.config",
            f"{AW2}/v2/DS1302_impl1(8)_V02.bin"),
    "V4":  (f"{AW2}/v4/DS1302_2019071801.bin.config", None),
    "V07": (f"{AW2}/v7/FPGA_V07.bin.config", None),
}


def main():
    want = [a for a in sys.argv[1:]] or list(RUNS)
    unknown = [w for w in want if w not in RUNS]
    if unknown:
        sys.exit(f"unknown label(s) {unknown}; known: {list(RUNS)}")

    for label in want:
        config, raw_bin = RUNS[label]
        cmd = ["python3", "scripts/run_pipeline.py",
               "--label", label, "--config", config, "--pins", PINS]
        # Unpack only when the .config does not exist yet; trellis_unpack
        # and fpga_iomap both refuse to overwrite, so a stale --bin here
        # can never clobber the curated awto-2000 sidecars.
        cfg_abs = config if os.path.isabs(config) else os.path.join(REPO, config)
        if raw_bin and not os.path.exists(cfg_abs):
            os.makedirs(os.path.dirname(cfg_abs), exist_ok=True)
            cmd += ["--bin", raw_bin]
        print(f"=== {label} ===", flush=True)
        rc = subprocess.run(cmd, cwd=REPO).returncode
        if rc != 0:
            sys.exit(f"{label} pipeline FAILED (exit {rc})")

    print("=== compare_pads ===", flush=True)
    log = os.path.join(REPO, "tmp", "compare_pads.log")
    with open(log, "w") as fh:
        rc = subprocess.run(
            ["python3", "scripts/compare_pads.py", *want],
            cwd=REPO, stdout=fh, stderr=subprocess.STDOUT).returncode
    with open(log) as fh:
        print(fh.read())
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
