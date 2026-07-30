#!/usr/bin/env python3.15t
"""Write `bits.db` back out, and prove it byte-exact against every shipped file.

WHY THIS EXISTS
---------------
`trellis_db.py` reads `bits.db`.  This writes it.  Together they are the missing
half of running prjtrellis's fuzzers on our own stack.

The fuzzers currently build the database through pytrellis: `get_tile_bitdata`
and `TileLocator` to read, then `BitGroup`/`ConfigBit`/`EnumSettingBits`/
`WordSettingBits`/`ArcData`/`FixedConnection` to accumulate and serialise back.
The read side we already have.  This is the write side.

It matters because of the 0x72 defect (docs/upstream-errors.md): the fuzzers decode
every Diamond variant with `pytrellis.Bitstream.read_bit(...).deserialise_chip()`,
which FAILS OUTRIGHT on EFB-active designs -- measured, 6 of 6 EFB fuzz targets.
Bits it cannot see are recorded as "this parameter has no bits", which is
indistinguishable in the database from a parameter nobody fuzzed.  Our decoder reads
those bitstreams.  So regenerating with our stack is a CORRECTNESS fix, not a
refresh -- but only once we can write the database, which is what this does.

THE ORDERING PROBLEM, AND WHY BYTE-EXACTNESS IS STILL POSSIBLE
-------------------------------------------------------------
The parsed model deliberately drops layout: bits live in a `frozenset`, so
token order within a line is lost.  That would normally make byte-exact output
impossible.  It is recoverable because prjtrellis always writes bit tokens sorted
by (frame, bit) -- verified across **223,325 multi-bit lines** in MachXO2 and ECP5,
with **zero** exceptions.  So sorting reconstructs the original order rather than
guessing at it.

Verified rather than assumed, which is the point: `--verify` re-emits every shipped
`bits.db` from its own parse and compares byte-for-byte.  Anything less would leave
us generating database files whose fidelity is untested, and a wrong database is the
kind of error that produces a plausible, wrong netlist rather than a crash.

    scripts/trellis_db_write.py --verify [--family MachXO2] [--show N]

Logs to ./tmp/logs/trellis_db_write.log; JSON to tmp/trellis_db_write.json.
"""
from __future__ import annotations

import argparse
import difflib
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toolchain  # noqa: E402
from trellis_db import parse_tile_db  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp/logs"

MUX_HEADER = "# Routing Mux Bits"
CFG_HEADER = "# Non-Routing Configuration"
FC_HEADER = "# Fixed Connections"


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("trellis_db_write")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "trellis_db_write.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def _bits(bits) -> str:
    """Bit tokens in prjtrellis's canonical order: sorted by (frame, bit).

    `-` for the empty set, which is how the default encoding is written.
    """
    if not bits:
        return "-"
    return " ".join(str(b) for b in sorted(bits, key=lambda b: (b.frame, b.bit,
                                                                b.invert)))


def format_tile_db(db) -> str:
    """Canonical `bits.db` text for a parsed TileDb.

    ALL THREE section headers are always written, even for a tile with nothing in
    it -- an empty file is exactly the three headers separated by blank lines, as
    `B_DUMMY_ENDL` shows.  Emitting them conditionally is wrong and was the first
    thing --verify caught, on all 142 MachXO2 tiles at once.

    Every block (mux, word, enum, fixed_conn) is followed by a blank line, and the
    file ends with one, so blocks are self-terminating rather than separated.
    """
    mux_sec: list[str] = [MUX_HEADER]
    cfg_sec: list[str] = [CFG_HEADER]
    fc_sec: list[str] = [FC_HEADER]
    out = mux_sec
    for mux in db.muxes.values():
        out.append(f".mux {mux.sink}")
        for arc in mux.arcs:
            out.append(f"{arc.source} {_bits(arc.bits)}")
        out.append("")
    out = cfg_sec
    for w in db.words.values():
        head = f".config {w.name}"
        if w.default is not None:
            head += f" {w.default}"
        out.append(head)
        # One token per line, in DECLARED order -- this is a bit vector, so order
        # is meaning, not layout, and must not be sorted.
        for b in w.bits:
            # None is a held position in the vector, written as `-`.
            out.append("-" if b is None else str(b))
        out.append("")
    for e in db.enums.values():
        head = f".config_enum {e.name}"
        if e.default is not None:
            head += f" {e.default}"
        out.append(head)
        for value, bits in e.values.items():
            out.append(f"{value} {_bits(bits)}")
        out.append("")
    out = fc_sec
    for sink, source in db.fixed_conns:
        out.append(f".fixed_conn {sink} {source}")
        out.append("")
    # Sections are joined by ONE blank line.  That single rule explains both
    # observed shapes: an empty tile is three headers with blanks between them,
    # and a populated tile has TWO blanks before a header -- one terminating the
    # previous block, one joining the sections.
    return "\n".join(mux_sec + [""] + cfg_sec + [""] + fc_sec) + "\n"


def verify(family, root, log, show):
    td = os.path.join(root, family, "tiledata")
    if not os.path.isdir(td):
        log.info("%s: no tiledata", family)
        return None
    tiles = sorted(os.listdir(td))
    same = differ = failed = 0
    diffs = []
    for tile in tiles:
        p = Path(td) / tile / "bits.db"
        if not p.is_file():
            continue
        original = p.read_text()
        try:
            db = parse_tile_db(p)
            emitted = format_tile_db(db)
        except Exception as exc:
            failed += 1
            log.error("  %s: parse/emit failed: %s: %s", tile,
                      type(exc).__name__, str(exc)[:120])
            continue
        if emitted == original:
            same += 1
        else:
            differ += 1
            if len(diffs) < show:
                d = list(difflib.unified_diff(
                    original.splitlines(), emitted.splitlines(),
                    "shipped", "emitted", lineterm="", n=1))
                diffs.append((tile, d[:14]))
    log.info("%s: %d byte-identical, %d differ, %d failed (of %d tiles)",
             family, same, differ, failed, same + differ + failed)
    for tile, d in diffs:
        log.info("  ---- first difference in %s ----", tile)
        for line in d:
            log.info("    %s", line)
    return {"family": family, "identical": same, "differ": differ,
            "failed": failed}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true",
                    help="re-emit every shipped bits.db and compare byte-for-byte")
    ap.add_argument("--family", default="", help="limit to one family")
    ap.add_argument("--show", type=int, default=2,
                    help="how many differing tiles to show a diff for")
    ap.add_argument("--json", default=str(REPO / "tmp/trellis_db_write.json"))
    args = ap.parse_args()
    log = setup_logging()
    root = toolchain.trellis_dbroot()

    if not args.verify:
        sys.exit("nothing to do: pass --verify (writing into the shipped database "
                 "is deliberately not offered here -- generation belongs to the "
                 "fuzzer harness, this module only formats)")

    fams = ([args.family] if args.family
            else [f for f in sorted(os.listdir(root))
                  if os.path.isdir(os.path.join(root, f, "tiledata"))])
    results = [r for r in (verify(f, root, log, args.show) for f in fams) if r]
    tot_same = sum(r["identical"] for r in results)
    tot_diff = sum(r["differ"] for r in results)
    tot_fail = sum(r["failed"] for r in results)
    log.info("==== TOTAL: %d identical, %d differ, %d failed ====",
             tot_same, tot_diff, tot_fail)
    with open(args.json, "w") as fh:
        json.dump({"results": results, "identical": tot_same,
                   "differ": tot_diff, "failed": tot_fail}, fh, indent=2,
                  sort_keys=True)
    log.info("results -> %s", args.json)
    return 1 if (tot_diff or tot_fail) else 0


if __name__ == "__main__":
    sys.exit(main())
