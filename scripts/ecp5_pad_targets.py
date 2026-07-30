#!/usr/bin/env python3.15t
"""Pick package pins for the BASE_TYPE round-trip differ (#85, #96).

WHAT THIS IS FOR
----------------
#96 calls the Diamond round-trip differ "the highest-value item across all this
work": build two targets that differ only in the I/O standard on one pad, decode
both, and diff the tile bits.  If Diamond emits different bits where the open
database says the two standards are indistinguishable, the degeneracy is a
fuzzing gap and the correct encodings can be read straight off the diff.

That experiment needs a pad that physically lands in the degenerate tile, and
nothing in #85 or #96 says which package pin that is.  `enum_degeneracy.py`
names the tile TYPES; this turns those into concrete pin names to constrain.

It also picks a CONTROL pad, which matters more than the test pad.  `PICL1`
resolves the same 84 values into 28 encodings, so two standards on a PICL1 pad
MUST produce different bits.  If the control shows no difference, the experiment
is broken -- wrong pad, wrong constraint syntax, Diamond optimising the input
away -- and a null result on the test pad would be meaningless.  Without it, "no
bits changed" cannot be distinguished from "the build never applied the setting".

    scripts/ecp5_pad_targets.py [--device LFE5U-25F] [--package CABGA256]
                                [--bel A] [--json PATH]

Logs to ./tmp/logs/ecp5_pad_targets.log.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toolchain  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"

# Tile-type key in tilegrid.json is "<name>:<type>", and the name carries the
# row/column as R<r>C<c>.
_RC_RE = re.compile(r"R(\d+)C(\d+)")


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("ecp5_pad_targets")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "ecp5_pad_targets.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def tiles_by_rc(device, db):
    """(row, col) -> [tile types present there]."""
    tg = json.load(open(os.path.join(db, "ECP5", device, "tilegrid.json")))
    out = {}
    for key in tg:
        name, _, ttype = key.partition(":")
        m = _RC_RE.search(name)
        if not m:
            continue
        rc = (int(m.group(1)), int(m.group(2)))
        out.setdefault(rc, []).append(ttype)
    return out


def pad_map(device, package, bel, db, log):
    """Package pin -> the PIC tile type holding it, for one PIO bel letter."""
    iodb = json.load(open(os.path.join(db, "ECP5", device, "iodb.json")))
    pins = iodb["packages"].get(package)
    if pins is None:
        sys.exit(f"package {package!r} not in iodb for {device}; have "
                 f"{sorted(iodb['packages'])}")
    rc_tiles = tiles_by_rc(device, db)
    rows = []
    for pin, info in sorted(pins.items()):
        if info.get("pio") != bel:
            continue
        rc = (info["row"], info["col"])
        # A PIO's row/col hosts several tiles (CIB, routing, the PIC itself);
        # only the PIC* tile carries PIOA.BASE_TYPE.
        pics = [t for t in rc_tiles.get(rc, []) if t.startswith("PIC")]
        for t in pics:
            rows.append({"pin": pin, "tile_type": t, "row": rc[0], "col": rc[1],
                         "bel": f"PIO{bel}"})
    log.info("%s/%s: %d pin(s) on PIO%s mapped to a PIC tile", device, package,
             len(rows), bel)
    return rows


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="LFE5U-25F")
    ap.add_argument("--package", default="CABGA256")
    ap.add_argument("--bel", default="A", help="PIO bel letter (default A)")
    ap.add_argument("--json", default=str(REPO / "tmp/ecp5_pad_targets.json"))
    args = ap.parse_args()
    log = setup_logging()
    db = toolchain.trellis_dbroot()

    rows = pad_map(args.device, args.package, args.bel, db, log)
    by_tile = {}
    for r in rows:
        by_tile.setdefault(r["tile_type"], []).append(r["pin"])

    # Resolution per tile type, straight from the database, so the target list and
    # the degeneracy measurement cannot drift apart.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from enum_degeneracy import survey
    res = {r["tile"]: r for r in survey("ECP5", f"PIO{args.bel}.BASE_TYPE", 2, log)}

    log.info("---- PIO%s pads by tile type ----", args.bel)
    table = []
    for ttype, pins in sorted(by_tile.items()):
        r = res.get(ttype)
        table.append({
            "tile_type": ttype, "pins": pins, "n_pins": len(pins),
            "values": r["values"] if r else None,
            "encodings": r["encodings"] if r else None,
            "resolution": r["resolution"] if r else None,
        })
    table.sort(key=lambda t: (t["resolution"] is None, t["resolution"] or 0))
    for t in table:
        log.info("  %-14s %3d pad(s)  %s enc/%s values  e.g. %s", t["tile_type"],
                 t["n_pins"],
                 str(t["encodings"]).rjust(3), str(t["values"]).ljust(3),
                 ", ".join(t["pins"][:6]))

    degenerate = [t for t in table if t["resolution"] is not None
                  and t["resolution"] <= 0.10]
    reference = [t for t in table if t["resolution"] is not None
                 and t["resolution"] >= 0.30]
    log.info("")
    if degenerate and reference:
        d, c = degenerate[0], reference[-1]
        log.info("EXPERIMENT TARGETS")
        log.info("  test pad    %-6s in %-12s (%d values -> %d encodings)",
                 d["pins"][0], d["tile_type"], d["values"], d["encodings"])
        log.info("  control pad %-6s in %-12s (%d values -> %d encodings)",
                 c["pins"][0], c["tile_type"], c["values"], c["encodings"])
        log.info("  Build each twice, changing ONLY the I/O standard, and diff "
                 "the decoded tile bits.")
        log.info("  The control MUST differ between the two standards. If it "
                 "does not, the experiment is broken and a null result on the "
                 "test pad means nothing.")
    else:
        log.info("no degenerate/reference pair among these pads -- try another "
                 "package or --bel")

    with open(args.json, "w") as fh:
        json.dump({"device": args.device, "package": args.package,
                   "bel": f"PIO{args.bel}", "tiles": table}, fh, indent=2,
                  sort_keys=True)
    log.info("results -> %s", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
