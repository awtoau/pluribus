#!/usr/bin/env python3.15t
"""Structural check of the clean emit (lifters/cycloneiv_clean/emit.py) against the Quartus post-fit ground truth (#165).

  python3.15t scripts/cycloneiv_clean_emit_check.py --root corpus/cycloneiv --names gx150_rb_000,... [--stride N --limit N] [--tag T]
Ground truth per design: postfit.vo (cells, masks, FF connections), routing.rcf (net -> sink pin, with route_port = physical pin), build.pin.
Per construct: matched / (matched + missing + extra + wrong); a missing connection is a fault (ambiguous / undecoded = missing).
  lut_site   emitted LUT at a GT lcell site with equal INIT and equal sum_lutc_input mode = matched; same site, differs = wrong;
             GT lcell not emitted = missing; emitted LUT with no GT lcell = extra.
  lut_pin    every RCF-routed LUT input (physical pin): driver produced = driver of the GT net (LC / FF / PAD by net name; other sources by the
             RCF root element) = matched; pin left unconnected / undecoded = missing; other driver = wrong; emitted connection at a matched
             site where the GT pin is not routed = extra.
  lut_carry  GT lcell with cin from the previous lcell: emitted cin = same LE-1 cout = matched; else missing / wrong.
  ff_site    emitted FF at a GT dffeas site = matched; GT FF not emitted = missing; emitted without GT FF = extra.
  ff_clock   emitted clock net's root record is a root of the GT CLK net (gate rule); none = missing.
  ff_d       GT D = combout of the lcell at the same LE and emitted D = that LUT = matched; GT D from elsewhere = missing (not modelled).
  io_dir     GT port ball: emitted pad with equal direction = matched; absent / undecoded direction = missing; different = wrong; emitted pad with no GT port = extra.
  io_data    GT output port driver (net feeding `<port>~output I`) equals the emitted pad driver producer; undecoded = missing.
Not scored here (reported as GT usage counts, not faults of this check): FF enable / clear / sclr / sload non-idle in GT (model is idle).
Log tmp/logs/cycloneiv_clean_emit_check.log; results tmp/cycloneiv_clean/emit_check_<tag>.json.
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
log = logging.getLogger("cycloneiv_clean_emit_check")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_emit_check.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean")
CATS = ("lut_site", "lut_pin", "lut_carry", "ff_site", "ff_clock", "ff_d", "io_dir", "io_data")
# source: Quartus lcell / dffeas port names (cycloneiv_lcell_comb, dffeas primitives)
FF_PORTS = ("clk", "d", "asdata", "clrn", "aload", "sclr", "sload", "ena")
PHYS = {"DATAA": 0, "DATAB": 1, "DATAC": 2, "DATAD": 3}
# source: scripts/cycloneiv_clean_gate.py DIR (io_decode default-pattern kinds vs build.pin direction column)
DIRMAP = {"input": "input", "output": "output", "bidir": "bidir-or-tristate"}


def counts():
    return {"matched": 0, "missing": 0, "extra": 0, "wrong": 0}


def headline(c):
    t = sum(c.values())
    return 100.0 * c["matched"] / t if t else 100.0


def parse_gt(d):
    """-> (lcells {(x,y,le): dict}, lc_by_name, ffs {(x,y,le): dict}, ff_by_name, ff_qname)"""
    text = open(os.path.join(d, "postfit.vo")).read()
    lcs, ffs, lc_name, ff_name, qnet = {}, {}, {}, {}, {}
    for blk in text.split("\n// Location: ")[1:]:
        head, _, body = blk.partition("\n")
        m = re.match(r"(LCCOMB|FF)_X(\d+)_Y(\d+)_N(\d+)$", head.strip())
        if not m:
            continue
        key = (int(m[2]), int(m[3]), int(m[4]) // 2)
        nm = re.match(r"(?:cycloneiv_lcell_comb|dffeas) (\S+?)\s*\(", body)
        if not nm:
            continue
        name = nm[1].lstrip("\\")
        if m[1] == "FF":
            con = {p: v.strip() for p, v in re.findall(r"\.(\w+)\((.*?)\)", body)}
            ffs[key] = dict(name=name, con=con)
            ff_name[name] = key
            q = con.get("q", "")
            qnet[re.sub(r"~q$", "", q.lstrip("\\").strip())] = key
            continue
        con = {p: v.strip() for p, v in re.findall(r"\.(data[abcd]|cin|combout|cout)\((.*?)\)", body)}
        mask = re.search(r"\.lut_mask = 16'h([0-9A-Fa-f]{4})", body) or re.search(r"lut_mask = 16'h([0-9A-Fa-f]{4})", body)
        mode = re.search(r"sum_lutc_input = \"(\w+)\"", body)
        lcs[key] = dict(name=name, mask=int(mask[1], 16) if mask else None, mode=mode[1] if mode else "datac", con=con)
        lc_name[name] = key
    return lcs, lc_name, ffs, ff_name, qnet


def parse_pin(path):
    out = {}
    for line in open(path):
        f = [s.strip() for s in line.split(":")]
        if len(f) >= 3 and f[2] in ("input", "output", "bidir"):
            out[f[0]] = (f[1], f[2])
    return out


def gt_producer(net, lc_name, ff_name, qnet, pins, lcs_=(), ffs_=()):
    """Producer tuple of a GT RCF net (by net name, else by its root element)."""
    nm = net["name"]
    if nm in lc_name:
        return ("LC",) + lc_name[nm]
    if nm in ff_name:
        return ("FF",) + ff_name[nm]
    if re.sub(r"~q$", "", nm) in qnet:
        return ("FF",) + qnet[re.sub(r"~q$", "", nm)]
    if nm.endswith("~input") and nm[:-6] in pins:
        return ("PAD", pins[nm[:-6]][0])
    if net["roots"]:
        r = net["roots"][0]
        if r[0] == "LE_BUFFER":                  # unnamed net: the buffer's LE is a LUT-only or a FF-only site -> that producer; both -> left as SRC
            k = (r[1], r[2], r[4] // 2)
            if (k in lcs_) != (k in ffs_):
                return ("LC" if k in lcs_ else "FF",) + k
        return ("SRC", r[0], r[1], r[2], r[3], r[4])
    return None


def score_design(cx, d, workers):
    t0 = time.time()
    from lifters.cycloneiv_clean import emit
    T = cx.T
    out = {c: counts() for c in CATS}
    scope = collections.defaultdict(collections.Counter)
    b = emit.Builder(cx, os.path.join(d, "bitstream.rbf"), os.path.basename(d), workers)
    nl = b.run()
    lcs, lc_name, ffs, ff_name, qnet = parse_gt(d)
    pins = parse_pin(os.path.join(d, "build.pin"))
    nets = T.parse_rcf(os.path.join(d, "routing.rcf"))
    # ---- luts
    mine = {(L["x"], L["y"], L["le"]): L for L in nl.luts}
    for k, G in lcs.items():
        L = mine.get(k)
        if L is None or G["mask"] is None:
            out["lut_site"]["missing"] += 1
            scope["lut_site"]["missing:not_emitted"] += 1
        elif L["init"] == G["mask"] and L["mode"] == G["mode"]:
            out["lut_site"]["matched"] += 1
        else:
            out["lut_site"]["wrong"] += 1
            scope["lut_site"]["wrong:" + ("init" if L["init"] != G["mask"] else "mode")] += 1
    out["lut_site"]["extra"] = sum(1 for k in mine if k not in lcs)
    # ---- lut pins
    gt_pin = {}
    for n in nets:
        prod = gt_producer(n, lc_name, ff_name, qnet, pins)
        for last, cell, port, rp in n["dests"]:
            if cell in lc_name and rp in PHYS:
                gt_pin[(lc_name[cell], PHYS[rp])] = (prod, n)
    for (k, gi), (prod, n) in gt_pin.items():
        L = mine.get(k)
        if L is None:
            out["lut_pin"]["missing"] += 1
            scope["lut_pin"]["missing:lut_not_emitted"] += 1
            continue
        if L["prod"][gi] is None:
            out["lut_pin"]["missing"] += 1
            scope["lut_pin"]["missing:pin_unconnected_or_undecoded"] += 1
        elif prod is not None and tuple(L["prod"][gi]) == tuple(prod):
            out["lut_pin"]["matched"] += 1
        elif L["prod"][gi][0] == "SRC" and (prod is None or prod[0] in ("PAD", "SRC")):
            out["lut_pin"]["missing"] += 1                     # undecoded source (clock buffer / dedicated clock pin / M9K): named, not mapped
            scope["lut_pin"]["missing:undecoded_source:" + L["prod"][gi][1]] += 1
        else:
            out["lut_pin"]["wrong"] += 1
            scope["lut_pin"]["wrong:%s->%s" % (L["prod"][gi][0], prod[0] if prod else None)] += 1
    for k, L in mine.items():
        if k in lcs:
            ex = sum(1 for gi in range(4) if L["prod"][gi] is not None and L["prod"][gi][0] != "CO" and (k, gi) not in gt_pin)
            out["lut_pin"]["extra"] += ex
            if ex:
                scope["lut_pin"]["extra:pin_connected_where_gt_not_routed"] += ex
        else:
            out["lut_pin"]["extra"] += sum(1 for gi in range(4) if L["prod"][gi] is not None)
    # ---- carry
    for k, G in lcs.items():
        ci = G["con"].get("cin", "gnd")
        if G["mode"] != "cin" or ci in ("gnd", "vcc", ""):
            continue
        src = [kk for kk, g in lcs.items() if g["con"].get("cout") == ci]
        L = mine.get(k)
        if L is None or L["cin"] is None:
            out["lut_carry"]["missing"] += 1
        elif src and L["cin"] == "co_%d_%d_%d" % src[0]:
            out["lut_carry"]["matched"] += 1
        else:
            out["lut_carry"]["wrong"] += 1
    # ---- ffs
    fm = {(F["x"], F["y"], F["le"]): F for F in nl.ffs}
    gt_clk = {}
    allnames = sorted({r for n in nets for r in n["roots"]})
    rec, why = cx.res.resolve(allnames)
    ridx = {n: i for i, n in enumerate(allnames)}
    for n in nets:
        for last, cell, port, rp in n["dests"]:
            if port == "CLK":
                gt_clk[cell] = {int(rec[ridx[r]]) for r in n["roots"] if rec[ridx[r]] >= 0}
    ctl_gt = collections.Counter()
    asdata_gt = {}
    for n in nets:
        for last, cell, port, rp in n["dests"]:
            if port == "ASDATA":
                asdata_gt[cell] = gt_producer(n, lc_name, ff_name, qnet, pins)
    for k, G in ffs.items():
        F = fm.get(k)
        if F is None:
            out["ff_site"]["missing"] += 1
            continue
        out["ff_site"]["matched"] += 1
        con = G["con"]
        for p, idle in (("ena", "vcc"), ("clrn", "vcc"), ("sclr", "gnd"), ("sload", "gnd"), ("aload", "gnd")):
            if con.get(p, idle) != idle:
                ctl_gt[p] += 1
        if con.get("clk", "").startswith("!"):
            ctl_gt["clk_inverted"] += 1
        roots = gt_clk.get(G["name"]) or gt_clk.get(re.sub(r"~q$", "", con.get("q", "").lstrip("\\").strip()))
        if F["clk_rec"] is None or not roots:
            out["ff_clock"]["missing"] += 1
            scope["ff_clock"]["missing:" + ("no_gt_root" if not roots else "no_emitted_clock")] += 1
        elif int(b.root(np.asarray([F["clk_rec"]]))[0]) in roots:
            out["ff_clock"]["matched"] += 1
        else:
            out["ff_clock"]["wrong"] += 1
        dn = con.get("d", "").lstrip("\\").strip()
        src = lc_name.get(re.sub(r"_combout$", "", dn).strip())
        asd = con.get("asdata", "").lstrip("\\").strip()
        asrc = lc_name.get(re.sub(r"_combout$", "", asd).strip()) if con.get("sload") == "vcc" else None
        if src == k:
            ok = F["d"] == "lc_%d_%d_%d" % k
        elif con.get("sload") == "vcc" and dn == "gnd":
            # FF-only LE: D = ASDATA; the net feeding it is named by the RCF dest ( ff, ASDATA ), producer compared like a LUT pin
            g = asdata_gt.get(G["name"]) or asdata_gt.get(re.sub(r"~q$", "", con.get("q", "").lstrip("\\").strip()))
            ok = F.get("d_prod") is not None and g is not None and tuple(F["d_prod"]) == tuple(g)
        else:
            ok = False
            scope["ff_d"]["missing:gt_d_other"] += 1
        if ok:
            out["ff_d"]["matched"] += 1
        else:
            out["ff_d"]["missing"] += 1
    out["ff_site"]["extra"] = sum(1 for k in fm if k not in ffs)
    # ---- io
    gt_ports = {}
    for port, (ball, dirn) in pins.items():
        gt_ports[ball] = (port, dirn)
    mine_io = {io["ball"]: io for io in nl.ios}
    out_net = {}
    for n in nets:
        for last, cell, port, rp in n["dests"]:
            if cell.endswith("~output") and port == "I":
                out_net[cell[:-7]] = gt_producer(n, lc_name, ff_name, qnet, pins, lcs, ffs)
    vo_ports = set(re.findall(r"^// (\S+)\t=>  Location: PIN_", open(os.path.join(d, "postfit.vo")).read(), re.M))
    for ball, (port, dirn) in gt_ports.items():
        if port not in vo_ports:
            continue
        io = mine_io.get(ball)
        if io is None or io["dir"] is None:
            out["io_dir"]["missing"] += 1
            scope["io_dir"]["missing:" + ("no_site" if io is None else "no_dir")] += 1
            continue
        if io["dir"] == DIRMAP[dirn]:
            out["io_dir"]["matched"] += 1
            if io.get("dir_source") == "routing":
                scope["io_dir"]["info:matched_direction_from_routing_only"] += 1
        else:
            out["io_dir"]["wrong"] += 1
            scope["io_dir"]["wrong:%s->%s" % (io["dir"], dirn)] += 1
        if dirn == "output":
            g = out_net.get(port)
            if io.get("drv") is None or g is None:
                out["io_data"]["missing"] += 1
                scope["io_data"]["missing:" + ("gt_driver_unknown" if g is None else "pad_row" if io["site"][0] == 5 else "col_pad_no_bim")] += 1
            elif tuple(io["drv_prod"]) == tuple(g):
                out["io_data"]["matched"] += 1
            elif io["drv_prod"][0] == "SRC" and g[0] in ("PAD", "SRC"):
                out["io_data"]["missing"] += 1                 # undecoded source named, not mapped (same rule as lut_pin)
                scope["io_data"]["missing:undecoded_source:" + io["drv_prod"][1]] += 1
            else:
                out["io_data"]["wrong"] += 1
                scope["io_data"]["wrong:%s->%s" % (io["drv_prod"][0], g[0])] += 1
    out["io_dir"]["extra"] = sum(1 for bl in mine_io if bl not in gt_ports or gt_ports[bl][0] not in vo_ports)
    return dict(design=os.path.basename(d), cats=out, scope={k: dict(v) for k, v in scope.items()}, gt_ff_ctl=dict(ctl_gt),
                gt_lcells=len(lcs), gt_ffs=len(ffs), emitted=emit.summary(nl)["luts"], seconds=round(time.time() - t0, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(REPO, "corpus", "cycloneiv"))
    ap.add_argument("--names", help="comma list of design directory names")
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
    from lifters.cycloneiv_clean import emit
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + a.workers * (heavy_guard.JOB_GB["cyc4_clean_gate_worker"] + 0.4)
    rows, t0 = [], time.time()
    with heavy_guard.lease(gb, "cyc4_clean_emit_check", log):
        cx = emit.Ctx()
        from lifters.cycloneiv_clean import tracer as T
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
                        log.info("%s %s %.1fs", r["design"], {c: r["cats"][c] for c in CATS if sum(r["cats"][c].values())}, r["seconds"])
                    except Exception as e:      # a design that cannot be scored is a result, not a skip
                        import traceback
                        log.error("%s: %s: %s\n%s", futs[f], type(e).__name__, e, traceback.format_exc())
                        r = dict(design=os.path.basename(futs[f]), error=f"{type(e).__name__}: {e}")
                    rows.append(r)
    good = [r for r in rows if "error" not in r]
    tot = {c: counts() for c in CATS}
    scope = collections.defaultdict(collections.Counter)
    for r in good:
        for c in CATS:
            for k, v in r["cats"][c].items():
                tot[c][k] += v
        for c, d in r["scope"].items():
            scope[c].update(d)
    log.info("DESIGNS %d / %d (errors %d) %.0fs", len(good), len(rows), len(rows) - len(good), time.time() - t0)
    for c in CATS:
        log.info("HEADLINE %-10s %6.2f%%  %s", c, headline(tot[c]), tot[c])
    for c, d in scope.items():
        log.info("scope %s: %s", c, dict(d.most_common(12)))
    ctl = collections.Counter()
    for r in good:
        ctl.update(r["gt_ff_ctl"])
    log.info("GT FF controls non-idle (not modelled): %s", dict(ctl))
    json.dump(dict(totals=tot, headline={c: round(headline(tot[c]), 3) for c in CATS}, scope={c: dict(d.most_common(40)) for c, d in scope.items()},
                   gt_ff_ctl=dict(ctl), rows=rows), open(os.path.join(OUT, f"emit_check_{a.tag}.json"), "w"), indent=0, default=str)


if __name__ == "__main__":
    main()
