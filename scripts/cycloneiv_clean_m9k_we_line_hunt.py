#!/usr/bin/env python3.15t
"""Which M9K control line (PIA gi 9 / 11) carries TDP port A's write enable (#181 item 7): site rule + deciding-bit hunt.
  python3.15t scripts/cycloneiv_clean_m9k_we_line_hunt.py [--match '*']      log tmp/logs/cycloneiv_clean_m9k_we_line_hunt.log
Per corpus TDP ram_block with both portawe / portbwe routed (postfit.vo + routing.rcf GT): site, GT line of A, every M9K control column
(raw bits, m9kctl.cols).  Reports (1) rule A-line vs x / y parity / mirrors, (2) control columns that separate A-on-9 from A-on-11
(perfect separators; same-site pairs), (3) raw byte diffs of the pairs given by --pair a,b.
"""
import argparse
import collections
import fnmatch
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_m9k_we_line_hunt.log")
log = logging.getLogger("m9k_we_line_hunt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(REPO, "corpus", "cycloneiv"))
    ap.add_argument("--match", default="*")
    ap.add_argument("--pair", default="gxhb_m9kwe_b_c1a,gxhb_m9kwe_b_c1b")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG, "w")])
    import heavy_guard
    import cycloneiv_clean_m9k_we_check as W
    from lifters.cycloneiv_clean import emit, m9k
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"]
    rows = []
    with heavy_guard.lease(gb, "cyc4_m9k_we_line_hunt", log):
        cx = emit.Ctx()
        for n in sorted(os.listdir(a.root)):
            d = os.path.join(a.root, n)
            if not fnmatch.fnmatch(n, a.match) or not os.path.exists(os.path.join(d, "postfit.vo")) or not os.path.exists(os.path.join(d, "bitstream.rbf")):
                continue
            txt = open(os.path.join(d, "postfit.vo")).read()
            if "ram_block" not in txt:
                continue
            rams = [r for r in W.parse_vo(txt) if r["mode"] == "bidir_dual_port"]
            if not rams:
                continue
            rcf = W.parse_rcf(open(os.path.join(d, "routing.rcf")).read())
            bits = cx.T.plane_bits(os.path.join(d, "bitstream.rbf"))
            mk = cx.m9kctl.decode(bits)
            for r in rams:
                x, y = r["xy"]
                i = m9k.instance(x, y)
                ga, gbb = rcf.get((x, y, "A")), rcf.get((x, y, "B"))
                ctl = {f"{g}#{k}": "".join(str(int(v)) for v in c[i]) for (g, k), c in mk["ctl"].items()}
                rows.append(dict(design=n, x=x, y=y, i=i, la=ga[0] if ga else None, lb=gbb[0] if gbb else None,
                                 pia=(int(mk["pia_all"][i, 9]), int(mk["pia_all"][i, 11])), ctl=ctl, mn=int(mk["ctl"][("RAM_WRITE_ENABLE_INVERT", 0)][i, 0])))
    both = [r for r in rows if r["la"] is not None and r["lb"] is not None]
    log.info("TDP blocks %d, both WE routed %d", len(rows), len(both))
    # (1) site rule
    log.info("== (1) A line vs site (both routed)")
    seen = collections.defaultdict(collections.Counter)
    for r in both:
        seen[(r["x"], r["y"])][r["la"]] += 1
    for xy, c in sorted(seen.items()):
        log.info("site X%d_Y%d (instance %d): A-line counts %s", xy[0], xy[1], m9k.instance(*xy), dict(c))
    for name, f in (("x%2", lambda r: r["x"] % 2), ("y%2", lambda r: r["y"] % 2), ("i%2", lambda r: r["i"] % 2), ("x%4", lambda r: r["x"] % 4)):
        t = collections.defaultdict(collections.Counter)
        for r in both:
            t[f(r)][r["la"]] += 1
        log.info("rule %s -> A line: %s", name, {k: dict(v) for k, v in sorted(t.items())})
    # (2) perfect separators among control columns
    log.info("== (2) control columns separating A-on-9 from A-on-11 (all both-routed rows, then spec-only)")
    for label, sel in (("all", both), ("gxhb_m9kwe only", [r for r in both if r["design"].startswith("gxhb_m9kwe")])):
        keys = sorted(sel[0]["ctl"]) if sel else []
        for k in keys:
            m = collections.defaultdict(set)
            for r in sel:
                m[r["la"]].add(r["ctl"][k])
            if m.get(9) and m.get(11) and not (m[9] & m[11]):
                log.info("[%s] SEPARATOR %s: A=9 values %s, A=11 values %s", label, k, sorted(m[9]), sorted(m[11]))
    log.info("-- per-column value histogram by A line (gxhb_m9kwe only, columns that vary at all)")
    sel = [r for r in both if r["design"].startswith("gxhb_m9kwe")]
    for k in sorted(sel[0]["ctl"]):
        h = collections.defaultdict(collections.Counter)
        for r in sel:
            h[r["la"]][r["ctl"][k]] += 1
        if len({v for c in h.values() for v in c}) > 1:
            log.info("%s: A=9 %s | A=11 %s", k, dict(h[9]), dict(h[11]))
    # (2b) candidate rule: RAM_WE_FAST_MUX gi 0 / gi 1 (8-bit mux column): bit 0 clear = default line (A 9, B 11), bit 0 set = alternate (A 11, B 9),
    #      bit 1 = no line.  Scored on every TDP block, per port with a routed WE.
    log.info("== (2b) rule: A line = 11 if FAST_MUX#0 bit0 else 9; B line = 9 if FAST_MUX#1 bit0 else 11")
    cnt = collections.Counter()
    for r in rows:
        for p, gt, fm, dflt, alt in (("A", r["la"], r["ctl"]["RAM_WE_FAST_MUX#0"], 9, 11), ("B", r["lb"], r["ctl"]["RAM_WE_FAST_MUX#1"], 11, 9)):
            if gt is None:
                continue
            pred = alt if fm[0] == "1" else dflt
            ok = pred == gt
            cnt[(p, "matched" if ok else "counter")] += 1
            if not ok:
                log.info("COUNTER %s X%d_Y%d port %s gt %s pred %s fm %s", r["design"], r["x"], r["y"], p, gt, pred, fm)
    log.info("rule 2b: %s", dict(cnt))
    # (3) raw diffs of a pair
    pa, pb = a.pair.split(",")
    A = np.fromfile(os.path.join(a.root, pa, "bitstream.rbf"), np.uint8)
    B = np.fromfile(os.path.join(a.root, pb, "bitstream.rbf"), np.uint8)
    log.info("== (3) pair %s vs %s: %d differing bytes", pa, pb, int((A != B).sum()))
    with heavy_guard.lease(gb, "cyc4_m9k_we_line_hunt_pair", log):
        cx = emit.Ctx()
        ba, bb = cx.T.plane_bits(os.path.join(a.root, pa, "bitstream.rbf")), cx.T.plane_bits(os.path.join(a.root, pb, "bitstream.rbf"))
        diff = np.where(ba != bb)[0]
        log.info("plane bits differing: %d", len(diff))
        names = {}
        for (g, k), cols in cx.m9kctl.cols.items():
            for inst in range(cols.shape[0]):
                for j, b in enumerate(cols[inst]):
                    names[int(b)] = (g, k, inst, j)
        for b in diff.tolist():
            log.info("plane bit %d (byte-ish): %s", b, names.get(b, "not a control column"))
    for r in rows:
        if r["design"] in (pa, pb):
            log.info("%s X%d_Y%d la=%s lb=%s pia(9,11)=%s", r["design"], r["x"], r["y"], r["la"], r["lb"], r["pia"])


if __name__ == "__main__":
    main()
