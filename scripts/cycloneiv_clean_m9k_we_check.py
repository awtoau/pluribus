#!/usr/bin/env python3.15t
"""M9K write-enable decode (emit.py / m9k_tdp.py) against the Quartus post-fit ground truth (#181 item 7).

  python3.15t scripts/cycloneiv_clean_m9k_we_check.py [--names a,b | --match '*']      log tmp/logs/cycloneiv_clean_m9k_we_check.log
Per design, every `cycloneiv_ram_block` of the postfit.vo (M9K location), matched / missing / extra / wrong:
  we_a     .portawe class (routed | inv `!sig` | gnd | vcc) vs the emitted port-A write enable (`(!x)` inv, `1'b1` vcc, `1'b0` gnd, else routed).
  we_b     same for .portbwe vs emitted `we_b`; true-dual-port blocks only (other modes tie portbwe to gnd).
  we_port  true-dual-port routed WE pins: the emitted signal of the port (`we` / `we_b`) = the signal on the GT control line of that port (A / B swap = wrong).
  we_line  routed WE pins: routing.rcf M4K_LEFT_CONTROL_INPUT index + preceding LOCAL_INTERCONNECT vs decoded RAM_PIA_TO_INPUT_YGR line (pia_all).
ROM-mode blocks are not scored (write enable inert; counted under scope rom_skipped).
Scoring: equal class = matched; GT routed / inv decoded const (or block not modelled) = missing; GT const decoded routed / inv = extra;
any other pair (gnd vs vcc, routed vs inv, wrong line) = wrong.
"""
import argparse
import collections
import fnmatch
import json
import logging
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("cycloneiv_clean_m9k_we_check")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_m9k_we_check.log")
CATS = ("we_a", "we_b", "we_line", "we_port")
CONST = ("gnd", "vcc")


def counts():
    return {"matched": 0, "missing": 0, "extra": 0, "wrong": 0}


def classify_gt(expr):
    """postfit.vo port expression -> routed | inv | gnd | vcc."""
    e = expr.strip()
    if e in CONST:
        return e
    return "inv" if e.startswith(("!", "~")) else "routed"


def classify_dec(we):
    """emitted write-enable string -> routed | inv | gnd | vcc."""
    if we == "1'b1":
        return "vcc"
    if we == "1'b0":
        return "gnd"
    return "inv" if we.startswith("(!") else "routed"


def verdict(gt, dec):
    if gt == dec:
        return "matched"
    if dec is None or (gt not in CONST and dec in CONST):
        return "missing"
    if gt in CONST and dec not in CONST:
        return "extra"
    return "wrong"


def parse_vo(text):
    """[{xy, name, mode, portawe, portbwe}] for every M9K ram block."""
    out = []
    for m in re.finditer(r"// Location: M9K_X(\d+)_Y(\d+)_N0\ncycloneiv_ram_block (\S+?) ?\((.*?)\);", text, re.S):
        body = m[4]
        pa = re.search(r"\.portawe\((.*?)\),\n", body)
        pb = re.search(r"\.portbwe\((.*?)\),\n", body)
        md = re.search(r"defparam %s ?\.operation_mode = \"(\w+)\"" % re.escape(m[3]), text)
        out.append(dict(xy=(int(m[1]), int(m[2])), name=m[3], mode=md[1] if md else None,
                        portawe=pa[1].strip() if pa else None, portbwe=pb[1].strip() if pb else None))
    return out


def parse_rcf(text):
    """{(x, y, 'A' | 'B'): (control index, local interconnect index)} for the WE pins of routing.rcf."""
    out = {}
    for blk in text.split("signal_name = ")[1:]:
        li, ctl = None, None
        for ln in blk.split("\n"):
            m = re.match(r"\s*LOCAL_INTERCONNECT:X\d+Y\d+S\d+I(\d+)", ln)
            if m:
                li = int(m[1])
            m = re.match(r"\s*M4K_LEFT_CONTROL_INPUT:X(\d+)Y(\d+)S\d+I(\d+)", ln)
            if m:
                ctl = (int(m[1]), int(m[2]), int(m[3]), li)
            m = re.match(r"\s*dest = \( [^,]*, PORT([AB])WE \)", ln)
            if m and ctl:
                out[(ctl[0], ctl[1], m[1])] = (ctl[2], ctl[3])
            if re.match(r"\s*dest = ", ln) or "branch_point" in ln:
                ctl = None
    return out


def score_design(cx, d, workers):
    import numpy as np
    from lifters.cycloneiv_clean import emit, m9k, names
    t0 = time.time()
    out = {c: counts() for c in CATS}
    scope = collections.defaultdict(collections.Counter)
    rows = []
    rams = parse_vo(open(os.path.join(d, "postfit.vo")).read())
    if not rams:
        return None
    rcf = parse_rcf(open(os.path.join(d, "routing.rcf")).read())
    b = emit.Builder(cx, os.path.join(d, "bitstream.rbf"), os.path.basename(d), workers)
    nl = b.run()
    mk = cx.m9kctl.decode(b.bits)
    ms = {(M["x"], M["y"]): M for M in nl.m9k}
    e_li = names.enum_of("LOCAL_INTERCONNECT")

    def line_sig(x, y, sel):
        rec = int(cx.find(e_li, x, y, 0, int(sel))) if sel >= 0 else -1
        return b.sig(rec)[0] if rec >= 0 else None
    for r in rams:
        x, y = r["xy"]
        M = ms.get((x, y))
        i = m9k.instance(x, y)
        tdp = r["mode"] == "bidir_dual_port"
        modelled = bool(M and M.get("modelled"))
        dec = {"A": classify_dec(M["we"]) if modelled else None, "B": (classify_dec(M["we_b"]) if modelled and M.get("we_b") else None) if tdp else None}
        raw = dict(w9=int(mk["pia_all"][i, 9]), w11=int(mk["pia_all"][i, 11]), inv=bool(mk["we_invert"][i]), inv_b=bool(mk["we_invert_b"][i]))
        rows.append(dict(design=os.path.basename(d), xy=(x, y), mode=r["mode"], vo=(r["portawe"], r["portbwe"]),
                         dec=(M.get("we") if modelled else "unmodelled", M.get("we_b") if modelled else None), raw=raw,
                         gt_line=(rcf.get((x, y, "A")), rcf.get((x, y, "B")))))
        for p, cat, gx in (("A", "we_a", r["portawe"]), ("B", "we_b", r["portbwe"])):
            if gx is None or (p == "B" and not tdp):
                continue
            if r["mode"] == "rom":                  # ROM write enable is inert (GT vcc over raw invert 1): counted, not scored
                scope["rom_skipped"][f"{p}: gt={gx}"] += 1
                continue
            g = classify_gt(gx)
            v = verdict(g, dec[p])
            out[cat][v] += 1
            if v != "matched":
                scope[cat][f"{v}: gt={g} dec={dec[p] or 'unmodelled'}"] += 1
            if g in ("routed", "inv") and rcf.get((x, y, p), (0, None))[1] is not None:
                ci, li = rcf[(x, y, p)]
                sel = int(mk["pia_all"][i, ci]) if 0 <= ci < mk["pia_all"].shape[1] else -1
                lv = "matched" if sel == li else ("missing" if sel < 0 else "wrong")
                out["we_line"][lv] += 1
                if tdp and modelled and lv == "matched":
                    ds = M["we" if p == "A" else "we_b"]
                    pv = "matched" if ds.removeprefix("(!").removesuffix(")") == line_sig(x, y, sel) else "wrong"
                    out["we_port"][pv] += 1
                    if pv != "matched":
                        scope["we_port"][f"wrong: port {p} gt line {ci}"] += 1
                if lv != "matched":
                    scope["we_line"][f"{lv}: port {p} gt line {ci} li {li} dec {sel}"] += 1
    return dict(design=os.path.basename(d), cats=out, scope={k: dict(v) for k, v in scope.items()}, rows=rows, seconds=round(time.time() - t0, 2))


def headline(c):
    t = sum(c.values())
    return 100.0 * c["matched"] / t if t else 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(REPO, "corpus", "cycloneiv"))
    ap.add_argument("--names")
    ap.add_argument("--match", default="*")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    names = a.names.split(",") if a.names else sorted(n for n in os.listdir(a.root) if fnmatch.fnmatch(n, a.match))
    ds = []
    for n in names:
        p = os.path.join(a.root, n)
        if os.path.exists(os.path.join(p, "postfit.vo")) and os.path.exists(os.path.join(p, "bitstream.rbf")) and "ram_block" in open(os.path.join(p, "postfit.vo")).read():
            ds.append(p)
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 2 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    res = []
    with heavy_guard.lease(gb, "cyc4_m9k_we_check", log):
        cx = emit.Ctx()
        for d in ds:
            try:
                r = score_design(cx, d, a.workers)
            except Exception as e:      # a design that cannot be scored is a result
                import traceback
                log.error("%s: %s\n%s", d, e, traceback.format_exc())
                r = dict(design=os.path.basename(d), error=str(e))
            if r is None:
                continue
            res.append(r)
            if "cats" in r:
                log.info("%s %s", r["design"], {c: r["cats"][c] for c in CATS if sum(r["cats"][c].values())})
    good = [r for r in res if "cats" in r]
    tot = {c: counts() for c in CATS}
    scope = collections.defaultdict(collections.Counter)
    for r in good:
        for c in CATS:
            for k, v in r["cats"][c].items():
                tot[c][k] += v
        for c, dd in r["scope"].items():
            scope[c].update(dd)
    log.info("DESIGNS %d scored / %d with ram_block / %d errors", len(good), len(ds), len(res) - len(good))
    for c in CATS:
        log.info("HEADLINE %-8s %6.2f%%  %s", c, headline(tot[c]), tot[c])
    allc = counts()
    for c in CATS:
        for k, v in tot[c].items():
            allc[k] += v
    log.info("HEADLINE all      %6.2f%%  %s", headline(allc), allc)
    for c, dd in scope.items():
        log.info("scope %s: %s", c, dict(dd.most_common(20)))
    for r in good:
        for w in r["rows"]:
            if w["vo"] != ("vcc", "gnd") and not (w["vo"][0] not in CONST and w["vo"][1] == "gnd" and not w["vo"][0].startswith("!")):
                log.info("row %s", w)
    for r in good:
        bad = [c for c in CATS if r["cats"][c]["missing"] or r["cats"][c]["extra"] or r["cats"][c]["wrong"]]
        if bad:
            log.info("failing %s: %s", r["design"], {c: r["cats"][c] for c in bad})
    os.makedirs(os.path.join(REPO, "tmp", "cycloneiv_clean"), exist_ok=True)
    json.dump(dict(totals=tot, rows=res), open(os.path.join(REPO, "tmp", "cycloneiv_clean", "m9k_we_check.json"), "w"), default=str)


if __name__ == "__main__":
    main()
