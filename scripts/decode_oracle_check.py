#!/usr/bin/env python3.15t
"""Check the native bitstream decoder against the reference unpackers.

The native decoder has to stay byte-faithful for MachXO2 (production) while
gaining ECP5.  The only way to claim that is to diff its output against the
authoritative tool for each family and require equality:

    ECP5      ecpunpack   (oss-cad-suite)
    MachXO2   ecpunpack   also handles MachXO2/XO3 given --idcode/device

Differences in `.comment` lines are ignored: those record the package, which
the reference tool takes from a command-line argument rather than decoding
from the bitstream, so they are metadata rather than recovered content.  Every
other line — every tile, arc, LUT INIT and enum — must match exactly.

    python3.15t scripts/decode_oracle_check.py [--workers N]

Runs the corpus in parallel (each decode is independent).  Exit status is
non-zero if any bitstream differs.  Logs to ./tmp/logs/decode_oracle_check.log
as well as the terminal.
"""
import argparse
import concurrent.futures
import difflib
import logging
import os
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import toolchain  # noqa: E402  (path set above)

DBROOT = toolchain.trellis_dbroot()
ECPUNPACK = toolchain.tool("ecpunpack", "ECPUNPACK")

# The test designs are built in the cynthion-workspace repository, so only the
# paths RELATIVE to it are knowable here; the root comes from $ECP5_TEST or a
# sibling checkout (#90).  Missing entries are skipped with a note rather than
# failing the run, because this check is about decode agreement on whichever
# designs are present, not about having all six.
_WS = toolchain.sibling_repo("cynthion-workspace", "ECP5_TEST",
                             "ECP5 test designs", required=False)

# (label, path relative to the workspace, device).  Small first, then the large
# real designs.
_CORPUS_REL = [
    ("led_patterns", "ecp5-test/led_patterns.bit", "LFE5U-12F"),
    ("analyzer", "tmp/gsg/analyzer/top.bit", "LFE5U-12F"),
    ("adv_uart", "ecp5-test/adv_uart/build/top.bit", "LFE5U-12F"),
    ("riscv", "ecp5-test/riscv/build/top.bit", "LFE5U-12F"),
    ("usb_bulk", "ecp5-test/usb_bulk/build/top.bit", "LFE5U-12F"),
    ("hyperram", "ecp5-test/hyperram/build/top.bit", "LFE5U-12F"),
]
CORPUS = ([(label, os.path.join(_WS, rel), dev)
           for label, rel, dev in _CORPUS_REL] if _WS else [])

_lock = threading.Lock()


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


def meaningful(path):
    """Config lines that represent DECODED content (drop tool metadata)."""
    out = []
    for line in open(path):
        s = line.rstrip("\n")
        if s.startswith(".comment"):
            continue
        out.append(s)
    return out


def check_one(label, bitpath, device, log):
    if not os.path.exists(bitpath):
        return label, None, "bitstream not present"
    outdir = "tmp/decode-oracle"
    os.makedirs(outdir, exist_ok=True)
    oracle = os.path.join(outdir, f"{label}.oracle.config")
    native = os.path.join(outdir, f"{label}.native.config")

    r = subprocess.run([ECPUNPACK, bitpath, oracle],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return label, False, f"ecpunpack failed: {r.stderr[-200:]}"

    import native_config
    try:
        text, pb, _bram = native_config.config_from_file(
            bitpath, device=device, db_root=DBROOT)
    except Exception as e:                                   # noqa: BLE001
        return label, False, f"native decode raised {type(e).__name__}: {e}"
    with open(native, "w") as fh:
        fh.write(text)

    a, b = meaningful(oracle), meaningful(native)
    if a == b:
        with _lock:
            log.info("%-14s IDENTICAL  (%d lines, %d/%d frames, crc=%s)",
                     label, len(a), pb.frames_read, pb.num_frames,
                     pb.crc_verified)
        return label, True, f"{len(a)} lines"

    diff = list(difflib.unified_diff(a, b, "oracle", "native", lineterm="",
                                     n=1))
    with _lock:
        log.error("%-14s DIFFERS (%d diff lines)", label, len(diff))
        for ln in diff[:24]:
            log.error("    %s", ln)
    return label, False, f"{len(diff)} diff lines"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    log = setup_logging("decode_oracle_check")
    log.info("comparing native decoder against %s", ECPUNPACK)

    results = []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(check_one, lb, bp, dv, log) for lb, bp, dv in CORPUS]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())

    log.info("---- summary ----")
    ok = skipped = bad = 0
    for label, res, note in sorted(results):
        if res is None:
            skipped += 1
            log.info("  %-14s SKIP  %s", label, note)
        elif res:
            ok += 1
            log.info("  %-14s PASS  %s", label, note)
        else:
            bad += 1
            log.error("  %-14s FAIL  %s", label, note)
    log.info("%d identical, %d differing, %d skipped", ok, bad, skipped)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
