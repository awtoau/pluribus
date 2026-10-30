#!/usr/bin/env python3.15t
"""MAC decode (lifters/cycloneiv_clean/macctl.py + emit.py) against the Quartus post-fit ground truth (#165).

  python3.15t scripts/cycloneiv_clean_mac_check.py [--names a,b | --match 'gxhb_mac*']      log tmp/logs/cycloneiv_clean_mac_check.log
Per design (corpus designs whose postfit.vo has cycloneiv_mac_mult), matched / missing / extra / wrong:
  mac_inst  GT MAC tiles (DSPMULT / DSPOUT locations) vs decoded used instances (any control cell set).
  mac_cfg   single-multiplier 18 x 18 / 9-bit designs only: per MAC the items sign A / B (static signed, dynamic), input register A / B, output register,
            nine-bit rows, against the mac_mult / mac_out defparams and sign pins of the .vo.  Dynamic-sign: the sign pin is routed.
  mac_pin   routed MAC pins (DATAA[k], DATAB[k], CLK, SIGNA, SIGNB, ...): decoded LOCAL_INTERCONNECT index = the last LOCAL_INTERCONNECT of the net's route.
  mac_out   result bits: every DSP_BUFFER source in the emitted netlist maps to `mac_<x>_<y>_r[i]` with i = the element index (structural: GT roots).
The decode rules were read off these same specimen families (macpa / macpb = two MAC columns); no independent MAC design exists in the corpus.
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

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("cycloneiv_clean_mac_check")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_mac_check.log")
CATS = ("mac_inst", "mac_cfg", "mac_pin")
PIN_RCF = {"CLK": ("clk_sel", None), "ENA": ("ena_sel", None), "ACLR": ("aclr_sel", None), "SIGNA": ("sign_sel", 0), "SIGNB": ("sign_sel", 1)}


def counts():
    return {"matched": 0, "missing": 0, "extra": 0, "wrong": 0}


def parse_vo(d):
    text = open(os.path.join(d, "postfit.vo")).read()
    tiles, mults, outs = set(), [], {}
    for blk in text.split("\n// Location: ")[1:]:
        head, _, body = blk.partition("\n")
        m = re.match(r"DSP(MULT|OUT)_X(\d+)_Y(\d+)_N(\d+)$", head.strip())
        if not m:
            continue
        tiles.add((int(m[2]), int(m[3])))
        if m[1] == "OUT":
            nm = re.match(r"cycloneiv_mac_out (\S+)", body)
            outs[(int(m[2]), int(m[3]), int(m[4]))] = nm[1] if nm else None
        if m[1] == "MULT":
            nm = re.match(r"cycloneiv_mac_mult (\S+)", body)
            sign = {p: v.strip() for p, v in re.findall(r"\.(signa|signb)\((.*?)\)", body)}
            mults.append(dict(xy=(int(m[2]), int(m[3])), n=int(m[4]), name=nm[1] if nm else None, sign=sign, out=(int(m[2]), int(m[3]), int(m[4]) + 2)))
    for mu in mults:
        mu["out_name"] = outs.get(mu["out"])
    return text, tiles, mults


def gt_cfg(text, mult):
    nm = re.escape(mult["name"])
    par = {k: v.strip('"') for k, v in re.findall(r"defparam %s \.(\w+) = (\"?\w+\"?);" % nm, text)}
    sign = mult["sign"]
    outm = re.search(r"defparam %s \.output_clock = \"?(\w+)\"?;" % re.escape(mult["out_name"] or "?"), text)
    return dict(reg_a=par.get("dataa_clock", "none") != "none", reg_b=par.get("datab_clock", "none") != "none",
                oreg=bool(outm) and outm[1] != "none", nine=par.get("dataa_width") == "9",
                dyn_a=sign.get("signa", "gnd") not in ("gnd", "vcc"), dyn_b=sign.get("signb", "gnd") not in ("gnd", "vcc"),
                signed_a=sign.get("signa") == "vcc", signed_b=sign.get("signb") == "vcc")


def hier(name):
    """Hierarchical cell name without the quartus escape and without the `entity:` prefixes of the RCF form (`lpm_mult:Mult4|mult_4et:auto_generated|mac_mult1` = `\\Mult4|auto_generated|mac_mult1`)."""
    return re.sub(r"(^|\|)\w+:", r"\1", name.strip().lstrip("\\"))


def gt_pins(d):
    """{(x, y): {mult name: {pin: LI index}}} from routing.rcf nets with a dest on a mac_mult cell.  Data pins: last LOCAL_INTERCONNECT of the net
    before the dest.  Control pins (CLK / ENA / ACLR / SIGN*): only when the stanza since the previous dest passes DSP_CONTROL_INPUT; LI = the one before it."""
    txt = open(os.path.join(d, "routing.rcf")).read()
    out = collections.defaultdict(lambda: collections.defaultdict(dict))
    for blk in txt.split("signal_name = ")[1:]:
        last_li, stanza_li, ctl, stanza_has_ctl = None, None, None, False
        for ln in blk.split("\n"):
            m = re.match(r"\s*LOCAL_INTERCONNECT:X(\d+)Y(\d+)S\d+I(\d+)", ln)
            if m:
                last_li = stanza_li = (int(m[1]), int(m[2]), int(m[3]))
            m = re.match(r"\s*DSP_CONTROL_INPUT:X(\d+)Y(\d+)", ln)
            if m:
                ctl = stanza_li
            m = re.match(r"\s*dest = \( ([^,]*mac_mult\d*), (\w+(?:\[\d+\])?) \)", ln)
            if m:
                pin = m[2]
                if pin.startswith("DATA"):
                    li = last_li
                else:
                    li = ctl if stanza_has_ctl else None
                if li:
                    out[(li[0], li[1])][hier(m[1])][pin] = li[2]
            if re.match(r"\s*dest = ", ln) or "branch_point" in ln:
                stanza_li = None
                stanza_has_ctl = False
            elif re.match(r"\s*DSP_CONTROL_INPUT:", ln):
                stanza_has_ctl = True
    return out


def score_design(cx, d, workers):
    from lifters.cycloneiv_clean import emit, mac, macctl
    t0 = time.time()
    out = {c: counts() for c in CATS}
    scope = collections.defaultdict(collections.Counter)
    b = emit.Builder(cx, os.path.join(d, "bitstream.rbf"), os.path.basename(d), workers)
    nl = b.run()
    md = cx.macctl.decode(b.bits)
    mcols = mac.columns()
    text, tiles, mults = parse_vo(d)
    mine = {(mcols[i // 90], i % 90 + 1): i for i in np.flatnonzero(md["used"]).tolist()}
    for t in tiles:
        out["mac_inst"]["matched" if t in mine else "missing"] += 1
        if t not in mine:
            scope["mac_inst"]["missing"] += 1
    for t in mine:
        if t not in tiles:
            out["mac_inst"]["extra"] += 1
            scope["mac_inst"]["extra"] += 1
    pins = gt_pins(d)
    short = {}
    for mu in mults:
        short[(mu["xy"], hier(mu["name"] or ""))] = mu
        t = mu["xy"]
        if t not in mine:
            continue
        i = mine[t]
        n = mu["n"]
        g = gt_cfg(text, mu)
        nine = bool(md["nine"][i])
        ra, rb, ro = (md["ireg_n"][i, n, 0], md["ireg_n"][i, n, 1], md["oreg_n"][i, n]) if nine else (md["ireg"][i, 0], md["ireg"][i, 1], md["oreg"][i])
        items = [("reg_a", bool(ra)), ("reg_b", bool(rb)), ("oreg", bool(ro)), ("nine", nine),
                 ("dyn_a", md["sign_sel"][i, 0] >= 0), ("dyn_b", md["sign_sel"][i, 1] >= 0)]
        if not g["dyn_a"]:
            items.append(("signed_a", not md["unsigned"][i, 0]))
        if not g["dyn_b"]:
            items.append(("signed_b", not md["unsigned"][i, 1]))
        for k, v in items:
            if v == g[k]:
                out["mac_cfg"]["matched"] += 1
            else:
                out["mac_cfg"]["missing" if g[k] else "extra"] += 1
                scope["mac_cfg"][f"{k}: gt={g[k]}"] += 1
    for t, mm in pins.items():
        i = mine.get(t)
        for mname, pm in mm.items():
            mu = short.get((t, mname))
            n = mu["n"] if mu else 0
            ar, br = macctl.rows(n, bool(md["nine"][i])) if i is not None else (None, None)
            for pin, li in pm.items():
                m = re.fullmatch(r"DATA([AB])\[(\d+)\]", pin)
                if m:
                    sel = md["data_sel"][i, (ar if m[1] == "A" else br)[int(m[2])]] if i is not None else -1
                elif pin in PIN_RCF:
                    key, idx = PIN_RCF[pin]
                    sel = (md[key][i] if idx is None else md[key][i, idx]) if i is not None else -1
                else:
                    continue
                c = out["mac_pin"]
                if sel == li:
                    c["matched"] += 1
                elif sel < 0:
                    c["missing"] += 1
                    scope["mac_pin"][f"missing:{'CLK' if pin == 'CLK' else 'other'}"] += 1
                else:
                    c["wrong"] += 1
                    scope["mac_pin"]["wrong"] += 1
    return dict(design=os.path.basename(d), cats=out, scope={k: dict(v) for k, v in scope.items()}, seconds=round(time.time() - t0, 2))


def headline(c):
    t = sum(c.values())
    return 100.0 * c["matched"] / t if t else 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(REPO, "corpus", "cycloneiv"))
    ap.add_argument("--names")
    ap.add_argument("--match", default="gxhb_mac*")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    names = a.names.split(",") if a.names else sorted(n for n in os.listdir(a.root) if fnmatch.fnmatch(n, a.match))
    ds = [os.path.join(a.root, n) for n in names if os.path.exists(os.path.join(a.root, n, "postfit.vo"))]
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 2 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    rows = []
    with heavy_guard.lease(gb, "cyc4_mac_check", log):
        cx = emit.Ctx()
        for d in ds:
            try:
                r = score_design(cx, d, 2)
            except Exception as e:      # a design that cannot be scored is a result
                import traceback
                log.error("%s: %s\n%s", d, e, traceback.format_exc())
                r = dict(design=os.path.basename(d), error=str(e))
            rows.append(r)
            if "cats" in r:
                log.info("%s %s", r["design"], {c: r["cats"][c] for c in CATS if sum(r["cats"][c].values())})
    good = [r for r in rows if "cats" in r]
    tot = {c: counts() for c in CATS}
    scope = collections.defaultdict(collections.Counter)
    for r in good:
        for c in CATS:
            for k, v in r["cats"][c].items():
                tot[c][k] += v
        for c, dd in r["scope"].items():
            scope[c].update(dd)
    log.info("DESIGNS %d / %d", len(good), len(rows))
    for c in CATS:
        log.info("HEADLINE %-9s %6.2f%%  %s", c, headline(tot[c]), tot[c])
    for c, dd in scope.items():
        log.info("scope %s: %s", c, dict(dd.most_common(12)))
    for r in good:
        bad = [c for c in CATS if r["cats"][c]["missing"] or r["cats"][c]["extra"] or r["cats"][c]["wrong"]]
        if bad:
            log.info("failing %s: %s", r["design"], {c: r["cats"][c] for c in bad})
    os.makedirs(os.path.join(REPO, "tmp", "cycloneiv_clean"), exist_ok=True)
    json.dump(dict(totals=tot, rows=rows), open(os.path.join(REPO, "tmp", "cycloneiv_clean", "mac_check.json"), "w"), default=str)


if __name__ == "__main__":
    main()
