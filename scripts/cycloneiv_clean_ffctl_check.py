#!/usr/bin/env python3.15t
"""FF control decode of the clean emit (lifters/cycloneiv_clean/ffctl.py + emit.py) against the Quartus post-fit ground truth (#165).

  python3.15t scripts/cycloneiv_clean_ffctl_check.py [--stride N --limit N | --names a,b,..] [--workers 3] [--tag T]
Per GT dffeas (matched to the emitted FF by site), per construct; matched / (matched + missing + extra + wrong), a missing connection is a fault:
  ff_ena    GT .ena != vcc: emitted ena source = GT net root and polarity equal = matched; none / undecoded = missing; other root or polarity = wrong;
            GT idle and emitted used = extra.  Same for ff_aclr (.clrn != vcc), ff_sclr (.sclr != gnd), ff_sload (.sload != gnd, GT FF with a LUT or FF-only).
  ff_clk_pol  GT .clk `!x` <-> emitted clock inverted (all FFs with an emitted clock).
  ff_asdata   GT sload FF with D from a LUT: emitted asdata source = GT ASDATA net root.
  lut_cin     GT cin-mode LE: emitted cin = the GT source LE's cout (same LAB or LE 15 of the LAB above).
Idle agreement (GT idle and emitted idle) is reported as `idle_ok`, outside the headline.  Failing scopes are enumerated per construct.
Log tmp/logs/cycloneiv_clean_ffctl_check.log; results tmp/cycloneiv_clean/ffctl_check_<tag>.json.
"""
import argparse
import collections
import concurrent.futures as cf
import glob
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
import cycloneiv_clean_emit_check as EC  # noqa: E402

log = logging.getLogger("cycloneiv_clean_ffctl_check")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_ffctl_check.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean")
CATS = ("ff_ena", "ff_aclr", "ff_sclr", "ff_sload", "ff_clk_pol", "ff_asdata", "lut_cin")
# source: Quartus dffeas ports: (emitted key, vo port, idle value, rcf port)
PORTS = (("ena", "ena", "vcc", "ENA"), ("aclr", "clrn", "vcc", "CLRN"), ("sclr", "sclr", "gnd", "SCLR"), ("sload", "sload", "gnd", "SLOAD"))


def score_design(cx, d, workers):
    from lifters.cycloneiv_clean import emit, tracer as T
    t0 = time.time()
    out = {c: dict(matched=0, missing=0, extra=0, wrong=0, idle_ok=0) for c in CATS}
    scope = collections.defaultdict(collections.Counter)
    b = emit.Builder(cx, os.path.join(d, "bitstream.rbf"), os.path.basename(d), workers)
    nl = b.run()
    lcs, lc_name, ffs, ff_name, qnet = EC.parse_gt(d)
    pins = EC.parse_pin(os.path.join(d, "build.pin"))
    nets = T.parse_rcf(os.path.join(d, "routing.rcf"))
    allnames = sorted({r for n in nets for r in n["roots"]})
    rec, _why = cx.res.resolve(allnames)
    ridx = {n: i for i, n in enumerate(allnames)}
    gtp = collections.defaultdict(dict)
    for n in nets:
        roots = {int(rec[ridx[r]]) for r in n["roots"] if rec[ridx[r]] >= 0}
        for _last, cell, port, _rp in n["dests"]:
            gtp[cell][port] = (roots, n)
    fm = {(F["x"], F["y"], F["le"]): F for F in nl.ffs}
    root = lambda r: int(b.root(np.asarray([r]))[0])
    for k, G in ffs.items():
        F = fm.get(k)
        if F is None:
            continue
        con = G["con"]
        ports = gtp.get(G["name"]) or gtp.get(re.sub(r"~q$", "", con.get("q", "").lstrip("\\").strip())) or {}
        for key, vo, idle, rp in PORTS:
            c = out["ff_" + key]
            gt_used = con.get(vo, idle) != idle
            mine = F.get(key) is not None
            if key == "sload" and con.get(vo) == "vcc":          # FF-only LE: constant-high sload (emitted as `sload_vcc`)
                c = out["ff_sload"]
                c["matched" if F.get("sload_vcc") else "missing"] += 1
                if not F.get("sload_vcc"):
                    scope["ff_sload"]["missing:sload_vcc"] += 1
                continue
            if key == "sload" and F.get("sload_vcc") and not gt_used:
                out["ff_sload"]["extra"] += 1
                scope["ff_sload"]["extra:sload_vcc_gt_idle"] += 1
                continue
            if not gt_used:
                if mine:
                    c["extra"] += 1
                    scope["ff_" + key]["extra:emitted_used_gt_idle"] += 1
                else:
                    c["idle_ok"] += 1
                continue
            if key == "sload" and con.get("sload") == "vcc" and con.get("d") == "gnd":
                pass
            if not mine:
                c["missing"] += 1
                scope["ff_" + key]["missing:" + ("undecoded" if key in " ".join(F["und"]) else "not_emitted")] += 1
                continue
            roots = ports.get(rp, (set(), None))[0]
            gt_inv = con[vo].startswith("!")
            if not roots:
                c["missing"] += 1
                scope["ff_" + key]["missing:no_gt_root"] += 1
            elif root(F[key + "_rec"]) not in roots:
                c["wrong"] += 1
                scope["ff_" + key]["wrong:root"] += 1
            elif bool(F[key + "_inv"]) != gt_inv:
                c["wrong"] += 1
                scope["ff_" + key]["wrong:polarity(inv=%s)" % gt_inv] += 1
            else:
                c["matched"] += 1
        if F["clk"] is not None:
            c = out["ff_clk_pol"]
            if bool(F.get("clk_inv")) == con.get("clk", "").startswith("!"):
                c["matched"] += 1
            else:
                c["wrong"] += 1
                scope["ff_clk_pol"]["wrong:gt_inv=%s" % con.get("clk", "").startswith("!")] += 1
        if con.get("sload") not in (None, "gnd", "vcc") and "ASDATA" in ports and con.get("d", "").lstrip("\\").strip() != "gnd":
            c = out["ff_asdata"]
            asd_net = ports["ASDATA"][1]
            gt_prod = EC.gt_producer(asd_net, lc_name, ff_name, qnet, pins, lcs, ffs) if asd_net is not None else None
            if F.get("asdata_prod") is None:
                c["missing"] += 1
                scope["ff_asdata"]["missing:not_emitted"] += 1
            elif gt_prod is None:
                c["missing"] += 1
                scope["ff_asdata"]["missing:no_gt_root"] += 1
            # own-register feedback (LE_USE_REGISTER_FEEDBACK, F-010) has no routing record: compare by producer tuple, like ff_d / lut_pin
            elif tuple(F["asdata_prod"]) == tuple(gt_prod):
                c["matched"] += 1
            else:
                c["wrong"] += 1
                scope["ff_asdata"]["wrong:root"] += 1
    # carry-in per cin-mode LE (same rule as the structural check; cross-LAB sources included)
    mine = {(L["x"], L["y"], L["le"]): L for L in nl.luts}
    for k, G in lcs.items():
        ci = G["con"].get("cin", "gnd")
        if G["mode"] != "cin" or ci in ("gnd", "vcc", ""):
            continue
        src = [kk for kk, g in lcs.items() if g["con"].get("cout") == ci]
        L = mine.get(k)
        c = out["lut_cin"]
        if L is None or L["cin"] is None:
            c["missing"] += 1
            scope["lut_cin"]["missing:" + ("lut_not_emitted" if L is None else "cin_undecoded")] += 1
        elif src and L["cin"] == "co_%d_%d_%d" % src[0]:
            c["matched"] += 1
            if (src[0][0], src[0][1]) != (k[0], k[1]):
                scope["lut_cin"]["info:matched_cross_lab"] += 1
        else:
            c["wrong"] += 1
            scope["lut_cin"]["wrong"] += 1
    return dict(design=os.path.basename(d), cats=out, scope={k: dict(v) for k, v in scope.items()}, seconds=round(time.time() - t0, 2),
                fail=[c for c in CATS if out[c]["wrong"] or out[c]["missing"] or out[c]["extra"]])


def headline(c):
    t = c["matched"] + c["missing"] + c["extra"] + c["wrong"]
    return 100.0 * c["matched"] / t if t else 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(REPO, "corpus", "cycloneiv"))
    ap.add_argument("--names")
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--tag", default="x")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    if a.names:
        ds = [os.path.join(a.root, n) for n in a.names.split(",")]
    else:
        ds = []
        for d in sorted(glob.glob(os.path.join(a.root, "*"))):
            if all(os.path.exists(os.path.join(d, f)) for f in ("bitstream.rbf", "routing.rcf", "postfit.vo", "build.pin")):
                try:
                    if json.load(open(os.path.join(d, "rebuild.json"))).get("status") != "ok" or "EP4CGX150" not in open(os.path.join(d, "routing.rcf")).read(600):
                        continue
                except (OSError, ValueError):
                    continue
                ds.append(d)
        ds = ds[::a.stride]
        ds = ds[:a.limit] if a.limit else ds
    import heavy_guard
    from lifters.cycloneiv_clean import emit, tracer as T
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + a.workers * (heavy_guard.JOB_GB["cyc4_clean_gate_worker"] + 0.4)
    rows, t0 = [], time.time()
    with heavy_guard.lease(gb, "cyc4_clean_ffctl_check", log):
        cx = emit.Ctx()
        cx.res = T.Resolver(cx.rt)
        cx.st.edge_ids([0], [0])
        log.info("designs %d", len(ds))
        with cf.ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(score_design, cx, d, 2): d for d in ds}
            pending = set(futs)
            while pending:
                done, pending = cf.wait(pending, timeout=60, return_when=cf.FIRST_COMPLETED)
                if not done:
                    log.error("stall: no design finished in 60 s (%d pending, load %s)", len(pending), os.getloadavg())
                    raise SystemExit(3)
                for f in done:
                    try:
                        r = f.result()
                        log.info("%s fail=%s %.1fs", r["design"], r["fail"], r["seconds"])
                    except Exception as e:      # a design that cannot be scored is a result, not a skip
                        import traceback
                        log.error("%s: %s: %s\n%s", futs[f], type(e).__name__, e, traceback.format_exc())
                        r = dict(design=os.path.basename(futs[f]), error=f"{type(e).__name__}: {e}")
                    rows.append(r)
    good = [r for r in rows if "error" not in r]
    tot = {c: collections.Counter() for c in CATS}
    scope = collections.defaultdict(collections.Counter)
    for r in good:
        for c in CATS:
            tot[c].update(r["cats"][c])
        for c, dd in r["scope"].items():
            scope[c].update(dd)
    log.info("DESIGNS %d / %d (errors %d) %.0fs", len(good), len(rows), len(rows) - len(good), time.time() - t0)
    for c in CATS:
        log.info("HEADLINE %-10s %6.2f%%  %s", c, headline(tot[c]), dict(tot[c]))
    for c, dd in scope.items():
        log.info("scope %s: %s", c, dict(dd.most_common(12)))
    fails = collections.defaultdict(list)
    for r in good:
        for c in r["fail"]:
            fails[c].append(r["design"])
    for c, ds_ in fails.items():
        log.info("failing designs %s (%d): %s", c, len(ds_), ds_[:25])
    json.dump(dict(totals={c: dict(v) for c, v in tot.items()}, headline={c: round(headline(tot[c]), 3) for c in CATS},
                   scope={c: dict(dd.most_common(40)) for c, dd in scope.items()}, failing={c: v for c, v in fails.items()}, rows=rows),
              open(os.path.join(OUT, f"ffctl_check_{a.tag}.json"), "w"), indent=0, default=str)


if __name__ == "__main__":
    main()
