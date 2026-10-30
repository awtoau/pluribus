#!/usr/bin/env python3.15t
"""PLL / clock-buffer / clock-domain report of an EP4CGX150 compressed image through the clean pipeline (#175, #165).

  PLURIBUS_DJI_IMAGE=<image> python3.15t scripts/cycloneiv_clean_image_clocks.py [IMAGE]
Read-only on IMAGE; the decompressed plane is a derived file (tmp/cycloneiv_clean/image_plane_clocks.rbf), removed at exit.
Local detail (per PLL, per clock buffer site, per domain): tmp/cycloneiv_clean/image_clocks.json.  Counts go to the log / docs.
Fin is unknown: frequencies are intervals of Fin consistent with the vendor PLL limits (pll.fin_interval), never one value.
"""
import collections
import json
import logging
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_image as IMG  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_image_clocks.log")
PLANE = os.path.join(IMG.OUT, "image_plane_clocks.rbf")
RESULT = os.path.join(IMG.OUT, "image_clocks.json")
log = logging.getLogger("image_clocks")


def plls(cx, plane):
    from lifters.cycloneiv_clean import asmdb_walk as W, pll
    import cycloneiv_clean_dirt as D
    pm = pll.load(W.Walk(), D.enum_tables())
    cff = pll.read_cff(plane)
    out = {}
    for k, bt, p in pm.used(cff):
        prm = pm.params(cff, bt, p)
        out[k] = dict(btype=bt, path=p, params=prm, fin=pll.fin_interval(prm, "GPLL" if bt == 45 else "MPLL" if k in (6, 7) else "GPLL"))
    return out


def clock_buffers(cx, bits):
    """Per site: selected value, parent kind, source element."""
    cb, st, rt = cx.ext.clkbuf, cx.st, cx.rt
    rows = []
    for s in range(cb.line.n_sites):
        v = cb.line.select(bits, s)
        row = dict(site=s, value=v)
        if v == -1 or v == -2:
            row["kind"] = "undecoded_pattern" if v == -1 else "ambiguous_pattern"
        elif v == 7:
            row["kind"] = "unused"
        elif v not in cb.edge[s]:
            row["kind"] = f"value_without_edge_{v}"
        else:
            cand = [(e, icd) for e, icd in cb.edge[s][v] if e >= 0]
            en = cb.pllw.enabled(bits) if cb.pllw else frozenset()
            if len(cand) > 1:
                cand = [c for c in cand if c[1] in en]
            if len(cand) != 1:
                row["kind"] = "ambiguous_pll_parent"
            else:
                src = int(st.esrc[cand[0][0]])
                row["kind"] = cx.tn(src)
                row["src"] = [int(rt.x[src]), int(rt.y[src]), *rt.element(src)[3:5]]
                if cand[0][1] is not None:
                    row["pll"] = cand[0][1]
        rows.append(row)
    return rows


def domains(cx, bits, fired_head):
    """FF count per clock root (BLK_CLK_BUF line -> programmed parents -> root)."""
    st = cx.st
    ff = cx.ext.reg.ff(bits, fired_head)
    blk = np.where(ff, cx.ext.clocks.le_blk(bits), -1)
    src, dst = st.esrc[fired_head].astype(np.int64), st.edst[fired_head].astype(np.int64)
    o = np.argsort(dst, kind="stable")
    ds, ss = dst[o], src[o]
    cache = {}

    def roots(n):
        if n in cache:
            return cache[n]
        seen, stack, rts = {n}, [n], set()
        while stack:
            x = stack.pop()
            i, j = np.searchsorted(ds, x, "left"), np.searchsorted(ds, x, "right")
            ps = ss[i:j].tolist()
            if not ps:
                rts.add(x)
            for p in ps:
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        cache[n] = rts
        return rts
    cnt, unresolved = collections.Counter(), 0
    for r in blk[blk >= 0].tolist():
        rs = roots(r)
        if len(rs) == 1:
            cnt[next(iter(rs))] += 1
        else:
            unresolved += 1
    rows = []
    for r, n in cnt.most_common():
        e, x, y, z, i = cx.rt.element(r)
        rows.append(dict(root_type=cx.tn(r), x=x, y=y, z=z, index=i, ffs=n))
    return rows, dict(ff=int(ff.sum()), ff_no_line=int(ff.sum() - (blk >= 0).sum()), ff_unresolved_root=unresolved)


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    image = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PLURIBUS_DJI_IMAGE")
    if not image:
        raise SystemExit("image path: argument or env PLURIBUS_DJI_IMAGE")
    t0 = time.time()
    rbf, c, _ = IMG.container(open(image, "rb").read())
    open(PLANE, "wb").write(rbf)
    try:
        import heavy_guard
        gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
        with heavy_guard.lease(gb, "cyc4_clean_image_clocks", log):
            cx = IMG.Ctx()
            bits = cx.T.plane_bits(PLANE)
            res = {"pll": plls(cx, PLANE), "clock_buffers": clock_buffers(cx, bits)}
            _, fired, _ = IMG.routing(cx, bits)
            head = np.asarray(fired[cx.T.HEADLINE_VARIANT])
            res["domains"], res["domain_counts"] = domains(cx, bits, head)
    finally:
        if os.path.exists(PLANE):
            os.remove(PLANE)
    kinds = collections.Counter(r["kind"] for r in res["clock_buffers"])
    log.info("PLLs enabled %d: %s", len(res["pll"]), sorted(res["pll"]))
    log.info("clock buffer sites by source kind %s", dict(kinds))
    log.info("domains %d, counts %s; roots by type %s", len(res["domains"]), res["domain_counts"], dict(collections.Counter(d["root_type"] for d in res["domains"])))
    json.dump(res, open(RESULT, "w"), indent=1, default=str)
    log.info("wrote %s (%.0fs)", RESULT, time.time() - t0)


if __name__ == "__main__":
    main()
