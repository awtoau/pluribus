#!/usr/bin/env python3.15t
"""Pad role classifier for a recovered Cyclone IV clean-pipeline netlist: bus-like groups from structure only, #165.

  python3.15t scripts/cycloneiv_clean_pad_roles.py --nl NL.pkl [--tag image] [--depth 3] [--pkg F672]
Per used pad: direction, first-level sinks / driver leaves, clock domain (and edge) of the FFs it feeds or is fed from,
capture/launch FF kind (direct FF = registered), forward / backward sequential cone sizes, side (pad function DIFFIO_<T|B|L|R>).
Groups (`bus` = same direction, same clock-domain signature, same cone fingerprint, >= MIN_BUS pads):
  in_bus   inputs captured directly by FFs of one clock domain (and edge)
  out_bus  outputs launched by FFs / LUTs over the same domain set and the same backward cone sizes
  strobe   odd pads: single-FF capture with a large cone, outputs with a one-hot / toggling driver
Evidence tags are the caller's: this script only measures. Log tmp/logs/cycloneiv_clean_pad_roles.log, results tmp/dji_pads/<tag>.json.
Netlist is read-only; no decoder code is touched.
"""
import argparse
import collections
import importlib.util
import json
import logging
import os
import pickle
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_pad_roles.log")
OUT = os.path.join(REPO, "tmp", "dji_pads")
log = logging.getLogger("pad_roles")
MIN_BUS = 4         # decision: fewer than 4 pads with an identical signature is not called a bus
FF_EDGES = ("d", "ena", "sclr", "sload", "asdata")


def _net_class():
    spec = importlib.util.spec_from_file_location("spi_trace", os.path.join(REPO, "scripts", "cycloneiv_clean_spi_trace.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Net


class Graph:
    """Consumer map and cone helpers over a netlist (luts, ffs, m9k, mac)."""

    def __init__(self, nl):
        self.nl = nl
        self.net = _net_class()(nl)
        self.ff, self.lut = self.net.ff, self.net.lut
        self.cons = collections.defaultdict(list)       # signal -> [consumer name]  (FF consumers as ff.pin)
        for k, v in self.net.cons.items():
            self.cons[k] = list(v)
        for i, m in enumerate(nl.m9k):
            for f in ("data", "addr", "we", "be"):
                x = m.get(f)
                for s in (x if isinstance(x, list) else [x]):
                    if isinstance(s, str):
                        self.cons[s].append(f"m9k{i}.{f}")
        for i, m in enumerate(nl.mac):
            for f in ("a", "b"):
                for s in m.get(f) or []:
                    if isinstance(s, str):
                        self.cons[s].append(f"mac{i}.{f}")
        self._fb = {}

    def back_ffs(self, sig, hops):
        """{depth: FFs first reached at that FF stage} of the sequential cone of `sig`, up to `hops` stages."""
        out, seen, cur = {}, set(), {sig}
        for h in range(hops + 1):
            nxt, new = set(), set()
            for s in cur:
                for x in self.net.comb_leaves(s):
                    if x in self.ff and x not in seen:
                        seen.add(x)
                        new.add(x)
                        F = self.ff[x]
                        nxt |= {F[k] for k in FF_EDGES if F.get(k)}
            out[h] = new
            cur = nxt
            if not cur:
                break
        return out

    def fwd(self, sig, hops, cap=20000):
        """(first-level FF set, per-stage new-FF counts, M9K/MAC pins reached) forward from `sig` through LUTs and `hops` FF stages."""
        first, counts, other = set(), [], set()
        seen_ff, frontier = set(), {sig}
        for h in range(hops + 1):
            new, nxt, seenl = set(), set(), set()
            stack = list(frontier)
            while stack:
                s = stack.pop()
                for c in self.cons.get(s, ()):
                    if "." in c:
                        n = c.split(".")[0]
                        if n in self.ff:
                            if n not in seen_ff:
                                seen_ff.add(n)
                                new.add(n)
                        else:
                            other.add(c)
                    elif c in self.lut and c not in seenl:
                        rr = self.net.red(c)
                        if rr is not None and s not in rr[0]:
                            continue        # pin is a don't-care of the LUT function
                        seenl.add(c)
                        stack.append(c)
            if h == 0:
                first = set(new)
            counts.append(len(new))
            frontier = new
            if not new or len(seen_ff) > cap:
                break
        return first, counts, other


def clk_sig(g, ffs):
    """clock-domain signature of FFs: sorted {(clock net, 'neg'|'pos')}."""
    return sorted({(g.ff[f]["clk"], "neg" if g.ff[f].get("clk_inv") else "pos") for f in ffs if f in g.ff})


def pad_features(g, ios, depth, pad_fn=None):
    rows = []
    for io in ios:
        b = io["ball"]
        sig = "pad_" + b
        r = {"ball": b, "dir": io["dir"], "site": io["site"], "fn": (pad_fn or {}).get(b), "drv": io.get("drv")}
        side = None
        if r["fn"]:
            import re
            m = re.match(r"DIFFIO_([TBLR])\d+", r["fn"])
            side = m.group(1) if m else None
        r["side"] = side
        if io["dir"] in ("input", "bidir-or-tristate"):
            first, counts, other = g.fwd(sig, depth)
            r["in_first_ffs"] = sorted(first)
            r["in_direct_ff"] = sum(1 for f in first if g.ff[f].get("d") == sig)
            r["in_clk"] = clk_sig(g, first)
            r["in_cone"] = counts
            r["in_blocks"] = len(other)
            r["in_consumers"] = len(g.cons.get(sig, ()))
        if io["dir"] in ("output", "bidir-or-tristate") and io.get("drv"):
            d = io["drv"]
            back = g.back_ffs(d, depth)
            r["out_leaf_ffs"] = sorted(back.get(0, ()))
            r["out_clk0"] = clk_sig(g, back.get(0, ()))
            r["out_direct_ff"] = d in g.ff
            r["out_cone"] = [len(back.get(h, ())) for h in range(depth + 1)]
            r["out_lut_depth0"] = 0 if d in g.ff else 1
        rows.append(r)
    return rows


def group(rows):
    """bus-like groups: same dir class + clock signature + cone fingerprint."""
    groups = collections.defaultdict(list)
    for r in rows:
        if r["dir"] == "input":
            key = ("in", json.dumps(r["in_clk"]), r["in_direct_ff"] > 0, tuple(r["in_cone"][:2]))
        elif r["dir"] == "output":
            if "out_cone" not in r:
                key = ("out_const",)
            else:
                key = ("out", json.dumps(r["out_clk0"]), tuple(r["out_cone"][:3]))
        else:
            key = ("bidir", json.dumps(r.get("out_clk0")), json.dumps(r.get("in_clk")))
        groups[key].append(r["ball"])
    return groups


def classify(g, rows):
    """-> {ball: (role, detail)} from structure only.  Roles: const_out, phase_out, ctl_out, through_in, through_out, rx_capture,
    strobe_in, nosink_in, bidir_bus, other_in, other_out.  All are structural facts; naming them (AD9363, FX3, ...) is the caller's inference."""
    roles = {}
    out_leaves = {r["ball"]: g.net.comb_leaves(r["drv"]) for r in rows if r["dir"] == "output" and r.get("drv")}
    pad_to_out = collections.defaultdict(list)
    for b, lv in out_leaves.items():
        for x in lv:
            if x.startswith("pad_"):
                pad_to_out[x[4:]].append(b)
    for r in rows:
        b, d = r["ball"], r["dir"]
        if d == "output":
            if not r.get("drv"):
                roles[b] = ("const_out", "no driver")
                continue
            lv = out_leaves[b]
            ffs = [x for x in lv if x in g.ff]
            neg = [x for x in ffs if g.ff[x].get("clk_inv")]
            pos = [x for x in ffs if not g.ff[x].get("clk_inv")]
            pair = [(p_, n_) for n_ in neg for p_ in pos if g.ff[n_]["d"] == p_ and g.ff[n_]["clk"] == g.ff[p_]["clk"]]
            if pair:
                roles[b] = ("phase_out", f"pos/neg FF pair on {pair[0][0]} clock {g.ff[pair[0][0]]['clk']}")
            elif any(x.startswith("pad_") for x in lv):
                roles[b] = ("through_out", "combinational path from pad " + ",".join(x[4:] for x in lv if x.startswith("pad_")))
            elif ffs and any(g.ff[x].get("ena") and g.ff[g.ff[x]["d"]]["name"] in g.ff for x in ffs if g.ff[x]["d"] in g.ff):
                roles[b] = ("ctl_out", "driver mixes register-loaded FFs (enable + FF source)")
            else:
                roles[b] = ("other_out", "")
        elif d == "input":
            nff = len(r["in_first_ffs"])
            if r["in_consumers"] == 0:
                roles[b] = ("nosink_in", "no consumer in the netlist")
            elif b in pad_to_out:
                roles[b] = ("through_in", "pad in the driver cone of " + ",".join(pad_to_out[b]))
            elif nff >= 4 and sum(1 for f in r["in_first_ffs"] if f in g.net.cons.get(g.ff[f]["d"], []) or f in g.net.comb_leaves(g.ff[f]["d"])) >= nff - 1:
                roles[b] = ("strobe_in", f"{nff} hold FFs (next state depends on own output)")
            elif nff == 1 and not [c for c in g.cons.get(r["in_first_ffs"][0], ())]:
                roles[b] = ("rx_capture", "single capture FF, output unused in the netlist, clock " + str(r["in_clk"]))
            else:
                roles[b] = ("other_in", f"{nff} first-level FFs, cone {r['in_cone']}")
        else:
            roles[b] = ("bidir_bus", "")
    return roles


def m9k_taps(g, sig, hops=3):
    """[(M9K output signal, FF stage)] in the sequential D-cone of `sig` within `hops` FF stages; M9K read data leaves look like m9k_<x>_<y>_q[<n>]."""
    out, seen, cur = [], set(), {sig}
    for h in range(hops + 1):
        nxt = set()
        for s_ in cur:
            for x in g.net.comb_leaves(s_):
                if x in g.ff:
                    if x not in seen:
                        seen.add(x)
                        nxt.add(g.ff[x]["d"])
                elif x.startswith("m9k_"):
                    out.append((x, h))
        cur = nxt
    return out


def word_lanes(g, rows, roles):
    """phase_out pads: M9K read bits feeding each pad.  Returns {ball: {m9k: [bit numbers]}} and the lane stride per M9K (gcd of bit-number gaps).
    One pad taking k bits spaced by the stride of one M9K = k time-multiplexed words (k = word count per frame)."""
    import math
    import re
    res = {}
    for r in rows:
        if roles.get(r["ball"], ("",))[0] != "phase_out":
            continue
        by = collections.defaultdict(set)
        for x, _h in m9k_taps(g, r["drv"]):
            m = re.match(r"(m9k_\d+_\d+)_q\[(\d+)\]", x)
            if m:
                by[m.group(1)].add(int(m.group(2)))
        res[r["ball"]] = {k: sorted(v) for k, v in by.items()}
    stride = {}
    for lanes in res.values():
        for k, v in lanes.items():
            if len(v) > 1:
                stride[k] = math.gcd(*[b - a for a, b in zip(v, v[1:])])
    return res, stride


def run(nl, depth, pad_fn=None):
    g = Graph(nl)
    rows = pad_features(g, nl.ios, depth, pad_fn)
    groups = group(rows)
    return g, rows, groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", required=True)
    ap.add_argument("--tag", default="image")
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--pkg", default="F672", help="package whose pad table gives pad functions (balls of the netlist)")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, "w"), logging.StreamHandler()])
    nl = pickle.load(open(a.nl, "rb"))
    pad_fn = None
    try:
        from lifters.cycloneiv_clean import pkgpad as K
        pads = K.pads()
        pad_fn = {}
        for i, j in K.pin_pad(K.pins({"F672": 672, "F896": 896, "F484": 484}[a.pkg])).items():
            pad_fn[K.pins({"F672": 672, "F896": 896, "F484": 484}[a.pkg])[i]["strs"][0]] = pads[j]["strs"][4]
    except Exception as e:  # pad functions are optional
        log.info("pad functions unavailable: %s", e)
    g, rows, groups = run(nl, a.depth, pad_fn)
    log.info("pads %d: %s", len(rows), dict(collections.Counter(r["dir"] for r in rows)))
    for key, balls in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        kind = "bus" if len(balls) >= MIN_BUS else "small"
        log.info("[%s] %d pads %s: %s", kind, len(balls), key, " ".join(sorted(balls)))
    roles = classify(g, rows)
    bycls = collections.defaultdict(list)
    for b, (ro, de) in roles.items():
        bycls[ro].append(b)
    for ro, bs in sorted(bycls.items(), key=lambda kv: -len(kv[1])):
        log.info("role %s (%d): %s", ro, len(bs), " ".join(sorted(bs)))
    lanes, stride = word_lanes(g, rows, roles)
    log.info("phase_out word lanes: stride per M9K %s", stride)
    for b in sorted(lanes):
        log.info("  lane %s: %s", b, {k: [v_ % stride[k] if k in stride else v_ for v_ in vs][:1] + [len(vs)] for k, vs in lanes[b].items()})
    json.dump({"lanes": lanes, "stride": stride, "roles": roles, "rows": rows, "groups": [{"key": list(k), "balls": v} for k, v in groups.items()]}, open(os.path.join(OUT, a.tag + ".json"), "w"), indent=1, default=list)
    log.info("done")


if __name__ == "__main__":
    main()
