#!/usr/bin/env python3.15t
"""Combinational loops of a clean-emit netlist: real loops through LUTs vs tracer artifacts (#165).

  python3.15t scripts/cycloneiv_clean_loops.py --image IMAGE | <bitstream.rbf> [--json out.json]
Graph: node = LUT sum output (lc_) or carry output (co_); edge A -> B when B reads A on a pin.  FFs and pads end a path.
  all edges        every emitted pin connection
  dependent edges  only pins the reading LUT's INIT depends on (sum: pins a, b, c|cin, d; carry out: a, b, c|cin, INIT restricted to d = 0)
A loop that exists only in `all edges` is a connection the function ignores (a don't-care selection), not a logic loop.
Log tmp/logs/cycloneiv_clean_loops.log.
"""
import argparse
import collections
import json
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("cycloneiv_clean_loops")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_loops.log")
PLANE = os.path.join(REPO, "tmp", "cycloneiv_clean", "loops_image_plane.rbf")


def depends(init, pin, d_zero=False):
    """INIT (16 bit, index = {d, c, b, a}) depends on index bit `pin`; d_zero restricts to indices with d = 0."""
    for i in range(16):
        if d_zero and i & 8:
            continue
        if ((init >> i) & 1) != ((init >> (i ^ (1 << pin))) & 1):
            return True
    return False


def graph(nl):
    """-> (nodes, all_edges, dep_edges): edge (src node, dst node)."""
    by = {L["name"]: L for L in nl.luts}
    all_e, dep_e = [], []
    for L in nl.luts:
        for out, d0 in (("lc", False), ("co", True)):
            if out == "co" and L["mode"] != "cin":
                continue
            dst = (out, L["name"])
            for gi, p in enumerate(L["pins"]):
                if not p or p == "1'b1" or p[:3] not in ("lc_", "co_"):
                    continue
                src = ("co", "lc_" + p[3:]) if p.startswith("co_") else ("lc", p)
                if src[1] not in by:
                    continue
                all_e.append((src, dst))
                if out == "co" and gi == 3:
                    continue
                if depends(L["init"], gi, d0):
                    dep_e.append((src, dst))
    return all_e, dep_e


def sccs(edges):
    """Strongly connected components with a cycle (size > 1 or self edge), iterative Tarjan."""
    adj = collections.defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    selfe = {a for a, b in edges if a == b}
    idx, low, on, st, out, n = {}, {}, set(), [], [], 0
    for root in list(adj):
        if root in idx:
            continue
        work = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                idx[v] = low[v] = n
                n += 1
                st.append(v)
                on.add(v)
            adv = False
            for j in range(i, len(adj[v])):
                w = adj[v][j]
                if w not in idx:
                    work.append((v, j + 1))
                    work.append((w, 0))
                    adv = True
                    break
                if w in on:
                    low[v] = min(low[v], idx[w])
            if adv:
                continue
            if low[v] == idx[v]:
                comp = []
                while True:
                    w = st.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1 or v in selfe:
                    out.append(comp)
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--image", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    rbf = a.input
    if a.image:
        import cycloneiv_decompress as cd
        rbf = PLANE
        os.makedirs(os.path.dirname(PLANE), exist_ok=True)
        open(PLANE, "wb").write(cd.decompress(open(a.input, "rb").read(), {}))
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    try:
        with heavy_guard.lease(gb, "cyc4_clean_loops", log):
            nl = emit.Builder(emit.Ctx(), rbf, "image" if a.image else None).run()
    finally:
        if a.image and os.path.exists(PLANE):
            os.remove(PLANE)
    all_e, dep_e = graph(nl)
    res = {"luts": len(nl.luts), "edges_all": len(all_e), "edges_dependent": len(dep_e)}
    for tag, e in (("all", all_e), ("dependent", dep_e)):
        c = sccs(e)
        res[f"loops_{tag}"] = len(c)
        res[f"loop_nodes_{tag}"] = sum(len(x) for x in c)
        res[f"loop_sizes_{tag}"] = sorted(collections.Counter(len(x) for x in c).items())
        res[f"loops_{tag}_with_carry"] = sum(1 for x in c if any(n[0] == "co" for n in x))
        if tag == "dependent":
            res["examples"] = [sorted(x)[:6] for x in c[:5]]
    log.info("%s", json.dumps(res))
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
