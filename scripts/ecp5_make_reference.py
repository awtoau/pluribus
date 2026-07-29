#!/usr/bin/env python3.15t
"""Regenerate a matched (`.config`, placed-netlist) reference pair for round-trip.

The ECP5 build directories here were produced by Amaranth, which runs nextpnr
WITHOUT `--write`.  So `top.json` is the *pre-place* yosys netlist: it has cell
counts and INIT values but no BEL attributes, and therefore cannot verify
placement.  Re-running nextpnr on the same input with `--write` emits the
placed netlist, where every TRELLIS_COMB/TRELLIS_FF carries the BEL it landed
on.

Both outputs come from ONE nextpnr invocation, so the `.config` and the placed
netlist describe the identical placement — that is the property that makes the
comparison meaningful.  (Re-running nextpnr separately from the original build
may pick a different placement than `top.bit` did; that is fine and expected,
because we verify the lifter against the pair we generate, not against the
historical bitstream.)

    python3.15t scripts/ecp5_make_reference.py <build-dir> [--out <dir>]

Logs to ./tmp/logs/ecp5_make_reference.log as well as the terminal.
"""
import argparse
import logging
import os
import re
import shutil
import subprocess
import sys

DEVICE_FLAG = {
    "LFE5U-12F": "--12k", "LFE5U-25F": "--25k",
    "LFE5U-45F": "--45k", "LFE5U-85F": "--85k",
}


def setup_logging(name):
    os.makedirs("tmp/logs", exist_ok=True)
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(f"tmp/logs/{name}.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def parse_build_sh(path):
    """Recover the nextpnr arguments the original build used."""
    txt = open(path).read()
    m = re.search(r"NEXTPNR_ECP5.*", txt)
    if not m:
        raise SystemExit(f"no nextpnr invocation in {path}")
    toks = m.group(0).split()
    args = {}
    for i, t in enumerate(toks):
        if t in ("--package", "--speed"):
            args[t] = toks[i + 1]
        elif re.fullmatch(r"--\d+k", t):
            args["device"] = t
    return args


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build_dir")
    ap.add_argument("--out", default=None,
                    help="output dir (default tmp/ecp5-ref/<name>)")
    args = ap.parse_args()

    log = setup_logging("ecp5_make_reference")
    src = os.path.abspath(args.build_dir)
    name = os.path.basename(os.path.dirname(src)) or os.path.basename(src)
    out = os.path.abspath(args.out or os.path.join("tmp/ecp5-ref", name))
    os.makedirs(out, exist_ok=True)

    np = parse_build_sh(os.path.join(src, "build_top.sh"))
    log.info("source=%s out=%s nextpnr args=%s", src, out, np)

    for f in ("top.json", "top.lpf"):
        shutil.copy(os.path.join(src, f), os.path.join(out, f))

    cmd = [
        "nextpnr-ecp5", "--quiet",
        np.get("device", "--12k"),
        "--package", np.get("--package", "CABGA256"),
        "--speed", np.get("--speed", "8"),
        "--json", os.path.join(out, "top.json"),
        "--lpf", os.path.join(out, "top.lpf"),
        "--textcfg", os.path.join(out, "ref.config"),
        "--write", os.path.join(out, "ref_placed.json"),
        "--log", os.path.join(out, "nextpnr.log"),
    ]
    log.info("running: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log.error("nextpnr failed (rc=%d)", r.returncode)
        log.error("stderr tail:\n%s", r.stderr[-3000:])
        return r.returncode
    log.info("wrote %s and %s",
             os.path.join(out, "ref.config"),
             os.path.join(out, "ref_placed.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
