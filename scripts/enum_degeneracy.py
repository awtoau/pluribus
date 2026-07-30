#!/usr/bin/env python3.15t
"""Rank tiles by how well one config field is RESOLVED, per family (#85).

`trellis_db_check.py` reports every degenerate enum in the database -- thousands
of them -- which establishes that a problem exists but not where to start.  This
answers the question that follows: for a given field, WHICH tile encodes it
properly, and which tiles collapse it?

That distinction is what makes #85 a fuzzing gap rather than a hardware limit.
`PIOA.BASE_TYPE` holds the same value set in several tiles; if one tile resolves
those values into many distinct bit patterns and another flattens them to a
handful, the values are clearly distinguishable in silicon and the flat tile is
simply under-fuzzed.  The well-resolved tile then doubles as the reference: it
shows what the correct encodings look like, so a round-trip differ knows what
answer it is trying to reproduce.

Why the ratio matters more than the raw count: a tile with 84 values and 3
encodings is not "mostly right", it is a coin flip across 81 of them.  Decode
picks one and cannot know it is wrong, which is the silent-wrongness class this
project treats as the dangerous one -- so the output is sorted by resolution,
worst last, and the worst rows are the work list.

    scripts/enum_degeneracy.py [--field PIOA.BASE_TYPE] [--family ECP5 ...]
                               [--min-values 2] [--json PATH]

Logs to ./tmp/logs/enum_degeneracy.log; JSON to tmp/enum_degeneracy.json.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trellis_db import DEFAULT_DB_ROOT, load_family  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"
DEFAULT_FAMILIES = ("ECP5", "MachXO2")


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("enum_degeneracy")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "enum_degeneracy.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def _bits_key(bits):
    """Canonical, order-independent key for a value's bit pattern.

    Sorted because bits.db lists bits in file order, which is not meaningful:
    two values with the same bits written in a different order are the same
    encoding, and comparing unsorted would report them as distinct.
    """
    return tuple(sorted((b.frame, b.bit, b.invert) for b in bits))


def survey(family, field, min_values, log):
    """Per-tile resolution of `field` across one family."""
    tiles = load_family(family, DEFAULT_DB_ROOT)
    rows = []
    for tname, tdb in sorted(tiles.items()):
        for fname, enum in sorted(getattr(tdb, "enums", {}).items()):
            if field and field != fname:
                continue
            values = getattr(enum, "values", None) or {}
            if len(values) < min_values:
                continue
            groups = {}
            for vname, bits in values.items():
                groups.setdefault(_bits_key(bits), []).append(vname)
            # An empty bit set means "this value is the default, encoded by the
            # absence of bits".  It is legitimately one encoding, so it counts,
            # but a field where MANY values share it is exactly the degeneracy.
            rows.append({
                "tile": tname, "field": fname,
                "values": len(values), "encodings": len(groups),
                "resolution": round(len(groups) / len(values), 4),
                "largest_collision": max((len(v) for v in groups.values()),
                                         default=0),
                "collisions": sorted(
                    (sorted(v) for v in groups.values() if len(v) > 1),
                    key=lambda g: (-len(g), g[0])),
            })
    rows.sort(key=lambda r: (-r["resolution"], r["tile"]))
    log.info("%s: %d tile/field row(s) for %s", family, len(rows),
             field or "every enum")
    return rows


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--field", default="PIOA.BASE_TYPE",
                    help="config field to survey; empty string means every enum")
    ap.add_argument("--family", nargs="*", default=list(DEFAULT_FAMILIES))
    ap.add_argument("--min-values", type=int, default=2,
                    help="skip fields with fewer values (default 2: a "
                         "single-value enum carries no information to lose)")
    ap.add_argument("--top", type=int, default=12,
                    help="rows to print per family (all go to the JSON)")
    ap.add_argument("--json", default=str(REPO / "tmp/enum_degeneracy.json"))
    args = ap.parse_args()
    log = setup_logging()

    out = {}
    for family in args.family:
        rows = survey(family, args.field, args.min_values, log)
        out[family] = rows
        if not rows:
            continue
        worst = rows[-1]
        # Compare LIKE WITH LIKE: only against tiles carrying the same number of
        # values.  A tile with 19 values resolving 12 of them says nothing about
        # one with 84, so ranking across different value counts would manufacture
        # a spread out of the value sets differing rather than the encodings.
        peers = [r for r in rows if r["values"] == worst["values"]]
        best = peers[0]
        log.info("  %-10s BEST  %-22s %3d values -> %3d encodings (%.0f%%)",
                 family, best["tile"], best["values"], best["encodings"],
                 100 * best["resolution"])
        log.info("  %-10s WORST %-22s %3d values -> %3d encodings (%.0f%%), "
                 "largest indistinguishable group %d",
                 family, worst["tile"], worst["values"], worst["encodings"],
                 100 * worst["resolution"], worst["largest_collision"])
        # The SPREAD between tiles is the whole argument, and the threshold has
        # to be more than "best > worst".  One tile resolving twice what another
        # manages, for the same value set on the same bel, is evidence the values
        # ARE distinguishable in silicon and the flat tile is under-fuzzed.  A
        # near-uniform spread is the opposite: it gives no internal reason to
        # believe the encodings could be finer, so the degeneracy may simply be
        # real -- several input standards can share one receiver setting and thus
        # one CRAM pattern.  Claiming a fuzzing gap from a 38-vs-36 difference
        # would be reading noise as a finding.
        ratio = (best["encodings"] / worst["encodings"]) if worst["encodings"] else 0
        if ratio >= 2:
            log.info("  %-10s => UNDER-FUZZED: %s resolves %d encodings where "
                     "%s manages %d for the same value set (%.1fx). One tile "
                     "showing the finer answer is what makes this a fuzzing "
                     "gap rather than a hardware limit.", family, best["tile"],
                     best["encodings"], worst["tile"], worst["encodings"], ratio)
        else:
            log.info("  %-10s => UNIFORM (%.2fx best/worst): every tile resolves "
                     "this field about equally, so there is NO internal evidence "
                     "of under-fuzzing. The aliases are real, but this family "
                     "gives no reference tile to read correct encodings from -- "
                     "settle it against the vendor, not against itself.",
                     family, ratio)
        log.info("  ---- %s, by resolution (worst last) ----", family)
        for r in (rows[:args.top // 2] + rows[-(args.top // 2):]
                  if len(rows) > args.top else rows):
            log.info("    %-24s %3d values %3d enc %5.0f%%  worst group %d",
                     r["tile"], r["values"], r["encodings"],
                     100 * r["resolution"], r["largest_collision"])

    with open(args.json, "w") as fh:
        json.dump({"field": args.field, "families": out}, fh, indent=2,
                  sort_keys=True)
    log.info("results -> %s", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
