#!/usr/bin/env python3
"""Import board-provided annotation layers into the DB (issue #12).

The pipeline already imports pad labels (pins.tsv → pad_map) and net names
(nets.tsv → net_names) at load time. This adds the remaining human-curated
layers a board can supply, keyed by bitstream label:

    spi_registers.tsv   → spi_registers   (register map: bank/addr/name/bit-fields)
    cell_names.tsv      → cell_names       (Ghidra-style cell annotations)
    open_questions.tsv  → open_questions   (tracked unknowns / RE questions)

Board-agnostic: files come from a board dir (or explicit paths), never baked in.
Always-rebuild per bitstream: every run deletes this bitstream's rows in each
table it has a source for, then reinserts — no stale rows.

Usage:
    python3 annotate.py --bitstream V07 --board boards/aw2-2d82auto
    python3 annotate.py --bitstream V07 --spi-registers path/to/spi_registers.tsv

TSV formats (tab-separated, '#' comment lines and a header row ignored):
    spi_registers.tsv   bank  address  name  description  bit_fields(JSON list)
    cell_names.tsv      cell  name  description  confidence
    open_questions.tsv  issue_num  title  description  status  related_nets(JSON) \
                        related_cells(JSON)  blocker
"""
import argparse
import json
import os
import sys

from sqlalchemy import delete, insert, select

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

import schema        # noqa: E402
from db import engine, die   # noqa: E402


def _rows(path):
    """Yield tab-split non-comment, non-blank rows; skip a leading header row."""
    with open(path) as fh:
        first = True
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cells = line.split("\t")
            # Skip a header row (first data line whose first cell is a known label).
            if first:
                first = False
                if cells[0].strip().lower() in _HEADERS:
                    continue
            yield [c.strip() for c in cells]


_HEADERS = {"bank", "cell", "issue_num", "net", "address"}


def _int(s):
    s = s.strip()
    return int(s, 0) if s else None   # 0 → auto-base, so 0x.. hex works


def _json(s, default):
    s = s.strip()
    if not s:
        return default
    return json.loads(s)


def _spi_registers(rows, bs_id):
    out = []
    for r in rows:
        bank, addr, name = r[0], r[1], r[2]
        desc = r[3] if len(r) > 3 else None
        bits = _json(r[4], []) if len(r) > 4 else []
        out.append({"bitstream": bs_id, "bank": bank, "address": _int(addr),
                    "name": name, "description": desc or None, "bit_fields": bits})
    return out


def _cell_names(rows, bs_id):
    out = []
    for r in rows:
        cell, name = r[0], r[1]
        desc = r[2] if len(r) > 2 else None
        conf = r[3] if len(r) > 3 and r[3] else "speculative"
        out.append({"bitstream": bs_id, "cell": cell, "name": name,
                    "description": desc or None, "confidence": conf})
    return out


def _open_questions(rows, bs_id):
    out = []
    for r in rows:
        issue = _int(r[0]) if r[0] else None
        title = r[1]
        desc = r[2] if len(r) > 2 else None
        status = r[3] if len(r) > 3 and r[3] else "open"
        nets = _json(r[4], None) if len(r) > 4 else None
        cells = _json(r[5], None) if len(r) > 5 else None
        blocker = r[6] if len(r) > 6 and r[6] else None
        out.append({"bitstream": bs_id, "issue_num": issue, "title": title,
                    "description": desc or None, "status": status,
                    "related_nets": nets, "related_cells": cells, "blocker": blocker})
    return out


_LAYERS = [
    ("spi_registers.tsv",  schema.spi_registers,  _spi_registers),
    ("cell_names.tsv",     schema.cell_names,     _cell_names),
    ("open_questions.tsv", schema.open_questions, _open_questions),
]


def annotate(label, board=None, paths=None):
    schema.init()
    eng = engine()
    with eng.begin() as conn:
        row = conn.execute(
            select(schema.bitstreams.c.id).where(schema.bitstreams.c.label == label)
        ).fetchone()
        if row is None:
            die(f"bitstream {label!r} not loaded — run load.py first")
        bs_id = row[0]

        total = 0
        for fname, table, builder in _LAYERS:
            path = (paths or {}).get(fname)
            if path is None and board:
                cand = os.path.join(board, fname)
                path = cand if os.path.exists(cand) else None
            if not path:
                continue
            if not os.path.exists(path):
                die(f"annotation source not found: {path}")
            rows = builder(list(_rows(path)), bs_id)
            # always-rebuild: clear this bitstream's rows, then insert
            conn.execute(delete(table).where(table.c.bitstream == bs_id))
            if rows:
                conn.execute(insert(table), rows)
            print(f"  {fname:20} {len(rows):5} rows -> {table.name}")
            total += len(rows)
    print(f"annotate: {label} — {total} rows imported")
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bitstream", required=True, help="bitstream label (already loaded)")
    ap.add_argument("--board", help="board dir containing the annotation TSVs")
    ap.add_argument("--spi-registers", help="explicit spi_registers.tsv path")
    ap.add_argument("--cell-names", help="explicit cell_names.tsv path")
    ap.add_argument("--open-questions", help="explicit open_questions.tsv path")
    args = ap.parse_args()

    paths = {}
    if args.spi_registers:  paths["spi_registers.tsv"] = args.spi_registers
    if args.cell_names:     paths["cell_names.tsv"] = args.cell_names
    if args.open_questions: paths["open_questions.tsv"] = args.open_questions
    if not args.board and not paths:
        ap.error("need --board or at least one explicit annotation path")

    annotate(args.bitstream, board=args.board, paths=paths or None)


if __name__ == "__main__":
    main()
