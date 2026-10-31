#!/usr/bin/env python3.15t
"""#188: match the DJI image's lifted netlist against the harness-stripped template library
(reference/template_library.json, built by cycloneiv_clean_template_library_build.py).

For every clocked FF in the DJI design, compute its D-cone's leaf set (patterns.Design.support) --
unlike the isolated specimens used to BUILD the library, real-design leaves are pads, other FF outputs,
M9K outputs or MAC outputs, not just pads.  Match by exact leaf COUNT first (cone_tt needs a fixed leaf
count), then check the cone's truth table against every library template of that leaf count under SOME
permutation of leaf order (same-shape-regardless-of-which-input-landed-where).  Permutation search is
capped at 8 leaves (8! = 40320, still cheap); wider cones are reported separately as "too wide to
permutation-match cheaply", never silently skipped.  A cone containing a self-loop (cone_has_cycle,
found 2026-10-31 via the AF3 engine's 2 documented self-referencing LEs -- patterns.cone_tt has no cycle
guard and hangs forever on one) is likewise detected and reported separately, never silently skipped
and never hung on.

The per-FF cone_tt + permutation-match work is independent per FF (pure read of the shared, read-only
Design/netlist) -- run across threads (ThreadPoolExecutor, default min(32, cpu count): this project's
"threads everywhere, never multiprocessing" rule, free-threaded 3.15t, #124's memory-cgroup concerns
don't apply here since this is CPU/RAM-bound Python work in ONE process, not N separate Quartus
processes). perm_cache is a dict guarded by a lock around the check-then-insert; worst case under a race
is a cache entry computed twice (correctness-neutral, cheap to redo), never a wrong answer.

  python3.15t scripts/cycloneiv_clean_template_match.py [--nl PATH] [--max-leaves-exact N] [--workers N]
Default --nl: tmp/image_sim_dji_push/nl.pkl (the current DJI m2001 lift).  Log tmp/logs/cycloneiv_clean_template_match.log.
Writes tmp/logs/cycloneiv_clean_template_match_result.json.  Read-only on the netlist and the library.
"""
import argparse
import itertools
import json
import logging
import os
import pickle
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import patterns as PT
log = logging.getLogger("template_match")
LIB = Path(REPO) / "reference" / "template_library.json"
DEFAULT_NL = Path(REPO) / "tmp" / "image_sim_dji_push" / "nl.pkl"
MAX_LEAVES_EXACT = 8        # 8! = 40,320 permutations per cone, still sub-second; above this, permutation
                            # search cost grows factorially (9! = 362,880, 10! = 3.6M) -- report as skipped
                            # rather than silently eating minutes per cone on a 35,873-FF design.


def cone_has_cycle(D, sig):
    """patterns.cone_tt has NO cycle guard: it only memoizes fully-resolved values, so a LUT that reads
    its own output, directly or through a chain (a genuine, documented artifact of this image -- 2
    self-looped LEs in the AF3 engine, docs/altera/cycloneIV/cycloneiv-clean-af3-engine.md: "self pin
    tied 0") makes it loop forever. Depth-first with an on-path set (not merely an all-ever-seen set --
    a DAG can revisit a node via a second, non-cyclic path, which must NOT be flagged): a hit on a node
    still on the current path is a genuine cycle. Found empirically (2026-10-31): cone_tt hung for >10s
    on ff_6_90_5's 2-leaf D cone, which chains through lc_6_90_14, one of the two documented
    self-referencing LEs."""
    # Iterative DFS (not recursive): cones up to 651 leaves were observed in this design, deep enough
    # that a recursive walk risks Python's default 1000-frame recursion limit.  Each stack frame is
    # (node, iterator-over-its-remaining-children), built once when the node is pushed.
    def children_of(s):
        L = D.lut.get(s) if s.startswith("lc_") else None
        if L is None or L["mode"] == "cin":
            return iter(())
        return iter([p for p in L["pins"] if p not in PT.CONSTV])

    done, on_path = set(), {sig}
    stack = [(sig, children_of(sig))]
    while stack:
        s, children = stack[-1]
        nxt = next(children, None)
        if nxt is None:
            on_path.discard(s)
            done.add(s)
            stack.pop()
            continue
        if nxt in done:
            continue
        if nxt in on_path:
            return True
        on_path.add(nxt)
        stack.append((nxt, children_of(nxt)))
    return False


def load_library(lib_path=None):
    """template_library.json carries tt_hex, not the raw int tt (a 16-leaf cone's tt is a 1<<65536-valued
    int whose decimal repr exceeds CPython's int-to-str digit limit; json.dump on the raw int crashes --
    see cycloneiv_clean_template_library_build.py's dedup comment). Reconstruct tt here, once, on load."""
    lib = json.load(open(lib_path or LIB))
    by_leaves = {}
    for t in lib["templates"]:
        t["tt"] = int(t["tt_hex"], 16)
        by_leaves.setdefault(t["n_leaves"], []).append(t)
    return lib, by_leaves


def permutation_tts(tt, k):
    """All truth tables reachable from `tt` (over k leaves) by permuting leaf order -- the set a cone's
    own truth table must intersect for a match independent of which physical signal landed in which
    leaf slot."""
    out = set()
    for perm in itertools.permutations(range(k)):
        pt = 0
        for i in range(1 << k):
            bits = [(i >> j) & 1 for j in range(k)]
            src_i = 0
            for j, p in enumerate(perm):
                src_i |= bits[j] << p
            if (tt >> src_i) & 1:
                pt |= 1 << i
        out.add(pt)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", default=str(DEFAULT_NL))
    ap.add_argument("--library", default=None,
                     help="override reference/template_library.json (e.g. an AREA-built library, #188 disambiguation)")
    ap.add_argument("--max-leaves-exact", type=int, default=MAX_LEAVES_EXACT)
    ap.add_argument("--workers", type=int, default=min(32, os.cpu_count() or 4),
                     help="threads for the per-FF cone_tt+permutation scan (pure Python, CPU-bound, free-threaded 3.15t)")
    a = ap.parse_args()
    lib_path = Path(a.library) if a.library else LIB
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_template_match.log"))])
    if not lib_path.exists():
        log.error("template library not found at %s -- run cycloneiv_clean_template_library_build.py first", lib_path)
        return 2
    if not os.path.exists(a.nl):
        log.error("netlist pickle not found at %s", a.nl)
        return 2
    lib, by_leaves = load_library(lib_path)
    log.info("library: %d unique templates, leaf counts %s", len(lib["templates"]), sorted(by_leaves))

    import heavy_guard
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    t0 = time.time()
    with heavy_guard.lease(gb, "cyc4_clean_template_match", log):
        nl = pickle.load(open(a.nl, "rb"))
        log.info("netlist loaded %.1fs: %d LUTs, %d FFs", time.time() - t0, len(nl.luts), len(nl.ffs))
        D = PT.Design(nl)

        # cache permutation-tt-sets per (template n_leaves, tt) so repeated cones of the same shape in
        # the DJI design don't recompute 8!-permutation closures over and over.  Guarded by perm_lock:
        # the check-then-insert can race across threads, worst case is one entry computed twice (cheap,
        # correctness-neutral), never a wrong lookup -- never guard the READ, only the fill-on-miss.
        perm_cache, perm_lock = {}, threading.Lock()

        def pset_for(cand_tt, k):
            ckey = (k, cand_tt)
            pset = perm_cache.get(ckey)
            if pset is not None:
                return pset
            computed = permutation_tts(cand_tt, k)
            with perm_lock:
                pset = perm_cache.setdefault(ckey, computed)
            return pset

        results_lock = threading.Lock()
        matched, unmatched_leaf_counts, skipped_too_wide = [], {}, {"count": 0, "leaf_counts": {}}
        skipped_cyclic = []
        n_checked = [0]
        t_scan = time.time()

        def check_one(F):
            if F["d"] is None:
                return
            leaves = sorted(D.support(F["d"]))
            k = len(leaves)
            with results_lock:
                n_checked[0] += 1
                nc = n_checked[0]
            if k == 0:
                return          # constant D (dead/tied FF) -- not a pattern
            if k > a.max_leaves_exact:
                with results_lock:
                    skipped_too_wide["count"] += 1
                    skipped_too_wide["leaf_counts"][k] = skipped_too_wide["leaf_counts"].get(k, 0) + 1
                return
            candidates = by_leaves.get(k)
            if not candidates:
                with results_lock:
                    unmatched_leaf_counts[k] = unmatched_leaf_counts.get(k, 0) + 1
                return
            # patterns.cone_tt has no cycle guard and hangs forever on a self-referencing LUT (a real,
            # documented artifact of this image -- 2 self-looped LEs in the AF3 engine). Checked BEFORE
            # calling cone_tt, not caught after the fact: there is no "after" to catch from an infinite
            # loop. See cone_has_cycle's docstring for how this was found.
            if cone_has_cycle(D, F["d"]):
                with results_lock:
                    skipped_cyclic.append(F["name"])
                return
            kinds = [D.kind(s) for s in leaves]
            tt = PT.cone_tt(D, F["d"], leaves)
            hit = None
            for cand in candidates:
                if tt in pset_for(cand["tt"], k):
                    hit = cand
                    break
            with results_lock:
                if hit is not None:
                    matched.append(dict(ff=F["name"], n_leaves=k, leaf_kinds=kinds,
                                         template_tt_hex=hit["tt_hex"], template_sources=[s["source"] for s in hit["sources"][:3]]))
                else:
                    unmatched_leaf_counts[k] = unmatched_leaf_counts.get(k, 0) + 1
                if nc % 2000 == 0:
                    log.info("scanned %d FFs, %.0fs elapsed, %d matched so far", nc, time.time() - t_scan, len(matched))

        clocked = [F for F in D.clocked]
        log.info("scanning %d clocked FFs across %d threads", len(clocked), a.workers)
        with ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(check_one, clocked))

    by_template = {}
    for m in matched:
        key = m["template_tt_hex"]
        by_template.setdefault(key, {"template_tt_hex": key, "example_sources": m["template_sources"], "count": 0})
        by_template[key]["count"] += 1

    result = dict(
        n_clocked_ffs=len(D.clocked),
        n_checked=n_checked[0],
        n_matched=len(matched),
        n_unmatched=sum(unmatched_leaf_counts.values()),
        unmatched_by_leaf_count=unmatched_leaf_counts,
        n_skipped_too_wide=skipped_too_wide["count"],
        skipped_too_wide_by_leaf_count=skipped_too_wide["leaf_counts"],
        n_skipped_cyclic=len(skipped_cyclic),
        skipped_cyclic_ffs=skipped_cyclic,
        matched_by_template=sorted(by_template.values(), key=lambda x: -x["count"]),
        elapsed_s=round(time.time() - t0, 1),
    )
    out = Path(REPO) / "tmp" / "logs" / "cycloneiv_clean_template_match_result.json"
    json.dump(dict(result, matched_detail=matched[:200]), open(out, "w"), indent=1)
    log.info("RESULT checked=%d matched=%d unmatched=%d skipped_too_wide=%d skipped_cyclic=%d elapsed=%.0fs -> %s",
              n_checked[0], len(matched), result["n_unmatched"], skipped_too_wide["count"], len(skipped_cyclic), result["elapsed_s"], out)
    print(json.dumps({k: v for k, v in result.items() if k != "matched_by_template" or len(v) < 20}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
