#!/usr/bin/env python3
"""Pluribus — extended reachability analyses (Stage 2b).

Runs after reach.py has populated the reachability table.  Four passes:

  1. Reverse reachability  — reachability_rev[dst][src] = hops
     "Who can reach net X?" answered from a pre-inverted index.
     Pure SQL INSERT SELECT from reachability — instant.

  2. FF cones             — ff_cones[ff_cell][cone_type][net] = hops
     Input cone:  all nets that transitively feed FF.D or FF.CE
     Output cone: all nets reachable from FF.Q
     Derived from reachability + reachability_rev in Python, parallel per FF.

  3. Critical paths       — critical_paths[src_ff][dst_ff] = hops
     Longest combinatorial chain between any two FF boundaries.
     Built from the reachability table: for each FF pair (A, B)
     where Q_A can reach D_B, record the hop count.  Max over all src FFs per
     dst FF gives the deepest input cone depth.

  4. Dominators           — dominators[ff_cell][net] = n_paths
     Nets that appear on EVERY pad→FF path.  Computed by counting how many
     distinct pad inputs reach FF X through each intermediate net, then keeping
     only nets whose count equals the total number of pads that reach FF X.

Usage
-----
  python3 fpga/pluribus/reach2.py [--bitstream V07] [--workers 24]
"""

import argparse
import math
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import BACKEND, die, engine
from sqlalchemy import select, insert, delete, func, text
import schema


def _insert_or_ignore(table):
    """Return an INSERT that silently skips duplicates on both backends."""
    if BACKEND == "sqlite":
        return insert(table).prefix_with("OR IGNORE")
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    return pg_insert(table).on_conflict_do_nothing()


# ── 1. Reverse reachability ───────────────────────────────────────────────────

def pass_reverse(bs_id, conn):
    """Invert reachability into reachability_rev via SQL."""
    conn.execute(
        delete(schema.reachability_rev).where(
            schema.reachability_rev.c.bitstream == bs_id
        )
    )
    r = schema.reachability
    rr = schema.reachability_rev
    sel = (
        select(r.c.bitstream, r.c.dst, r.c.src, r.c.min_hops)
        .where(r.c.bitstream == bs_id)
    )
    result = conn.execute(
        _insert_or_ignore(rr).from_select(
            ["bitstream", "dst", "src", "min_hops"], sel
        )
    )
    n = result.rowcount
    return n


# ── 2. FF cones ───────────────────────────────────────────────────────────────

def pass_ff_cones(bs_id, n_workers):
    """Build input and output cones for every FF.

    Input cone of FF X:  all nets reachable from any source that reach D/CE,
                         stopping at other FF Q outputs (register boundary).
    Output cone of FF X: all nets reachable from Q, stopping at FF D/CE inputs.

    Both cones are derived from the full reachability table by filtering:
    - input cone: reachability_rev where dst IN {D_net, CE_net}, then truncate
      at any net that is another FF's Q (a register output is a cone boundary)
    - output cone: reachability where src = Q_net, truncate at FF D/CE inputs
    """
    with engine().connect() as conn:
        rows_ffs = conn.execute(
            select(
                schema.ffs.c.cell,
                schema.ffs.c.d,
                schema.ffs.c.ce,
                schema.ffs.c.q,
            ).where(schema.ffs.c.bitstream == bs_id)
        ).fetchall()

        # Build set of all FF Q nets (register outputs = cone boundaries for input cones)
        ff_q_nets = set()
        for _cell, _d, _ce, q in rows_ffs:
            if q and not q.startswith("1'b"):
                ff_q_nets.add(q)

        # Build set of all FF D/CE nets (register inputs = cone boundaries for output cones)
        ff_d_nets = set()
        for _cell, d, ce, _q in rows_ffs:
            if d and not d.startswith("1'b"):   ff_d_nets.add(d)
            if ce and not ce.startswith("1'b"): ff_d_nets.add(ce)

        # Load full reachability_rev (used for input cones)
        rev_rows = conn.execute(
            select(
                schema.reachability_rev.c.dst,
                schema.reachability_rev.c.src,
                schema.reachability_rev.c.min_hops,
            ).where(schema.reachability_rev.c.bitstream == bs_id)
        ).fetchall()
        rev_index = defaultdict(list)
        for dst, src, h in rev_rows:
            # Exclude paths that cross a FF Q boundary — src that is another FF's Q
            # is a register output and should not be included in the combinational cone
            if src not in ff_q_nets:
                rev_index[dst].append((src, h))

        # Load full reachability (used for output cones)
        fwd_rows = conn.execute(
            select(
                schema.reachability.c.src,
                schema.reachability.c.dst,
                schema.reachability.c.min_hops,
            ).where(schema.reachability.c.bitstream == bs_id)
        ).fetchall()
        fwd_index = defaultdict(list)
        for src, dst, h in fwd_rows:
            # Exclude paths that cross a FF D/CE boundary
            if dst not in ff_d_nets:
                fwd_index[src].append((dst, h))

        conn.execute(
            delete(schema.ff_cones).where(schema.ff_cones.c.bitstream == bs_id)
        )
        conn.commit()

    ffs = rows_ffs
    total      = len(ffs)
    done       = [0]
    lock       = threading.Lock()
    # Post-SD-fix cone sizes make each worker's final insert large; 24
    # concurrent inserts exhaust the SQLAlchemy pool (5+10, 30s timeout)
    # and SQLite serialises writers anyway — one insert at a time.
    insert_lock = threading.Lock()
    error_msgs = []

    def worker_chunk(chunk):
        try:
            rows = []
            for cell, d, ce, q in chunk:
                # Input cone: union of rev[d] and rev[ce]
                seen = {}
                for driver_net in (d, ce):
                    if not driver_net or driver_net.startswith("1'b"):
                        continue
                    for src, h in rev_index.get(driver_net, []):
                        if src not in seen or h < seen[src]:
                            seen[src] = h
                for net, h in seen.items():
                    rows.append({
                        "bitstream": bs_id,
                        "ff_cell":   cell,
                        "cone_type": "input",
                        "net":       net,
                        "min_hops":  h,
                    })

                # Output cone: fwd[q]
                if q and not q.startswith("1'b"):
                    for dst, h in fwd_index.get(q, []):
                        rows.append({
                            "bitstream": bs_id,
                            "ff_cell":   cell,
                            "cone_type": "output",
                            "net":       dst,
                            "min_hops":  h,
                        })

            if rows:
                with insert_lock:
                    with engine().begin() as wconn:
                        wconn.execute(_insert_or_ignore(schema.ff_cones), rows)

            with lock:
                done[0] += len(chunk)
                n = done[0]
                if n % 100 == 0 or n == total:
                    print(f"  ff_cones {n}/{total}", end="\r", flush=True)
        except Exception as exc:
            with lock:
                error_msgs.append(str(exc))

    # Partition with ceil so no FFs are dropped at the tail
    chunk_size = max(1, math.ceil(total / n_workers))
    chunks  = [ffs[i:i+chunk_size] for i in range(0, total, chunk_size)]
    threads = [threading.Thread(target=worker_chunk, args=(c,)) for c in chunks]
    for t in threads: t.start()
    for t in threads: t.join()

    if error_msgs:
        die(f"ff_cones worker(s) failed: {error_msgs[0]}")

    # Count result
    with engine().connect() as conn:
        n = conn.execute(
            select(func.count()).select_from(schema.ff_cones).where(
                schema.ff_cones.c.bitstream == bs_id
            )
        ).scalar()
    return n


# ── 3. Critical paths ─────────────────────────────────────────────────────────

def pass_critical_paths(bs_id):
    """Find the longest combinational chain between each FF pair.

    If Q_A can reach D_B in h hops (without passing through another FF D/CE
    as an intermediate stop), record (A, B, h).  Keeps only the maximum h per
    (src_ff, dst_ff) pair.  The full transitive reachability table is used;
    the combinational boundary condition is enforced by requiring src=FF.q and
    dst=FF.d/ce — any path in the table that starts at a register output and
    ends at a register input is a combinational chain.
    """
    cp = schema.critical_paths

    # A (src_ff, dst_ff) pair can match several reachability rows (fb.d and
    # fb.ce are separate dst nets, each possibly at several hop counts), so
    # dedupe with a window function keeping the max-hops row.  Rows for the
    # label are deleted first, so a plain INSERT needs no upsert — the old
    # ON CONFLICT form broke on PostgreSQL ("cannot affect row a second
    # time") and SQLite's INSERT OR REPLACE kept an arbitrary row, not max.
    json_fn = "json_array" if BACKEND == "sqlite" else "json_build_array"
    stmt = text(f"""
        INSERT INTO critical_paths (bitstream, src_ff, dst_ff, hops, path_nets)
        SELECT bitstream, src_ff, dst_ff, min_hops, path_nets FROM (
            SELECT
                r.bitstream,
                fa.cell  AS src_ff,
                fb.cell  AS dst_ff,
                r.min_hops,
                {json_fn}(fa.q, r.dst) AS path_nets,
                ROW_NUMBER() OVER (
                    PARTITION BY r.bitstream, fa.cell, fb.cell
                    ORDER BY r.min_hops DESC
                ) AS rn
            FROM reachability r
            JOIN ffs fa ON fa.bitstream=r.bitstream AND fa.q=r.src
            JOIN ffs fb ON fb.bitstream=r.bitstream
                       AND (fb.d=r.dst OR fb.ce=r.dst)
            WHERE r.bitstream=:bs_id
        ) ranked
        WHERE rn = 1
    """)

    with engine().begin() as conn:
        conn.execute(delete(cp).where(cp.c.bitstream == bs_id))
        result = conn.execute(stmt, {"bs_id": bs_id})
        n = result.rowcount

    # Report the deepest chains
    with engine().connect() as conn:
        top = conn.execute(
            select(cp.c.src_ff, cp.c.dst_ff, cp.c.hops)
            .where(cp.c.bitstream == bs_id)
            .order_by(cp.c.hops.desc())
            .limit(5)
        ).fetchall()

    return n, top


# ── 4. Dominators ────────────────────────────────────────────────────────────

def pass_dominators(bs_id):
    """Find nets that lie on every pad-to-FF path.

    N dominates FF F if: count(pads that reach N AND N reaches F.D/CE)
                         == count(pads that reach F.D/CE)

    Uses full reachability table — no stop_at filter.  Pad boundary is enforced
    by joining against pad_map (src must be a pad net_in).
    """
    dom = schema.dominators

    # This is a multi-CTE analytics query that cannot be cleanly expressed in
    # SQLAlchemy Core without becoming harder to read than the raw SQL, so we
    # use text() here as permitted by the rewrite rules.
    if BACKEND == "sqlite":
        # Rewritten to avoid triple self-join on reachability (252k rows).
        # Uses ff_cones (input cone per FF, 26k rows) and pad_map (18 rows)
        # so SQLite can do covering-index lookups instead of full scans.
        # pad_counts comes from pad_ff_influence (already aggregated by reach.py).
        stmt = text("""
            WITH
            pad_counts AS (
                SELECT ff_cell, count(*) AS n_pads
                FROM pad_ff_influence
                WHERE bitstream=:bs_id
                GROUP BY ff_cell
            ),
            pad_via_counts AS (
                SELECT fc.ff_cell, fc.net AS via_net,
                       count(DISTINCT pm.label) AS n_paths
                FROM ff_cones fc
                JOIN pad_map pm ON pm.bitstream=:bs_id AND pm.net_in IS NOT NULL
                JOIN reachability r ON r.bitstream=:bs_id
                                   AND r.src=pm.net_in
                                   AND r.dst=fc.net
                WHERE fc.bitstream=:bs_id AND fc.cone_type='input'
                GROUP BY fc.ff_cell, fc.net
            )
            INSERT OR IGNORE INTO dominators (bitstream, ff_cell, net, n_paths)
            SELECT :bs_id, pvc.ff_cell, pvc.via_net, pvc.n_paths
            FROM pad_via_counts pvc
            JOIN pad_counts pc ON pc.ff_cell=pvc.ff_cell
            WHERE pvc.n_paths = pc.n_pads
              AND pc.n_pads > 0
        """)
    else:
        stmt = text("""
            WITH
            pad_to_ff AS (
                SELECT
                    f.cell      AS ff_cell,
                    pm.label    AS pad_label,
                    r.src       AS pad_net
                FROM ffs f
                JOIN reachability r  ON r.bitstream=f.bitstream
                                    AND (r.dst=f.d OR r.dst=f.ce)
                JOIN pad_map pm      ON pm.bitstream=f.bitstream
                                    AND pm.net_in=r.src
                WHERE f.bitstream=:bs_id
                  AND f.d IS NOT NULL
            ),
            pad_counts AS (
                SELECT ff_cell, count(DISTINCT pad_label) AS n_pads
                FROM pad_to_ff GROUP BY ff_cell
            ),
            net_on_path AS (
                SELECT
                    ptf.ff_cell,
                    r_fwd.dst   AS via_net,
                    ptf.pad_label
                FROM pad_to_ff ptf
                JOIN reachability r_fwd ON r_fwd.bitstream=:bs_id
                                       AND r_fwd.src=ptf.pad_net
                JOIN ffs f2 ON f2.cell=ptf.ff_cell AND f2.bitstream=:bs_id
                JOIN reachability r_back ON r_back.bitstream=:bs_id
                                        AND r_back.src=r_fwd.dst
                                        AND (r_back.dst=f2.d OR r_back.dst=f2.ce)
            ),
            via_counts AS (
                SELECT ff_cell, via_net, count(DISTINCT pad_label) AS n_paths
                FROM net_on_path GROUP BY ff_cell, via_net
            )
            INSERT INTO dominators (bitstream, ff_cell, net, n_paths)
            SELECT :bs_id, vc.ff_cell, vc.via_net, vc.n_paths
            FROM via_counts vc
            JOIN pad_counts pc ON pc.ff_cell=vc.ff_cell
            WHERE vc.n_paths = pc.n_pads
              AND pc.n_pads > 0
            ON CONFLICT DO NOTHING
        """)

    with engine().begin() as conn:
        conn.execute(delete(dom).where(dom.c.bitstream == bs_id))
        result = conn.execute(stmt, {"bs_id": bs_id})
        # rowcount is -1 for INSERT...SELECT with CTEs in SQLite; do a real count
        with engine().connect() as _c:
            n = _c.execute(
                select(func.count()).select_from(dom).where(dom.c.bitstream == bs_id)
            ).scalar()

    # Top dominators by n_paths
    with engine().connect() as conn:
        top = conn.execute(
            select(
                dom.c.net,
                func.count(func.distinct(dom.c.ff_cell)).label("ff_count"),
                func.max(dom.c.n_paths).label("max_paths"),
            )
            .where(dom.c.bitstream == bs_id)
            .group_by(dom.c.net)
            .order_by(func.count(func.distinct(dom.c.ff_cell)).desc())
            .limit(5)
        ).fetchall()

    return n, top


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bitstream", default="V07")
    ap.add_argument("--workers",   type=int, default=24)
    args = ap.parse_args()

    with engine().connect() as conn:
        row = conn.execute(
            select(schema.bitstreams.c.id).where(
                schema.bitstreams.c.label == args.bitstream
            )
        ).fetchone()
    if not row:
        die(f"Bitstream {args.bitstream!r} not in DB — run load.py + reach.py first")
    bs_id = row[0]

    t0 = time.time()
    timings = []

    # ── 1. Reverse reachability ──
    print("Pass 1: reverse reachability…", flush=True)
    t = time.time()
    with engine().begin() as conn:
        n = pass_reverse(bs_id, conn)
    elapsed = time.time() - t
    timings.append(("reverse",   elapsed))
    print(f"  {n} rows  ({elapsed:.2f}s)")

    # ── 2. FF cones ──
    print("Pass 2: FF input/output cones…", flush=True)
    t = time.time()
    n = pass_ff_cones(bs_id, args.workers)
    elapsed = time.time() - t
    timings.append(("ff_cones",  elapsed))
    print(f"\n  {n} cone entries  ({elapsed:.2f}s)")

    # ── 3. Critical paths ──
    print("Pass 3: critical combinational paths…", flush=True)
    t = time.time()
    n, top_paths = pass_critical_paths(bs_id)
    elapsed = time.time() - t
    timings.append(("crit_paths", elapsed))
    print(f"  {n} FF→FF pairs  ({elapsed:.2f}s)")
    if top_paths:
        print("  Deepest chains:")
        for src, dst, h in top_paths:
            print(f"    {src} → {dst}  ({h} hops)")

    # ── 4. Dominators ──
    print("Pass 4: dominators…", flush=True)
    t = time.time()
    n, top_doms = pass_dominators(bs_id)
    elapsed = time.time() - t
    timings.append(("dominators", elapsed))
    print(f"  {n} dominator entries  ({elapsed:.2f}s)")
    if top_doms:
        print("  Top nets (dominate most FFs):")
        for net, ff_count, max_paths in top_doms:
            print(f"    {net}  dominates {ff_count} FFs  (via {max_paths} pads)")

    total = time.time() - t0
    print(f"\n══ reach2 complete  ({total:.2f}s total) ══")
    print("  Stage timings:")
    for name, elapsed in timings:
        bar = "█" * int(elapsed / total * 30)
        print(f"  {name:<12}  {elapsed:5.2f}s  {bar}")


if __name__ == "__main__":
    main()
