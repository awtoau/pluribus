#!/usr/bin/env python3
"""Compare two Trellis .config files — highlights per-tile differences.

Primary use case: validate nextpnr IOLOGIC output against Diamond-generated
reference configs for the same design. Diffs are shown at tile+field level
so only meaningful bitstream changes surface, not cosmetic arc ordering.

Usage:
  # Compare nextpnr IOLOGIC output against Diamond reference
  python3 scripts/compare_config.py \\
      ref.config nextpnr_out.config --tile-type PIC_T0 PIC_B0 PIC_L0 PIC_R0

  # Compare V04 vs V07 full bitstreams
  python3 scripts/compare_config.py \\
      fpga/v4/DS1302_2019071801.bin.config \\
      fpga/v7/FPGA_V07.bin.config

  # Show only IOLOGIC enum differences (suppress arcs)
  python3 scripts/compare_config.py ref.config out.config --no-arcs

Output format:
  Each changed tile is listed.  Fields are tagged:
    + added in B (out)
    - removed (only in A / ref)
    ~ changed value
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path


# ── Parser ────────────────────────────────────────────────────────────────────

TILE_RE  = re.compile(r"^\.tile\s+(\S+):(\S+)")
ARC_RE   = re.compile(r"^arc:\s+(\S+)\s+(\S+)")
ENUM_RE  = re.compile(r"^enum:\s+(\S+)\s+(\S+)")
WORD_RE  = re.compile(r"^word:\s+(\S+)\s+(\S+)")
UNKN_RE  = re.compile(r"^unknown:\s+(\S+)")
DEVT_RE  = re.compile(r"^\.device\s+(\S+)")
VART_RE  = re.compile(r"^\.variant\s+(\S+)")


class TileData:
    """Contents of one .tile block."""
    __slots__ = ("tile_type", "arcs", "enums", "words", "unknowns")

    def __init__(self, tile_type):
        self.tile_type = tile_type
        self.arcs:     set   = set()
        self.enums:    dict  = {}   # key → value
        self.words:    dict  = {}
        self.unknowns: set   = set()


def parse_config(path: str) -> dict:
    """Return {tile_name: TileData, "_meta": {device, variant}}."""
    tiles = {}
    meta = {}
    cur_name = None
    cur = None

    with open(path) as fh:
        for line in fh:
            s = line.strip()
            m = DEVT_RE.match(s)
            if m:
                meta["device"] = m.group(1)
                continue
            m = VART_RE.match(s)
            if m:
                meta["variant"] = m.group(1)
                continue
            m = TILE_RE.match(s)
            if m:
                cur_name = m.group(1)
                tile_type = m.group(2)
                cur = TileData(tile_type)
                tiles[cur_name] = cur
                continue
            if cur is None:
                continue
            m = ARC_RE.match(s)
            if m:
                cur.arcs.add((m.group(1), m.group(2)))
                continue
            m = ENUM_RE.match(s)
            if m:
                cur.enums[m.group(1)] = m.group(2)
                continue
            m = WORD_RE.match(s)
            if m:
                cur.words[m.group(1)] = m.group(2)
                continue
            m = UNKN_RE.match(s)
            if m:
                cur.unknowns.add(m.group(1))

    tiles["_meta"] = meta
    return tiles


# ── Comparison ────────────────────────────────────────────────────────────────

def diff_tiles(a: TileData, b: TileData, show_arcs: bool) -> list[str]:
    lines = []

    # enums
    all_keys = sorted(set(a.enums) | set(b.enums))
    for k in all_keys:
        av, bv = a.enums.get(k), b.enums.get(k)
        if av == bv:
            continue
        if av is None:
            lines.append(f"  + enum {k} = {bv}")
        elif bv is None:
            lines.append(f"  - enum {k} = {av}")
        else:
            lines.append(f"  ~ enum {k}: {av}  →  {bv}")

    # words
    all_keys = sorted(set(a.words) | set(b.words))
    for k in all_keys:
        av, bv = a.words.get(k), b.words.get(k)
        if av == bv:
            continue
        if av is None:
            lines.append(f"  + word {k} = {bv}")
        elif bv is None:
            lines.append(f"  - word {k} = {av}")
        else:
            lines.append(f"  ~ word {k}: {av}  →  {bv}")

    # unknowns
    for u in sorted(b.unknowns - a.unknowns):
        lines.append(f"  + unknown {u}")
    for u in sorted(a.unknowns - b.unknowns):
        lines.append(f"  - unknown {u}")

    # arcs (optional)
    if show_arcs:
        for arc in sorted(b.arcs - a.arcs):
            lines.append(f"  + arc {arc[0]} ← {arc[1]}")
        for arc in sorted(a.arcs - b.arcs):
            lines.append(f"  - arc {arc[0]} ← {arc[1]}")

    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ref",  help="Reference config (Diamond or baseline)")
    ap.add_argument("out",  help="Config to compare against reference")
    ap.add_argument("--tile-type", nargs="*", metavar="TYPE",
                    help="Only show tiles whose type matches (substring). "
                         "E.g. PIC_T0 IOLOGIC EBR")
    ap.add_argument("--no-arcs", action="store_true",
                    help="Suppress arc differences (focus on enum/word/unknown)")
    ap.add_argument("--only-changed", action="store_true", default=True,
                    help="Only show tiles with differences (default: True)")
    ap.add_argument("--summary", action="store_true",
                    help="Print summary table only, no per-tile detail")
    args = ap.parse_args()

    ref_path, out_path = Path(args.ref), Path(args.out)
    if not ref_path.exists():
        print(f"ERROR: ref not found: {ref_path}", file=sys.stderr); sys.exit(2)
    if not out_path.exists():
        print(f"ERROR: out not found: {out_path}", file=sys.stderr); sys.exit(2)

    print(f"Reference : {ref_path}")
    print(f"Comparing : {out_path}")

    ref_tiles = parse_config(str(ref_path))
    out_tiles = parse_config(str(out_path))

    ref_meta = ref_tiles.pop("_meta", {})
    out_meta = out_tiles.pop("_meta", {})
    if ref_meta.get("device") != out_meta.get("device"):
        print(f"WARNING: device mismatch: {ref_meta.get('device')} vs {out_meta.get('device')}")

    # Tile filter
    def keep(tile_name: str, tile_type: str) -> bool:
        if not args.tile_type:
            return True
        return any(f in tile_type for f in args.tile_type)

    all_names = sorted(set(ref_tiles) | set(out_tiles))
    changed = []
    added = []
    removed = []

    for name in all_names:
        a = ref_tiles.get(name)
        b = out_tiles.get(name)
        tile_type = (a or b).tile_type

        if not keep(name, tile_type):
            continue

        if a is None:
            added.append(name)
            continue
        if b is None:
            removed.append(name)
            continue

        diffs = diff_tiles(a, b, show_arcs=not args.no_arcs)
        if diffs:
            changed.append((name, tile_type, diffs))

    # Output
    print(f"\nTiles only in ref   : {len(removed)}")
    print(f"Tiles only in out   : {len(added)}")
    print(f"Tiles with changes  : {len(changed)}")

    if removed and not args.summary:
        print("\n=== Only in ref (removed) ===")
        for n in removed[:20]:
            print(f"  {n}")
        if len(removed) > 20:
            print(f"  … and {len(removed)-20} more")

    if added and not args.summary:
        print("\n=== Only in out (added) ===")
        for n in added[:20]:
            print(f"  {n}")
        if len(added) > 20:
            print(f"  … and {len(added)-20} more")

    if changed and not args.summary:
        print("\n=== Changed tiles ===")
        for name, tile_type, diffs in changed:
            print(f"\n.tile {name}:{tile_type}")
            for d in diffs:
                print(d)

    total = len(removed) + len(added) + len(changed)
    print(f"\n{'IDENTICAL' if total == 0 else f'{total} tile(s) differ'}")
    sys.exit(0 if total == 0 else 1)


if __name__ == "__main__":
    main()
