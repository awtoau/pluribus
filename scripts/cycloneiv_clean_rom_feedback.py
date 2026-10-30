#!/usr/bin/env python3.15t
"""Does an M9K's data reach its own (or any M9K's) address / write-enable cone?  Sequencer-vs-table test on a recovered netlist (#165).

  python3.15t scripts/cycloneiv_clean_rom_feedback.py --nl NL.pkl --tiles 7_85,94_57 [--depth 12] [--fwd 6]
Per tile (annotation name x_y), structure only:
  addr cone   leaves (M9K outputs, pads, clock-like sources) reached backwards through LUT/FF inputs within --depth stages, per port
  feedback    M9K output bits in an address / write-enable cone = ROM data can steer its own address (jump / data-dependent next address)
  fanout      sink kinds of the output bits within --fwd stages (M9K read address / data / enable pins, MAC, pads)
No address cone with an M9K output = pure table (address from counters / registers).  Netlist read-only.  Log tmp/logs/cycloneiv_clean_rom_feedback.log
"""
import argparse
import collections
import logging
import os
import pickle
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_rom_feedback.log")
log = logging.getLogger("rom_feedback")
CONST = ("1'", "0'")


class G:
    def __init__(self, nl):
        self.lut = {l["name"]: l for l in nl.luts}
        self.ff = {f["name"]: f for f in nl.ffs}
        self.m9k = {f"m9k_{m['x']}_{m['y']}": m for m in nl.m9k}
        self.cons = collections.defaultdict(list)
        for l in nl.luts:
            for p in l["pins"]:
                self.cons[p].append((l["name"], "pin"))
        for f in nl.ffs:
            for k in ("d", "ena", "aclr", "sclr", "sload", "asdata"):
                if f.get(k):
                    self.cons[f[k]].append((f["name"], k))
        for io in nl.ios:
            if io.get("drv"):
                self.cons[io["drv"]].append(("pad_" + io["ball"], "drv"))
        for n, m in self.m9k.items():
            for k in ("data", "data_b", "addr", "addr_b", "raddr"):
                for s in m.get(k) or []:
                    self.cons[s].append((n, k))
            for k in ("we", "we_b", "ce", "ce_b"):
                if m.get(k):
                    self.cons[m[k].lstrip("!")].append((n, k))
        for mm in nl.mac:
            for s in mm["a"] + mm["b"]:
                self.cons[s].append((f"mac_{mm['x']}_{mm['y']}", "in"))

    def back(self, sigs, depth):
        seen, fr, res = set(), [s for s in sigs if s and not s.startswith(CONST)], collections.Counter()
        for _ in range(depth):
            nx = []
            for x in fr:
                if x in seen:
                    continue
                seen.add(x)
                if x.startswith("m9k_"):
                    res[x.split("_o[")[0]] += 1
                elif x.startswith(("pad_", "u_")):
                    res[x] += 1
                elif x in self.lut:
                    L = self.lut[x]
                    nx += L["pins"] + ([L["cin"]] if L.get("cin") else [])
                elif x in self.ff:
                    nx += [self.ff[x][k] for k in ("d", "ena", "aclr", "sclr", "sload", "asdata") if self.ff[x].get(k)]
                elif x.startswith("co_"):
                    nx.append("lc_" + x[3:])
            fr = [y for y in nx if y and not y.startswith(CONST)]
        return res

    def fwd(self, sigs, depth):
        seen, fr, res = set(sigs), list(sigs), collections.Counter()
        for d in range(depth):
            nx = []
            for s in fr:
                for c, k in self.cons.get(s, ()):
                    if c.startswith(("m9k_", "mac_", "pad_")):
                        res[(c.split("_")[0], k, d + 1)] += 1
                    elif c not in seen:
                        seen.add(c)
                        nx.append(c)
            fr = nx
        return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", required=True)
    ap.add_argument("--tiles", required=True)
    ap.add_argument("--depth", type=int, default=12)
    ap.add_argument("--fwd", type=int, default=6)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
    g = G(pickle.load(open(a.nl, "rb")))
    for t in a.tiles.split(","):
        n = "m9k_" + t
        m = g.m9k[n]
        ports = {"addr": m.get("addr") or [], "addr_b": m.get("addr_b") or [], "raddr": m.get("raddr") or [],
                 "we": [m["we"].lstrip("!")] if m.get("we") else [], "we_b": [m["we_b"]] if m.get("we_b") else []}
        for pn, sigs in ports.items():
            if not sigs:
                continue
            r = g.back(sigs, a.depth)
            fb = {k: v for k, v in r.items() if k.startswith("m9k_")}
            log.info("%s %-7s %2d pins; M9K outputs in cone: %s; pads: %s", t, pn, len(sigs), sorted(fb.items()) or "none", sorted(k for k in r if k.startswith("pad_")))
        outs = [f"{n}_o[{i}]" for i in range(36) if f"{n}_o[{i}]" in g.cons]
        log.info("%s fanout (kind, pin, stage): %s", t, sorted(g.fwd(outs, a.fwd).items()))


if __name__ == "__main__":
    main()
