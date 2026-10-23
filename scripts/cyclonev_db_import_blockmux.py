#!/usr/bin/env python3.15t
"""Import Cyclone V block-mux ground truth into pluribus's SQLite/Postgres DB.

WHY THIS EXISTS
----------------
The routing-node tables (cv_route_muxes/cv_route_lines/cv_route_drivers/
cv_p2r/cv_p2p, scripts/cyclonev_db_import_routes.py) cover the general
interconnect fabric. They say nothing about the muxes INSIDE a block: LAB
common logic (tdff/bdff clock-enable/clear-source selects, LUT mask bits),
M10K mode selection, DSP operational-mode/coefficient muxes, GPIO/PLL/HSSI
mux selection -- all currently un-fuzzed, currently absent from the DB. This
script imports exactly that layer, from the same kind of Mistral plain-text
ground truth as the routing import, following the same "read the producer
source, not the compiled consumer" discipline.

GRAMMAR (read from tools/mux_to_source.py's load_mux_data()/lab_expand(), the
PRODUCER-side reference parser -- not libmistral/cv-bmux.cc/cv-rmux.cc, the
compiled consumer those feed, which is out of scope this session):

  Non-indented line:  "<subtype> <mux> <stype>[:<bcount>] [<pos>...]"
    stype in {b, m, n, r}; an optional default suffix follows the stype
    letter for b/r only: '-' -> 0, '+' -> -1 (r) or 1 (b), else a HEX digit
    string parsed with int(d, 16) (NOT decimal -- e.g. opt-mux.txt's
    start_up_clock has suffix "3f" -> default 63, confirmed by running the
    real generator). bcount defaults to 1. span comes from the file's own
    per-subtype `tmap` (NOT uniform within one file -- e.g. dsp's g=1,c=8,
    d=12), reproduced verbatim below from mux_to_source.py lines 219-240.
    When present, position tokens for span>1 follow the SAME line, laid out
    bcount-fastest then span-next with exactly one pad token of stride
    (bcount+1) between each span row (the pad token is always literally '|'
    in this corpus, but it is consumed POSITIONALLY here, exactly mirroring
    load_mux_data()'s `ls[3+b + (bcount+1)*s]` indexing, not by filtering out
    '|' -- the parser never actually inspects what's at the pad slot).

  Indented sub-line, one of:
    "* <pos> <pos> ... <pos>"        -- one extra span row (bcount positions)
    "<hex> <name> [!]"               -- stype m: value -> name; trailing '!'
                                         marks this the default (its index
                                         recorded, not the hex value)
    "<hex> <int> [!]"                -- stype n: value -> number, same '!' rule

  <pos> is a bare int for 1D files (oram/pram) or "x.y" for 2D files (cram),
  selected per-file by `is_2d` -- matches load_mux_data()'s `w` closure.

RAM SPACES (verified against the loader call sites, not assumed from naming):
    oram  -- opt-mux.txt only                              (is_2d=True)
    pram  -- gpio/dqs16/fpll/cmuxc/cmuxv/cmuxh/dll/hssi/cbuf/lvl/pma3/pma3-c/
             serpar/term/hip/hmc                            (is_2d=False)
    cram  -- lab/mlab/m10k/dsp/hps_clocks                   (is_2d=True)
(opt-mux.txt IS is_2d=True in the real call -- "oram" position tokens are
still "x.y" pairs, same shape as cram; oram vs cram is a RAM-id distinction
on the consumer side, not a coordinate-shape distinction on this side.)

lab_expand() (mux_to_source.py lines 86-120) is a REAL transform applied to
lab-mux.txt/mlab-mux.txt's 'i'-subtype entries only, AFTER the normal parse:
one declared bit-row becomes 10 span rows (5 "top" half-LUT instances at
85-8i minus the row, 5 "bottom" at 8i plus the row), with an extra
MLAB-specific branch when the row is 64 bits wide (lut_mask) that splits the
row into two 32-bit halves with different offsets for the two boundary rows.
Reproduced verbatim below, not re-derived, and spot-checked against a live
run of the real generator (see docs/cyclonev-blockmux-status.md).

NOT PER-DIE (see schema.py's cv_block_muxes comment) -- confirmed by reading
the loader: load_mux_data() takes no chip/die parameter, mux_to_source.py's
CLI takes only a data-dir, and the compiled bm_*[] arrays in
libmistral/cv-bmux-data.cc are plain file-scope statics with no per-die
indirection anywhere in cv-bmux.cc/cv-rmux.cc. One import populates every
die's shared mux definitions; --mistral-root exists for path portability
only, not for a --die selector.

MEMORY: all 21 files total 4,650 lines (the largest, hip-mux.txt, is 900
lines) -- nothing like the routing import's multi-million-line files. No
streaming/batching needed; the whole dataset parses and inserts in one pass.
Still gated behind the same psutil.virtual_memory() check before the single
insert, for consistency with the established pattern (and because the
--max-ram-pct=85 default fix from that session applies unchanged to any
future concurrent use of this script).

Always-rebuild: deletes all cv_block_muxes rows before reinserting. Any
parse mismatch is db.die() -- fail fast, never a soft warning.

Logs to ./tmp/logs/cyclonev_db_import_blockmux.log.

Usage:
    python3.15t scripts/cyclonev_db_import_blockmux.py
    python3.15t scripts/cyclonev_db_import_blockmux.py --mistral-root /path/to/mistral
"""
import argparse
import json
import os
import sys
import time

import psutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import db
import schema

DEFAULT_MISTRAL_ROOT = "/mnt/2tb/git/mistral"
DEFAULT_MAX_RAM_PCT = 85.0

# ── load_mux_data() call table, reproduced verbatim from
# tools/mux_to_source.py lines 219-240 (mtype, tmap, is_2d, variantmap).
# mtype is the file's base name (data/<mtype>-mux.txt); dump_target is filled
# in separately below for the two files (cmuxv, cmuxh) that feed two
# dump_muxes() calls each.
LOAD_CALLS = [
    # mtype        tmap                                                    is_2d  variantmap
    ("opt",        {'g': 1},                                                True,  {}),
    ("gpio",       {'i': 4, 'x': 4, 'X': 4, 'g': 1, 'l': 2, 's': 1},         False, {'x': 1, 'X': 0, 's': 1}),
    ("dqs16",      {'g': 1, 'i': 16},                                       False, {}),
    ("fpll",       {'g': 1, 'e': 2, 'c': 9, 'l': 2},                        False, {}),
    ("lab",        {'g': 1, 'i': 1},                                        True,  {}),
    ("mlab",       {'g': 1, 'i': 1},                                        True,  {}),
    ("m10k",       {'g': 1, 'm': 256},                                      True,  {}),
    ("dsp",        {'g': 1, 'c': 8, 'd': 12},                                True,  {}),
    ("hps_clocks", {'i': 18},                                               True,  {}),
    ("cmuxc",      {'r': 6, 'R': 1, 'Y': 4},                                 False, {}),
    ("cmuxv",      {'g': 4, 'r': 20, 'G': 1, 'R': 1},                       False, {}),
    ("cmuxh",      {'g': 4, 'r': 12, 'G': 1, 'R': 1},                       False, {}),
    ("dll",        {'g': 1},                                                False, {}),
    ("hssi",       {'g': 1, 'i': 3},                                        False, {}),
    ("cbuf",       {'g': 1, 'i': 2},                                        False, {}),
    ("lvl",        {'g': 1, 'i': 4},                                        False, {}),
    ("pma3",       {'g': 1, 'i': 3, 'q': 4, 'k': 6, 'd': 2, 't': 1, 'b': 1}, False, {'t': 1, 'b': 0}),
    ("pma3-c",     {'i': 3},                                                False, {}),
    ("serpar",     {'g': 1},                                                False, {}),
    ("term",       {'g': 1},                                                False, {}),
    ("hip",        {'g': 1, 'i': 8, 'm': 6},                                False, {}),
    ("hmc",        {'g': 1, 'i': 128, 'a': 40, 'p': 6, 'f': 4, 'o': 8},      False, {}),
]

# RAM-space per mtype -- verified by reading dump_bpos() call sites
# (mux_to_source.py lines 304-332): opt -> oram, the 17 non-cram files below
# -> pram, lab/mlab/m10k/dsp/hps_clocks -> cram.
ORAM_FILES = {"opt"}
CRAM_FILES = {"lab", "mlab", "m10k", "dsp", "hps_clocks"}


def ram_space_for(mtype):
    if mtype in ORAM_FILES:
        return "oram"
    if mtype in CRAM_FILES:
        return "cram"
    return "pram"


# dump_target per (mtype, subtype-filter): mirrors dump_muxes() call sites
# (lines 407-455). Most files feed exactly one dump_target named after the
# file; cmuxv/cmuxh each split into two dump_targets by subtype filter.
# cmuxc keeps its one dump_target "cmuxcr" (named with a trailing 'r' in the
# source despite not being subtype-filtered -- verified: dump_muxes("cmuxcr",
# cmuxc, 1, counters) has no filter argument, all of cmuxc's R/Y/r subtypes
# land in cmuxcr).
SPLIT_DUMP_TARGETS = {
    "cmuxv": [("cmuxvr", lambda t: t in ("r", "R")), ("cmuxvg", lambda t: t in ("g", "G"))],
    "cmuxh": [("cmuxhr", lambda t: t in ("r", "R")), ("cmuxhg", lambda t: t in ("g", "G"))],
}
SINGLE_DUMP_TARGET = {
    "opt": "opt", "gpio": "gpio", "dqs16": "dqs16", "fpll": "fpll",
    "cmuxc": "cmuxcr", "dll": "dll", "hssi": "hssi", "cbuf": "cbuf",
    "lvl": "lvl", "pma3": "pma3", "pma3-c": "pma3c", "serpar": "serpar",
    "term": "term", "hip": "hip", "hmc": "hmc",
    "lab": "lab", "mlab": "mlab", "m10k": "m10k", "dsp": "dsp",
    "hps_clocks": "hps_clocks",
}


def _wait_for_ram(max_ram_pct, log, what):
    """Same gate as cyclonev_db_import_routes.py's _wait_for_ram -- 85% default
    (this host's QEMU-VM+IDE baseline sits at ~50-58%, so a lower default
    stalls forever), periodic 30s re-logging so a real stall is visible.
    This script's own peak usage is trivial (4,650 source lines total) --
    the gate is here for consistency with the established pattern, not
    because this script is expected to ever actually wait.
    """
    start = None
    last_log = 0.0
    while psutil.virtual_memory().percent >= max_ram_pct:
        now = time.time()
        if start is None:
            start = now
            log.info(f"  RAM at {psutil.virtual_memory().percent:.0f}% >= "
                      f"{max_ram_pct:.0f}% -- pausing before {what}")
            last_log = now
        elif now - last_log >= 30.0:
            log.info(f"  still waiting on RAM ({psutil.virtual_memory().percent:.0f}% >= "
                      f"{max_ram_pct:.0f}%) for {now - start:.0f}s -- {what}")
            last_log = now
        time.sleep(2)


def setup_logging():
    import logging
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    log = logging.getLogger("cyclonev_db_import_blockmux")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fh = logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_db_import_blockmux.log"))
    sh = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh.setFormatter(fmt)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


# ── load_mux_data(), transliterated from mux_to_source.py lines 10-84 ───────

def load_mux_data(mistral_root, mtype, tmap, is_2d, variantmap, log):
    w = (lambda v: [int(v.split('.')[0]), int(v.split('.')[1])]) if is_2d else (lambda v: int(v))
    muxes = []
    fname = os.path.join(mistral_root, "data", f"{mtype}-mux.txt")
    if not os.path.isfile(fname):
        db.die(f"missing {fname} -- is --mistral-root correct?")

    with open(fname, "r") as f:
        for raw in f:
            l = raw.rstrip("\n\r")
            ls = l.split()
            if len(ls) == 0:
                continue
            sub = l[0] == ' '
            if sub:
                if len(muxes) == 0:
                    db.die(f"{fname}: indented line before any mux: {l!r}")
                cur = muxes[-1]
                if ls[0] == '*':
                    bl = []
                    for b in range(cur['bcount']):
                        bl.append(w(ls[b + 1]))
                    cur['bits'].append(bl)
                else:
                    if len(ls) == 3 and ls[2] == '!':
                        cur['def'] = len(cur['val'])
                    if cur['stype'] == 'm':
                        cur['val'].append([int(ls[0], 16), ls[1]])
                    elif cur['stype'] == 'n':
                        cur['val'].append([int(ls[0], 16), int(ls[1])])
                    else:
                        db.die(f"{fname}: mux {cur['mux']} is not of stype m or n "
                               f"({cur['stype']}): {l!r}")
            else:
                subtype = ls[0]
                mux = ls[1]
                ss = ls[2].split(':')
                bcount = 1 if len(ss) < 2 else int(ss[1])
                stype = ss[0]
                d = None
                if len(stype) > 1:
                    d = stype[1:]
                    stype = stype[0]
                if d is not None and (stype == 'r' or stype == 'b'):
                    if d == '-':
                        d = 0
                    elif d == '+':
                        d = -1 if stype == 'r' else 1
                    elif stype == 'r':
                        d = int(d, 16)
                    else:
                        db.die(f"{fname}: incorrect default suffix {d!r} on mux {mux}: {l!r}")
                if stype not in ('b', 'm', 'r', 'n'):
                    db.die(f"{fname}: bad stype {stype!r} on mux {mux}: {l!r}")
                if subtype not in tmap:
                    db.die(f"{fname}: missing subtype {subtype!r} on mux {mux}: {l!r}")
                span = tmap[subtype]
                bits = []
                nm = {'subtype': subtype, 'mux': mux, 'stype': stype, 'bcount': bcount,
                      'span': span, 'bits': bits,
                      'variant': variantmap.get(subtype, -1)}
                if d is not None:
                    nm['def'] = d
                if stype in ('m', 'n'):
                    nm['val'] = []
                if len(ls) != 3:
                    if len(ls) != 3 + (span - 1) + span * bcount:
                        db.die(f"{fname}: incorrect field count on mux {mux}, "
                               f"span={span} bcount={bcount}: {l!r}")
                    for s in range(span):
                        bl = []
                        for b in range(bcount):
                            bl.append(w(ls[3 + b + (bcount + 1) * s]))
                        bits.append(bl)
                muxes.append(nm)

    for nm in muxes:
        if len(nm['bits']) != nm['span']:
            db.die(f"{fname}: span count mismatch on mux {nm['mux']}: "
                   f"declared {nm['span']}, got {len(nm['bits'])}")

    return muxes


def lab_expand(muxes, is_mlab):
    """Transliterated verbatim from mux_to_source.py lines 86-120."""
    for nm in muxes:
        if nm['subtype'] == 'i':
            bb = nm['bits'][0]
            sp = is_mlab and len(bb) == 64
            nb = []
            for i in range(4 if sp else 5):
                base = 85 - 8 * i
                bl = []
                for b in bb:
                    bl.append([b[0], base - b[1]])
                nb.append(bl)
            if sp:
                bl = []
                for b in bb[:32]:
                    bl.append([b[0], 53])
                for b in bb[32:]:
                    bl.append([b[0], 47])
                nb.append(bl)
            for i in range(4 if sp else 5):
                base = 8 * i
                bl = []
                for b in bb:
                    bl.append([b[0], base + b[1]])
                nb.append(bl)
            if sp:
                bl = []
                for b in bb[:32]:
                    bl.append([b[0], 32])
                for b in bb[32:]:
                    bl.append([b[0], 38])
                nb.append(bl)
            nm['span'] = 10
            nm['bits'] = nb


# ── row building ─────────────────────────────────────────────────────────

def rows_for(mtype, muxes, dump_target, ram_space, is_2d, filter_fn=None):
    rows = []
    for nm in muxes:
        if filter_fn is not None and not filter_fn(nm['subtype']):
            continue
        stype = nm['stype']
        values = None
        default_value = None
        default_value_idx = None
        if stype in ('m', 'n'):
            values = nm['val']
            default_value_idx = nm.get('def')
        else:
            default_value = nm.get('def')
        rows.append({
            "source_file": f"{mtype}-mux.txt",
            "dump_target": dump_target,
            "ram_space": ram_space,
            "subtype": nm['subtype'],
            "mux": nm['mux'],
            "stype": stype,
            "bcount": nm['bcount'],
            "span": nm['span'],
            "variant": nm['variant'],
            "is_2d": is_2d,
            "bits": nm['bits'],
            "values": values,
            "default_value": default_value,
            "default_value_idx": default_value_idx,
        })
    return rows


def build_all_rows(mistral_root, log):
    all_rows = []
    counts_by_target = {}
    for mtype, tmap, is_2d, variantmap in LOAD_CALLS:
        muxes = load_mux_data(mistral_root, mtype, tmap, is_2d, variantmap, log)
        if mtype in ("lab", "mlab"):
            lab_expand(muxes, mtype == "mlab")
        ram_space = ram_space_for(mtype)

        if mtype in SPLIT_DUMP_TARGETS:
            for dump_target, filter_fn in SPLIT_DUMP_TARGETS[mtype]:
                rows = rows_for(mtype, muxes, dump_target, ram_space, is_2d, filter_fn)
                all_rows.extend(rows)
                counts_by_target[dump_target] = len(rows)
        else:
            dump_target = SINGLE_DUMP_TARGET[mtype]
            rows = rows_for(mtype, muxes, dump_target, ram_space, is_2d)
            all_rows.extend(rows)
            counts_by_target[dump_target] = len(rows)

        log.info(f"  {mtype}-mux.txt: {len(muxes)} mux entries (ram_space={ram_space}, is_2d={is_2d})")

    return all_rows, counts_by_target


def insert_rows(conn, rows, log):
    cols = ["source_file", "dump_target", "ram_space", "subtype", "mux", "stype",
            "bcount", "span", "variant", "is_2d", "bits", "values",
            "default_value", "default_value_idx"]
    json_cols = {"bits", "values"}
    placeholders = ",".join("?" * len(cols))
    quoted_cols = ",".join(f'"{c}"' for c in cols)  # "values"/"mux" are reserved words in SQL
    sql = f"INSERT INTO cv_block_muxes ({quoted_cols}) VALUES ({placeholders})"
    values = [
        tuple(
            (json.dumps(r[c]) if c in json_cols else (int(r[c]) if c == "is_2d" else r[c]))
            for c in cols
        )
        for r in rows
    ]
    conn.executemany(sql, values)
    if db.BACKEND == "sqlite":
        conn.commit()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mistral-root", default=DEFAULT_MISTRAL_ROOT)
    ap.add_argument("--max-ram-pct", type=float, default=DEFAULT_MAX_RAM_PCT,
                     help=f"pause before the insert pass while psutil.virtual_memory().percent "
                          f"is at/above this (default: {DEFAULT_MAX_RAM_PCT})")
    args = ap.parse_args()

    log = setup_logging()
    schema.init()

    t0 = time.time()
    log.info(f"NoGIL: {not sys._is_gil_enabled()}  importing block-mux data from {args.mistral_root}")

    all_rows, counts_by_target = build_all_rows(args.mistral_root, log)

    conn = db.connect_threadsafe()
    conn.execute("DELETE FROM cv_block_muxes")
    if db.BACKEND == "sqlite":
        conn.commit()

    _wait_for_ram(args.max_ram_pct, log, "block-mux insert pass")
    insert_rows(conn, all_rows, log)
    conn.close()

    log.info(f"inserted {len(all_rows)} rows across {len(counts_by_target)} dump_target(s) "
              f"in {time.time()-t0:.1f}s")
    for target in sorted(counts_by_target):
        log.info(f"  {target}: {counts_by_target[target]} rows")


if __name__ == "__main__":
    main()
