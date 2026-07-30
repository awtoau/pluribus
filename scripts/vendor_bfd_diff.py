#!/usr/bin/env python3.15t
"""Dump the vendor BFD and diff its tile types against the Trellis database.

The BFD is Diamond's own bitstream frame database -- the tile-to-bit mapping that
prjtrellis reverse-engineered by experiment.  `bstool` dumps it to ASCII, which
makes "what does the open database not know?" a finite, named list instead of an
open question.

#93 did this for ECP5 by hand and found trellis is a strict subset: 185 of the
vendor's 198 tile types, with 13 missing and NONE wrong.  This generalises it, and
the production family turns out to be the same shape.

WHY IT MATTERS MORE THAN A COUNT
--------------------------------
Two opposite conclusions come out of one comparison:

  * `trellis-only` should be EMPTY.  A tile type trellis has and the vendor does
    not would mean the open database invented something, which would undermine
    every decode.  It is empty for both families -- a strong independent
    endorsement of prjtrellis's accuracy.
  * `vendor-only` is a WORK LIST.  Each name is a tile the vendor documents and
    the open flow cannot decode, and the BFD gives its geometry, sites and node
    table -- a direct route to ground truth rather than more fuzzing in the dark.

INVOCATION NOTES (both cost time to rediscover)
-----------------------------------------------
`bstool` needs `LD_LIBRARY_PATH` for `libbasbs.so` and `FOUNDRY` set, and the
argument order is NOT what its usage text says: `-a -b <ARCH> <in.bfd> <out.asc>`.
It also writes beside its input, so the input is copied to a writable directory
first.  ARCH is the Diamond FAMILY name (`MachXO2`, `ECP5U`), not the device-tree
name (`xo2c00`, `sa5p00`) -- and confusing the two is the #92 trap, where `ep5c00`
reads like ECP5 and is actually LatticeECP3.

    scripts/vendor_bfd_diff.py [--family MachXO2] [--keep-asc]

Logs to ./tmp/logs/vendor_bfd_diff.log; JSON to tmp/vendor_bfd_diff.json.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toolchain  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"

# Diamond family name -> (device trees, trellis family).  A family can span SEVERAL
# trees and the union is what matters -- getting this wrong produces a false
# accusation, not a quiet miss.
#
# Learned the hard way on MachXO: mapped to `mj5g00` alone, the diff reported 38
# TRELLIS-ONLY tile types, i.e. "the open database invented 38 tiles".  It had not.
# `mj5g00e` carries them (CLK0_2K, PIC2_L_EBR2K_1, PIC2_L_PLL1K, PIC2_R_LVDS,
# PIC4_L, ...), so MachXO's vendor data is split across two trees even though
# DiamondDevFile.xml maps every MachXO PART to `mj5g00`.  Part-to-tree mapping is
# therefore NOT the same thing as data-to-tree mapping, and only the second matters
# here.  Same family of error as #92's ep5c00/sa5p00 trap.
FAMILIES = {
    "MachXO2":  (("xo2c00",), "MachXO2"),
    "ECP5U":    (("sa5p00",), "ECP5"),
    "MachXO":   (("mj5g00", "mj5g00e", "mj5g00p"), "MachXO"),
    "MachXO3D": (("se5c00",), "MachXO3D"),
}

_TILE_RE = re.compile(r'^Tile\s+"([^"]+)"', re.M)


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("vendor_bfd_diff")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "vendor_bfd_diff.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def dump_bfd(arch, trees, log, keep):
    """Run bstool over every tree of a family; returns the UNION of tile types."""
    tiles = set()
    for tree in trees:
        got = _dump_one(arch, tree, log, keep)
        if got:
            tiles |= got
    return tiles or None


def _dump_one(arch, tree, log, keep):
    d = toolchain.diamond_root()
    bfd = os.path.join(d, "ispfpga", tree, "data", f"{tree}.bfd")
    if not os.path.isfile(bfd):
        log.info("  %s/%s: no BFD in this tree (MachXO3L/LF ship none)", arch, tree)
        return None
    bstool = os.path.join(d, "ispfpga", "bin", "lin64", "bstool")
    if not os.path.isfile(bstool):
        toolchain.die(f"bstool not found at {bstool}")
    work = REPO / "tmp" / f"bfd_{tree}"
    work.mkdir(parents=True, exist_ok=True)
    local = work / f"{tree}.bfd"
    if not local.exists():
        shutil.copy(bfd, local)
    asc = work / f"{tree}.asc"
    env = dict(os.environ,
               LD_LIBRARY_PATH=os.pathsep.join([
                   os.path.join(d, "bin", "lin64"),
                   os.path.join(d, "ispfpga", "bin", "lin64"),
                   os.environ.get("LD_LIBRARY_PATH", "")]),
               FOUNDRY=os.path.join(d, "ispfpga"))
    if not asc.exists():
        r = subprocess.run([bstool, "-a", "-b", arch, local.name, asc.name],
                           cwd=work, capture_output=True, text=True, env=env)
        if r.returncode != 0 or not asc.exists():
            log.error("  %s: bstool rc=%d: %s", arch, r.returncode,
                      (r.stdout + r.stderr).strip()[-300:])
            return None
    size = asc.stat().st_size
    text = asc.read_text(errors="replace")
    tiles = set(_TILE_RE.findall(text))
    log.info("  %s/%s: %.1f MB ASCII, %d tile types", arch, tree, size / 1e6,
             len(tiles))
    if not keep:
        asc.unlink(missing_ok=True)
        local.unlink(missing_ok=True)
    return tiles


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", default="", choices=[""] + sorted(FAMILIES))
    ap.add_argument("--keep-asc", action="store_true",
                    help="keep the ASCII dump (tens of MB) for inspection")
    ap.add_argument("--json", default=str(REPO / "tmp/vendor_bfd_diff.json"))
    args = ap.parse_args()
    log = setup_logging()
    db = toolchain.trellis_dbroot()

    out = {}
    for arch in ([args.family] if args.family else sorted(FAMILIES)):
        trees, tfam = FAMILIES[arch]
        log.info("==== %s (trees %s, trellis family %s) ====", arch,
                 "+".join(trees), tfam)
        vendor = dump_bfd(arch, trees, log, args.keep_asc)
        if vendor is None:
            continue
        td = os.path.join(db, tfam, "tiledata")
        trellis = set(os.listdir(td)) if os.path.isdir(td) else set()
        both = vendor & trellis
        only_t = sorted(trellis - vendor)
        only_v = sorted(vendor - trellis)
        log.info("  vendor %d, trellis %d, in both %d", len(vendor), len(trellis),
                 len(both))
        if only_t:
            # This is the alarming direction: trellis claiming a tile the vendor
            # does not have would mean the open database invented one.
            log.error("  TRELLIS-ONLY (%d) -- trellis has tiles the vendor does "
                      "not: %s", len(only_t), only_t[:20])
        else:
            log.info("  trellis-only: 0 -- trellis is a strict SUBSET, it invented "
                     "nothing and got no tile name wrong")
        log.info("  vendor-only (%d) -- documented by the vendor, not decodable by "
                 "the open flow:", len(only_v))
        for i in range(0, len(only_v), 6):
            log.info("      %s", ", ".join(only_v[i:i + 6]))
        out[arch] = {"vendor": len(vendor), "trellis": len(trellis),
                     "both": len(both), "trellis_only": only_t,
                     "vendor_only": only_v}

    with open(args.json, "w") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    log.info("results -> %s", args.json)
    bad = [a for a, v in out.items() if v["trellis_only"]]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
