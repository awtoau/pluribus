#!/usr/bin/env python3
"""Rebuild-regression diff (#60): compare a fresh from-scratch DB against a
reference DB, per-table, to catch data loss or regressions.

Rebuild the pipeline into a NEW db (never overwrite the working one), then:

    python3 scripts/rebuild_regression.py --fresh tmp/rebuild_check.db \
        --ref tmp/reference.db --label <LABEL>

Reports, for every table, the row count for the given bitstream label in each
DB and the delta.  Exits non-zero (listing the offending tables) if the fresh
rebuild has FEWER rows than the reference — i.e. the pipeline dropped data.
"""
import argparse
import sqlite3
import sys


def _table_cols(con):
    tabs = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    return {t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")] for t in tabs}


def _bs_id(con, label):
    try:
        r = con.execute("SELECT id FROM bitstreams WHERE label=?", (label,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return r[0] if r else None


def counts(con, label):
    """Per-table row count; scoped to `label` for tables with a bitstream column,
    total otherwise."""
    cols = _table_cols(con)
    bid = _bs_id(con, label)
    out = {}
    for t, tc in cols.items():
        if t == "bitstreams":
            continue
        try:
            if "bitstream" in tc and bid is not None:
                n = con.execute(f"SELECT count(*) FROM {t} WHERE bitstream=?",
                                (bid,)).fetchone()[0]
            else:
                n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            n = None
        out[t] = n
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fresh", required=True, help="freshly rebuilt DB")
    ap.add_argument("--ref", required=True, help="reference DB to compare against")
    ap.add_argument("--label", required=True, help="bitstream label to compare")
    ap.add_argument("--tol", type=float, default=0.0,
                    help="allowed fractional row drop before flagging (default 0)")
    args = ap.parse_args()

    f = sqlite3.connect(args.fresh)
    r = sqlite3.connect(args.ref)
    cf, cr = counts(f, args.label), counts(r, args.label)

    print(f"rebuild-regression: {args.label}   fresh={args.fresh}  ref={args.ref}")
    print(f"  {'table':<30}{'fresh':>9}{'ref':>9}{'delta':>9}")
    print("  " + "-" * 57)
    loss = []
    for t in sorted(set(cf) | set(cr)):
        a, b = cf.get(t), cr.get(t)
        d = (a - b) if (a is not None and b is not None) else None
        flag = ""
        if a is not None and b is not None and b > 0 and a < b * (1 - args.tol):
            flag = "  <-- DATA LOSS"
            loss.append((t, b, a))
        print(f"  {t:<30}{str(a):>9}{str(b):>9}{str(d):>9}{flag}")

    print()
    if loss:
        print(f"REGRESSION — {len(loss)} table(s) lost rows vs reference:")
        for t, b, a in loss:
            print(f"    {t}: {b} -> {a}")
        sys.exit(1)
    print("OK — no data loss (fresh >= ref for every table).")


if __name__ == "__main__":
    main()
