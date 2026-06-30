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
from db import BACKEND, connect, die, execute_values


# ── 1. Reverse reachability ───────────────────────────────────────────────────

def pass_reverse(bs_id, conn):
    """Invert reachability into reachability_rev via SQL."""
    cur = conn.cursor()
    cur.execute("DELETE FROM reachability_rev WHERE bitstream=%s", (bs_id,))
    cur.execute("""
        INSERT INTO reachability_rev (bitstream, dst, src, min_hops)
        SELECT bitstream, dst, src, min_hops
        FROM reachability
        WHERE bitstream=%s
        ON CONFLICT DO NOTHING
    """, (bs_id,))
    n = cur.rowcount
    conn.commit()
    cur.close()
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
    conn = connect()
    cur  = conn.cursor()

    cur.execute("SELECT cell, d, ce, q FROM ffs WHERE bitstream=%s", (bs_id,))
    ffs = cur.fetchall()

    # Build set of all FF Q nets (register outputs = cone boundaries for input cones)
    ff_q_nets = set()
    for _cell, _d, _ce, q in ffs:
        if q and not q.startswith("1'b"):
            ff_q_nets.add(q)

    # Build set of all FF D/CE nets (register inputs = cone boundaries for output cones)
    ff_d_nets = set()
    for _cell, d, ce, _q in ffs:
        if d and not d.startswith("1'b"):   ff_d_nets.add(d)
        if ce and not ce.startswith("1'b"): ff_d_nets.add(ce)

    # Load full reachability_rev (used for input cones)
    cur.execute("""
        SELECT dst, src, min_hops FROM reachability_rev
        WHERE bitstream=%s
    """, (bs_id,))
    rev_index = defaultdict(list)
    for dst, src, h in cur.fetchall():
        # Exclude paths that cross a FF Q boundary — src that is another FF's Q
        # is a register output and should not be included in the combinational cone
        if src not in ff_q_nets:
            rev_index[dst].append((src, h))

    # Load full reachability (used for output cones)
    cur.execute("""
        SELECT src, dst, min_hops FROM reachability
        WHERE bitstream=%s
    """, (bs_id,))
    fwd_index = defaultdict(list)
    for src, dst, h in cur.fetchall():
        # Exclude paths that cross a FF D/CE boundary
        if dst not in ff_d_nets:
            fwd_index[src].append((dst, h))

    cur.execute("DELETE FROM ff_cones WHERE bitstream=%s", (bs_id,))
    conn.commit()
    cur.close()
    conn.close()

    total      = len(ffs)
    done       = [0]
    lock       = threading.Lock()
    error_msgs = []

    def worker_chunk(chunk):
        try:
            wconn = connect()
            wcur  = wconn.cursor()
            rows  = []
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
                    rows.append((bs_id, cell, 'input', net, h))

                # Output cone: fwd[q]
                if q and not q.startswith("1'b"):
                    for dst, h in fwd_index.get(q, []):
                        rows.append((bs_id, cell, 'output', dst, h))

            if rows:
                execute_values(wcur, """
                    INSERT INTO ff_cones (bitstream, ff_cell, cone_type, net, min_hops)
                    VALUES %s ON CONFLICT DO NOTHING
                """, rows)
                wconn.commit()
            wcur.close()
            wconn.close()

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
    conn2 = connect()
    cur2  = conn2.cursor()
    cur2.execute("SELECT count(*) FROM ff_cones WHERE bitstream=%s", (bs_id,))
    n = cur2.fetchone()[0]
    cur2.close()
    conn2.close()
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
    conn = connect()
    cur  = conn.cursor()
    cur.execute("DELETE FROM critical_paths WHERE bitstream=%s", (bs_id,))

    array_expr = "ARRAY[fa.q, r.dst]" if BACKEND == "postgres" else "json_array(fa.q, r.dst)"
    cur.execute(f"""
        INSERT INTO critical_paths (bitstream, src_ff, dst_ff, hops, path_nets)
        SELECT
            r.bitstream,
            fa.cell  AS src_ff,
            fb.cell  AS dst_ff,
            r.min_hops,
            {array_expr}
        FROM reachability r
        JOIN ffs fa ON fa.bitstream=r.bitstream AND fa.q=r.src
        JOIN ffs fb ON fb.bitstream=r.bitstream AND (fb.d=r.dst OR fb.ce=r.dst)
        WHERE r.bitstream=%s
        ON CONFLICT (bitstream, src_ff, dst_ff)
            DO UPDATE SET hops=EXCLUDED.hops, path_nets=EXCLUDED.path_nets
            WHERE critical_paths.hops < EXCLUDED.hops
    """, (bs_id,))
    n = cur.rowcount
    conn.commit()

    # Report the deepest chains
    cur.execute("""
        SELECT src_ff, dst_ff, hops FROM critical_paths
        WHERE bitstream=%s ORDER BY hops DESC LIMIT 5
    """, (bs_id,))
    top = cur.fetchall()
    cur.close()
    conn.close()
    return n, top


# ── 4. Dominators ────────────────────────────────────────────────────────────

def pass_dominators(bs_id):
    """Find nets that lie on every pad-to-FF path.

    N dominates FF F if: count(pads that reach N AND N reaches F.D/CE)
                         == count(pads that reach F.D/CE)

    Uses full reachability table — no stop_at filter.  Pad boundary is enforced
    by joining against pad_map (src must be a pad net_in).
    """
    conn = connect()
    cur  = conn.cursor()
    cur.execute("DELETE FROM dominators WHERE bitstream=%s", (bs_id,))

    cur.execute("""
        WITH
        -- pads that reach each FF D/CE net (pad boundary: src must be pad net_in)
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
            WHERE f.bitstream=%s
              AND f.d IS NOT NULL
        ),
        pad_counts AS (
            SELECT ff_cell, count(DISTINCT pad_label) AS n_pads
            FROM pad_to_ff GROUP BY ff_cell
        ),
        -- intermediate nets reachable from pad that also reach FF.D/CE
        net_on_path AS (
            SELECT
                ptf.ff_cell,
                r_fwd.dst   AS via_net,
                ptf.pad_label
            FROM pad_to_ff ptf
            JOIN reachability r_fwd ON r_fwd.bitstream=%s
                                   AND r_fwd.src=ptf.pad_net
            JOIN ffs f2 ON f2.cell=ptf.ff_cell AND f2.bitstream=%s
            JOIN reachability r_back ON r_back.bitstream=%s
                                    AND r_back.src=r_fwd.dst
                                    AND (r_back.dst=f2.d OR r_back.dst=f2.ce)
        ),
        via_counts AS (
            SELECT ff_cell, via_net, count(DISTINCT pad_label) AS n_paths
            FROM net_on_path GROUP BY ff_cell, via_net
        )
        INSERT INTO dominators (bitstream, ff_cell, net, n_paths)
        SELECT %s, vc.ff_cell, vc.via_net, vc.n_paths
        FROM via_counts vc
        JOIN pad_counts pc ON pc.ff_cell=vc.ff_cell
        WHERE vc.n_paths = pc.n_pads
          AND pc.n_pads > 0
        ON CONFLICT DO NOTHING
    """, (bs_id, bs_id, bs_id, bs_id, bs_id))
    n = cur.rowcount
    conn.commit()

    # Top dominators by n_paths
    cur.execute("""
        SELECT net, count(distinct ff_cell) AS ff_count, max(n_paths) AS max_paths
        FROM dominators WHERE bitstream=%s
        GROUP BY net ORDER BY ff_count DESC LIMIT 5
    """, (bs_id,))
    top = cur.fetchall()
    cur.close()
    conn.close()
    return n, top


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bitstream", default="V07")
    ap.add_argument("--workers",   type=int, default=24)
    args = ap.parse_args()

    conn = connect()
    cur  = conn.cursor()
    cur.execute("SELECT id FROM bitstreams WHERE label=%s", (args.bitstream,))
    row = cur.fetchone()
    if not row:
        die(f"Bitstream {args.bitstream!r} not in DB — run load.py + reach.py first")
    bs_id = row[0]
    cur.close()
    conn.close()

    t0 = time.time()
    timings = []

    # ── 1. Reverse reachability ──
    print("Pass 1: reverse reachability…", flush=True)
    t = time.time()
    conn1 = connect()
    n = pass_reverse(bs_id, conn1)
    conn1.close()
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
