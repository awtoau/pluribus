#!/usr/bin/env python3.15t
"""Cyclone IV GX150 LOCAL_LINE pip table + exact resolver from specimen evidence (#141).

Table: per (source LE index, sink LE N, port) the 4 tile-relative CRAM bits of the same-LAB LOCAL_LINE pip,
from the forced-single-hop specimen grids (evidence rows kind specimen-pair; scripts/cycloneiv_forced.py).
Translation: cell = (FX[x] + df) * NV + (vy0 + vpitch * y + dv), as in scripts/cycloneiv_bit_inventory.py class 3.
Resolver: a pip is PRESENT in a LAB when all its bits are set.  Bit sets are not unique across pairs, so
the output is the CANDIDATE set per sink input (LAB, sink N, port); exactly one candidate = `unique`.
No statistics: nothing is picked among several candidates.

  python3.15t scripts/cycloneiv_pip_table.py table                      # table + 4-LAB agreement
  python3.15t scripts/cycloneiv_pip_table.py validate [--limit N]       # vs RCF LOCAL_LINE of the gate set
  python3.15t scripts/cycloneiv_pip_table.py image --image <rbf|bin>    # resolve one image, summary
Log tmp/logs/cycloneiv_pip_table.log; JSON tmp/cycloneiv_pip_table_*.json.
"""
import argparse
import collections
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_bit_inventory as bi  # noqa: E402

log = logging.getLogger("cycloneiv_pip_table")
NV = bi.NV
DIE_NAME = "EP4CGX150"
LAB_NS = tuple(range(0, 32, 2))      # LCCOMB N of the 16 LEs; source LE index i <-> N = 2 i
SRC_TAG = "specimen-localline"       # source tag per resolved hop (bisectable in the tracer)


def build_table(g=None):
    """{(src LE index, snk_N, port): ((df, dv) x4)} from LAB X10Y10 + per-LAB agreement stats.
    Every LAB is translated to tile-relative offsets with FX/vy; pairs where LABs disagree are DROPPED
    from the table (reported), not voted over."""
    per_lab = []
    for fp, (lx, ly) in zip(bi.FORCED, bi.FORCED_LAB):
        tab = bi.forced_table(fp)
        cur = {}
        for r in tab.values():
            assert r["src"] % 2 == 0
            k = (r["src"] // 2, r["snk"], r["hop"][4])      # source LE index i = N / 2 (= RCF LOCAL_LINE index)
            cur[k] = tuple(sorted((b // NV - g.FX[lx], b % NV - (g.vy0 + g.vpitch * ly)) for b in r["on"]))
        per_lab.append(((lx, ly), cur))
    ref = per_lab[0][1]
    agree = {}
    drop = set()
    for (lx, ly), cur in per_lab:
        same = [k for k in cur if ref.get(k) == cur[k]]
        agree[f"X{lx}Y{ly}"] = (len(same), len(cur))
        drop |= {k for k in set(cur) | set(ref) if cur.get(k) != ref.get(k)}
    table = {k: v for k, v in ref.items() if k not in drop}
    return table, agree, sorted(drop)


class Resolver:
    """Dense-plane resolver of the LOCAL_LINE class over all LABs at once."""

    def __init__(self, g, table=None, workers=6, mode="full"):
        """mode full: all 4 bits (pure specimen fact).  mode pq: only the 2 pair/sink bits; the 2 source-LE
        bits (C, D) are ignored - hypothesis (RCF-validated, not specimen-proven): C = LE datac/arith mode,
        D = comb (not registered) output, i.e. source state, so the specimens (comb, datac sources) saw them set."""
        self.g = g
        self.mode = mode
        self.tiles = bi.lab_tiles(g)                               # (x, y) of every LAB
        self.table = table if table is not None else build_table(g)[0]
        self.keys = sorted(self.table)
        self.universe = sorted({b for v in self.table.values() for b in v})
        uidx = {b: i for i, b in enumerate(self.universe)}
        use = collections.defaultdict(set)
        for k, v in self.table.items():
            for b in v:
                use[b].add(k)
        self.src_bits = {b for b, ks in use.items() if len(ks) >= 15 and len({k[0] for k in ks}) == 1}
        sel = (lambda b: True) if mode == "full" else (lambda b: b not in self.src_bits)
        self.pair_bits = np.array([[uidx[b] for b in self.table[k] if sel(b)] for k in self.keys], np.int32)   # [P, 4 or 2]
        self.fx = np.array([g.FX[int(x)] for x in self.tiles[:, 0]], np.int64)
        self.vy = g.vy0 + g.vpitch * self.tiles[:, 1].astype(np.int64)
        self.workers = workers
        self.sink_of = np.array([(k[1], k[2]) for k in self.keys], dtype=object)

    def present(self, plane):
        """bool [nLAB, P]: all bits of pip p set in LAB l.  Threads over LAB bands (read-only dense plane)."""
        plane.dense()
        n = len(self.tiles)
        out = np.zeros((n, len(self.keys)), bool)
        uf = np.array([b[0] for b in self.universe], np.int64)
        uv = np.array([b[1] for b in self.universe], np.int64)
        bands = np.array_split(np.arange(n), max(1, self.workers * 4))

        def one(ix):
            f = self.fx[ix][:, None] + uf[None, :]
            v = self.vy[ix][:, None] + uv[None, :]
            bits = plane.has(f.ravel(), v.ravel()).reshape(len(ix), -1)         # [b, U]
            m = bits[:, self.pair_bits[:, 0]]
            for j in range(1, self.pair_bits.shape[1]):
                m &= bits[:, self.pair_bits[:, j]]
            out[ix] = m

        with ThreadPoolExecutor(self.workers) as ex:
            list(ex.map(one, bands))
        return out

    def candidates(self, plane):
        """{(x, y, snk_N, port): [src, ...]} for every sink input with >= 1 present pip."""
        pres = self.present(plane)
        li, pi = np.nonzero(pres)
        cand = collections.defaultdict(list)
        for l, p in zip(li.tolist(), pi.tolist()):
            src, snk, port = self.keys[p]
            cand[(int(self.tiles[l, 0]), int(self.tiles[l, 1]), snk, port)].append(src)
        return cand


def rcf_truth(name):
    """{(x, y, snk_N, port): src} from the RCF LOCAL_LINE hops of a corpus design + diagnostics.
    Sink = an LCCOMB atom placed in the same LAB; others are counted in `skipped` by reason."""
    import cycloneiv_corpus as cc
    import cycloneiv_route_learn as rl
    d = cc.CORPUS / name
    rcf = cc.parse_rcf(d / "routing.rcf")
    vo = cc.load_vo(name)
    loc = {}
    for aname, a in vo.atoms.items():
        m = rl.LOC.match(a.get("location") or "")
        if m and m.group(1) == "LCCOMB":
            loc[aname] = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
    truth, skipped = {}, collections.Counter()
    for edges in rcf.values():
        for s, t in edges:
            if s[0] != "W" or s[1] != "LOCAL_LINE" or t[0] != "SINK":
                if s[0] == "W" and s[1] == "LOCAL_LINE":
                    skipped["LOCAL_LINE -> non-sink"] += 1
                continue
            x, y, i = s[2], s[3], s[5]
            a = loc.get(t[1])
            if a is None:
                skipped["sink atom not an LCCOMB"] += 1
                continue
            if (a[0], a[1]) != (x, y):
                skipped["sink in another LAB"] += 1
                continue
            key = (x, y, a[2], t[2].upper())
            if key in truth and truth[key] != i:
                skipped["two sources for one sink input"] += 1
            truth[key] = i
    return truth, skipped


def score(cand, truth, table):
    """Per sink input: matched / missing / extra / wrong (+ ambiguity), with causes of misses."""
    c = collections.Counter()
    why = collections.Counter()
    per_lab = collections.defaultdict(collections.Counter)
    for key in set(cand) | set(truth):
        t, S = truth.get(key), cand.get(key, [])
        lab = key[:2]
        if not S:
            if t is None:
                continue
            c["missing"] += 1
            per_lab[lab]["missing"] += 1
            if (t, key[2], key[3]) not in table:
                why["not in table: " + ("self source (src LE == sink LE)" if t == key[2] // 2 else
                                        "sink port " + key[3] if key[3] in ("DATAA", "DATAB") else
                                        "pair known on the other C/D port only")] += 1
            else:
                why["table pair known but its bits are not all set"] += 1
        elif len(S) == 1:
            if t is None:
                c["extra"] += 1
                per_lab[lab]["extra"] += 1
            elif S[0] == t:
                c["matched"] += 1
                per_lab[lab]["matched"] += 1
            else:
                c["wrong"] += 1
                per_lab[lab]["wrong"] += 1
        else:
            c["ambiguous"] += 1
            if t is not None:
                c["missing"] += 1                    # no exact answer for a real hop
                per_lab[lab]["missing"] += 1
                why["ambiguous candidate set" + (" (truth inside)" if t in S else " (truth NOT inside)")] += 1
                c["ambiguous_truth_inside" if t in S else "ambiguous_truth_outside"] += 1
            else:
                c["ambiguous_no_truth"] += 1
    return c, why, per_lab


def headline(c):
    d = c["matched"] + c["missing"] + c["extra"] + c["wrong"]
    return f"matched {c['matched']} / (matched {c['matched']} + missing {c['missing']} + extra {c['extra']} + wrong {c['wrong']}) = {100 * c['matched'] / d:.2f}%" if d else "no hops"


def validate_design(R, name):
    """one design; R.mode picks full / pq"""
    import cycloneiv_corpus as cc
    plane = cc.load_plane_only(name)
    cand = R.candidates(plane)
    truth, skipped = rcf_truth(name)
    c, why, per_lab = score(cand, truth, R.table)
    # domain = hops whose (src, snk, port) is in the table
    dom_t = {k: v for k, v in truth.items() if (v, k[2], k[3]) in R.table}
    cd_, _w, _p = score({k: v for k, v in cand.items()}, dom_t, R.table)
    c_dom = collections.Counter({k: cd_[k] for k in ("matched", "missing", "wrong")})
    # extras in the domain view: unique candidates for sinks that have no truth at all
    c_dom["extra"] = cd_["extra"]
    return dict(name=name, n_truth=len(truth), n_dom=len(dom_t), counts=dict(c), dom=dict(c_dom), why=dict(why),
                skipped=dict(skipped), cand_sinks=len(cand), multi=sum(1 for s in cand.values() if len(s) > 1))


# -- tracer option (not in the default lift path) -----------------------------------------------------
def make_localline_view(ddb_unit_view, resolver=None):
    """UnitView whose tracers answer an LCCOMB pin from a UNIQUE present LOCAL_LINE pip first (source tag
    SRC_TAG in tracer.why), else defer to the ddb tracer.  tracer.ll_stats counts agree / differ / gain."""
    import cycloneiv_ddb_trace as dt

    class LLTracer(dt.DdbTracer):
        def __init__(self, *args, cand, **kw):
            super().__init__(*args, **kw)
            self.cand = cand
            self.ll_stats = collections.Counter()

        def _trace(self, key, x, y):
            kind, n, port = key
            base = super()._trace(key, x, y)
            if kind != "LCCOMB":
                return base
            S = self.cand.get((x, y, n, port))
            if not S:
                return base
            if len(S) > 1:
                self.ll_stats["ambiguous"] += 1
                return base
            g, _w = self.driver(x, y, S[0], None)
            if g is None:
                self.ll_stats["unique_but_cell_unreadable"] += 1
                return base
            if base[0] is None:
                self.ll_stats["gain (base unresolved)"] += 1
            elif base[0] == g:
                self.ll_stats["agree"] += 1
            else:
                self.ll_stats["differ"] += 1
            return g, SRC_TAG

    class LLView(type(ddb_unit_view)):
        def __init__(self, D):
            super().__init__(D)
            self.res = resolver or Resolver(D.P.g)
            self.tracer = None

        def make_tracer(self, plane, geom, learner, terminals):
            cand = self.res.candidates(plane)
            self.tracer = LLTracer(self.D, self, plane, geom, learner, None, terminals, cand=cand)
            return self.tracer

    return LLView(ddb_unit_view.D)


def cmd_table(a):
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of(DIE_NAME))
    table, agree, drop = build_table(g)
    log.info("table: %d pairs (src, snk, port); universe %d distinct tile-relative cells; dropped (LABs disagree) %d",
             len(table), len({b for v in table.values() for b in v}), len(drop))
    log.info("per-LAB agreement with X10Y10 after translation: %s", agree)
    ports = collections.Counter(k[2] for k in table)
    log.info("ports covered: %s (DATAA/DATAB untested)", dict(ports))
    # static aliasing: pairs whose 4-bit set is covered by the union of other sources' bits at the same sink
    by_sink = collections.defaultdict(list)
    for k, v in table.items():
        by_sink[(k[1], k[2])].append((k[0], set(v)))
    same = sum(1 for k, v in table.items() for k2, v2 in table.items() if k < k2 and v == v2)
    log.info("identical bit sets across distinct pairs: %d", same)


def cmd_validate(a):
    import heavy_guard
    import cycloneiv_corpus as cc
    import cycloneiv_geom as cg
    import cycloneiv_route_learn as rl
    names = [n for n in cc.designs("gx150_rb*") if rl.split_of(n, "odd")]
    log.info("gate set: %d designs with routing.rcf + bitstream.rbf", len(names))
    if a.limit:
        names = names[:a.limit]
    g = cg.load(cg.die_of(DIE_NAME))
    R = Resolver(g, workers=a.workers, mode=a.mode)
    log.info("resolver (mode %s): %d pairs, %d LABs, universe %d cells", R.mode, len(R.keys), len(R.tiles), len(R.universe))
    import contextlib
    ctx = contextlib.nullcontext() if a.no_lease else heavy_guard.lease(a.lease_gb, "cyc4_pip_table", log)
    with ctx:
        with ThreadPoolExecutor(a.jobs) as ex:
            res = list(ex.map(lambda n: validate_design(R, n), names))
    import resource
    log.info("peak RSS %.2f GB (%d jobs x %d workers)", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, a.jobs, a.workers)
    tot, dom, why, skipped = (collections.Counter() for _ in range(4))
    for r in res:
        tot.update(r["counts"]); dom.update(r["dom"]); why.update(r["why"]); skipped.update(r["skipped"])
        log.info("%s truth %d (in-table %d): %s", r["name"], r["n_truth"], r["n_dom"], headline(collections.Counter(r["counts"])))
    n_truth = sum(r["n_truth"] for r in res)
    n_dom = sum(r["n_dom"] for r in res)
    log.info("== %d designs, %d RCF LOCAL_LINE sink inputs (%d with a pair/port in the table) ==", len(res), n_truth, n_dom)
    log.info("ALL hops: %s", headline(tot))
    log.info("  unique/ambiguous: ambiguous sink inputs %d (truth inside %d, outside %d, no truth %d)", tot["ambiguous"],
             tot["ambiguous_truth_inside"], tot["ambiguous_truth_outside"], tot["ambiguous_no_truth"])
    log.info("IN-TABLE hops only: matched %d missing %d wrong %d extra(all sinks) %d", dom["matched"], dom["missing"], dom["wrong"], dom["extra"])
    log.info("precision (unique candidates) = matched / (matched + wrong + extra) = %.2f%%; recall = matched / truth = %.2f%%",
             100 * tot["matched"] / max(1, tot["matched"] + tot["wrong"] + tot["extra"]), 100 * tot["matched"] / max(1, n_truth))
    for k, v in why.most_common():
        log.info("  miss cause: %6d  %s", v, k)
    log.info("  skipped RCF hops: %s", dict(skipped))
    (REPO / "tmp").mkdir(exist_ok=True)
    (REPO / "tmp/cycloneiv_pip_table_validate.json").write_text(json.dumps(dict(designs=res, total=dict(tot), dom=dict(dom), why=dict(why)), indent=1))


def cmd_image(a):
    import cycloneiv_corpus as cc
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of(DIE_NAME))
    plane = cc.cram_plane(Path(a.image).read_bytes(), g)
    R = Resolver(g, workers=a.workers, mode=a.mode)
    cand = R.candidates(plane)
    uniq = sum(1 for s in cand.values() if len(s) == 1)
    log.info("image: %d sink inputs with >=1 present LOCAL_LINE pip; unique %d, ambiguous %d", len(cand), uniq, len(cand) - uniq)
    hist = collections.Counter(len(s) for s in cand.values())
    log.info("candidates-per-sink histogram %s", dict(sorted(hist.items())))
    labs = len({k[:2] for k in cand})
    log.info("LABs with >=1 candidate %d of %d", labs, len(R.tiles))
    (REPO / "tmp").mkdir(exist_ok=True)
    (REPO / "tmp/cycloneiv_pip_table_image.json").write_text(json.dumps(dict(
        sinks=len(cand), unique=uniq, hist={str(k): v for k, v in sorted(hist.items())}, labs=labs)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["table", "validate", "image"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--lease-gb", type=float, default=3.0)
    ap.add_argument("--no-lease", action="store_true", help="skip the memory lease (the ramp rule starves non-build_pool jobs while a sweep runs; this job is < 2 GB)")
    ap.add_argument("--mode", choices=["full", "pq"], default="full")
    ap.add_argument("--image")
    a = ap.parse_args()
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/cycloneiv_pip_table.log", "w")])
    {"table": cmd_table, "validate": cmd_validate, "image": cmd_image}[a.cmd](a)


if __name__ == "__main__":
    main()
