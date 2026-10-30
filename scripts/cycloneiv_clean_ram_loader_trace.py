#!/usr/bin/env python3.15t
"""Who loads / uses the run-time RAM formed by two M9K tiles, and what its content is (#165).  Structure only.

  python3.15t scripts/cycloneiv_clean_ram_loader_trace.py --nl NL.pkl [--tiles 7_85,7_86] [--pad AF3] [--base 256] [--fw FILE ...]
Per tile pair (one 32-bit word = 18 + 14 data wires, both ports):
  ports     pin groups (addr / data / clk / we) with the clock domain of their cone leaves: serial side vs engine side
  serial    clock domain of the address counter: crossings in (FFs outside the domain, undecoded sources, M9K), consumers out,
            counter (shift-load chain, increment), data chain (RAM-out load / neighbour shift, serial-in source), constant address bits
  engine    domain of the other port: pad pin (drive FF, OE LUT, sample FF), sclr counters and carry chains, consumers out
  content   words from --base; the stored 32-bit words are matched to the SHA-1 IV / round constants by solving the wire permutation
  fw        --fw images: SHA-1 IV / K present in either byte order (present/absent only, no offsets)
Evidence tags V (traced / compared here) in the log.  Netlist read-only.  Log tmp/logs/cycloneiv_clean_ram_loader_trace.log, JSON tmp/dji_ram/<tiles>.json.
"""
import argparse
import collections
import json
import logging
import os
import pickle
import struct
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_ram_loader_trace.log")
OUT = os.path.join(REPO, "tmp", "dji_ram")
log = logging.getLogger("ram_loader")
CONST = ("1'", "0'")
SHA1_IV = (0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0)
SHA1_K = (0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xCA62C1D6)


def solve_wire_map(words_a, words_b, targets, wa=18, wb=18):
    """For each target bit j (0..31) the physical bit positions (tile A bits 0..wa-1, then tile B bits) whose column equals the target column over all words.
    -> {j: [positions]}; a position is reported once per bit even when two columns are identical."""
    cols = [[(w >> k) & 1 for w in words_a] + [] for k in range(wa)]
    cols += [[(w >> k) & 1 for w in words_b] for k in range(wb)]
    res = {}
    for j in range(32):
        t = [(x >> j) & 1 for x in targets]
        res[j] = [p for p, c in enumerate(cols) if c == t]
    return res


def sha1_match(words_a, words_b, base=0):
    """Compare the nine words at base.. with SHA-1 H0..H4, K0..K3.  -> (bits found uniquely, bits found ambiguously, bits missing, map)."""
    tg = SHA1_IV + SHA1_K
    a, b = words_a[base:base + len(tg)], words_b[base:base + len(tg)]
    m = solve_wire_map(a, b, tg)
    uniq = sum(1 for v in m.values() if len(v) == 1)
    amb = sum(1 for v in m.values() if len(v) > 1)
    miss = sum(1 for v in m.values() if not v)
    return uniq, amb, miss, m


def lut_deps(init, npins=4):
    """Pin indexes a 4-input LUT truth table depends on."""
    return [i for i in range(npins) if any(((init >> x) & 1) != ((init >> (x ^ (1 << i))) & 1) for x in range(1 << npins))]


class G:
    def __init__(self, nl):
        self.nl = nl
        self.lut = {l["name"]: l for l in nl.luts}
        self.ff = {f["name"]: f for f in nl.ffs}
        self.m9k = {f"m9k_{m['x']}_{m['y']}": m for m in nl.m9k}
        self.cons = collections.defaultdict(list)
        for l in nl.luts:
            for p in l["pins"] + ([l["cin"]] if l.get("cin") else []):
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

    def srcs(self, x):
        if x in self.lut:
            L = self.lut[x]
            return L["pins"] + ([L["cin"]] if L.get("cin") else [])
        if x in self.ff:
            return [self.ff[x][k] for k in ("d", "ena", "aclr", "sclr", "sload", "asdata") if self.ff[x].get(k)]
        if x.startswith("co_"):
            return ["lc_" + x[3:]]
        return []

    def back_leaves(self, sigs, depth):
        """Leaves (non-LUT/FF signals) and FF clock domains reached backwards within `depth` FF/LUT stages."""
        seen, fr, leaves, clks = set(), [s for s in sigs if s and not s.startswith(CONST)], collections.Counter(), collections.Counter()
        for _ in range(depth):
            nx = []
            for x in fr:
                if x in seen:
                    continue
                seen.add(x)
                if x in self.ff:
                    clks[self.ff[x]["clk"]] += 1
                if x in self.lut or x in self.ff or x.startswith("co_"):
                    nx += [s for s in self.srcs(x) if s and not s.startswith(CONST)]
                else:
                    leaves[x.split("_o[")[0] if x.startswith("m9k_") else x] += 1
            fr = nx
        return leaves, clks

    def fwd_kinds(self, starts, domain=None, depth=6):
        """Sink kinds of the signals (through LUTs; FFs followed too) within `depth` stages; FFs outside `domain` counted by clock."""
        seen, fr, kinds = set(starts), list(starts), collections.Counter()
        for _ in range(depth):
            nx = []
            for s in fr:
                for c, k in self.cons.get(s, ()):
                    if c in seen:
                        continue
                    seen.add(c)
                    if c.startswith(("pad_", "mac_")):
                        kinds[c] += 1
                    elif c.startswith("m9k_"):
                        kinds[f"{c}.{k}"] += 1
                    else:
                        if c in self.ff and domain is not None and self.ff[c]["clk"] != domain:
                            kinds["ff@" + self.ff[c]["clk"]] += 1
                        nx.append(c)
                        if c in self.lut:
                            nx.append("co_" + c[3:])
            fr = nx
        return kinds


def domain_io(g, dom_clk, tile_names):
    """Signals entering / leaving the FF set of one clock: sources outside it (FFs of other clocks, non-FF leaves), sinks outside it."""
    dom = {n for n, f in g.ff.items() if f["clk"] == dom_clk}
    cross, ext = collections.Counter(), collections.Counter()
    for n in dom:
        seen, st = set(), [n]
        first = True
        while st:
            x = st.pop()
            for k in (g.srcs(x) if x != n or first else []):
                first = False
                if k in seen or k.startswith(CONST) or not k:
                    continue
                seen.add(k)
                if k in g.ff:
                    if k not in dom:
                        cross[(k, g.ff[k]["clk"])] += 1
                elif k in g.lut or k.startswith("co_"):
                    st.append(k if k in g.lut else "lc_" + k[3:])
                else:
                    ext[k.split("_o[")[0] if k.startswith("m9k_") else k] += 1
    out = collections.Counter()
    for n in dom:
        seen = set()

        def walk(sig):
            for c, k in g.cons.get(sig, ()):
                if c in seen:
                    continue
                seen.add(c)
                if c in g.ff:
                    if c not in dom:
                        out["ff@" + g.ff[c]["clk"]] += 1
                elif c in g.lut:
                    walk(c)
                    walk("co_" + c[3:])
                elif c.startswith("m9k_"):
                    out[c] += 1
                else:
                    out[c.split("_")[0]] += 1
        walk(n)
    return dom, cross, ext, out


def analyse(nl, tiles, pad, base):
    g = G(nl)
    ta, tb = (g.m9k["m9k_" + t] for t in tiles)
    res = {"tiles": tiles}
    # ports
    groups = {"addr": ta["addr"], "addr_b": ta["addr_b"], "data": ta["data"], "data_b": ta["data_b"], "we": [ta["we"]], "we_b": [ta["we_b"]]}
    res["pin_clocks"] = {}
    for k, v in groups.items():
        leaves, clks = g.back_leaves(v, 3)
        res["pin_clocks"][k] = dict(clks.most_common(3))
        log.info("[V] ports %s: FF clocks within 3 stages %s", k, dict(clks.most_common(3)))
    log.info("[V] tile B shares addr / addr_b / we / we_b nets with tile A: %s", all(ta[k] == tb[k] for k in ("addr", "addr_b", "we", "we_b")))
    log.info("[V] address bit 8 tied: addr %s addr_b %s (word address = 256 + 8-bit value on both ports)", ta["addr"][8], ta["addr_b"][8])
    # serial side = clock of the counter FFs on addr_b
    ctr = [s for s in ta["addr_b"] if s in g.ff]
    sclk = g.ff[ctr[0]]["clk"]
    dom, cross, ext, out = domain_io(g, sclk, tiles)
    res["serial"] = {"clk": sclk, "ffs": len(dom), "cross_in_ffs": [list(k) for k in cross], "ext_in": dict(ext), "out": dict(out)}
    log.info("[V] serial side clock %s: %d FFs; inputs from other-clock FFs %s; other sources %s", sclk, len(dom), [(k[0], k[1][-9:]) for k in cross], dict(ext))
    log.info("[V] serial side outputs (consumers outside the domain): %s", dict(out))
    c0 = g.ff[ctr[0]]
    log.info("[V] address counter %d FFs: ena %s sload %s aclr %s; shift link bit i <- bit i+1, top bit asdata %s (serial in); increment = carry chain d", len(ctr), c0["ena"], c0["sload"], c0.get("aclr"), g.ff[ctr[-1]]["asdata"])
    chain = [s for s in ta["data_b"] + tb["data_b"] if s in g.ff]
    cs = set(chain)
    sel, ena, load_bits = collections.Counter(), collections.Counter(), 0
    for s in chain:
        f = g.ff[s]
        L = g.lut[f["d"]]
        ena[f["ena"]] += 1
        ps = L["pins"]
        load_bits += sum(1 for p in ps if p.startswith("m9k_"))
        sel.update(p for p in ps if p not in cs and not p.startswith(CONST) and not p.startswith("m9k_"))
    serial_in = [p for s in chain for p in g.lut[g.ff[s]["d"]]["pins"] if p.startswith("u_")]
    log.info("[V] data chain %d FFs (write data of both tiles): one enable %s; each D = LUT of (RAM read bit, neighbour chain FF, shared select %s); %d RAM-read loads; serial-in source %s", len(chain), dict(ena), [k for k, v in sel.items() if v >= len(chain) // 2][:2], load_bits, sorted(set(serial_in)))
    log.info("[V] members: counter %s", " ".join(ctr))
    log.info("[V] members: data chain %s", " ".join(chain))
    res["serial"].update(counter=len(ctr), chain=len(chain), serial_in=sorted(set(serial_in)), count_sel=dict(sel.most_common(3)))
    # engine side
    eclk = ta["clk"]
    edom, ecross, eext, eout = domain_io(g, eclk, tiles)
    res["engine"] = {"clk": eclk, "ffs": len(edom), "cross_in_ffs": [list(k) for k in ecross], "ext_in": dict(eext), "out": dict(eout)}
    log.info("[V] engine clock %s: %d FFs; inputs from other-clock FFs %s; other sources %s; outputs %s", eclk, len(edom), [(k[0], k[1][-9:]) for k in ecross], dict(eext), dict(eout))
    io = next(i for i in nl.ios if i["ball"] == pad)
    drv, oe = io["drv"], io.get("oe")
    log.info("[V] pad %s dir %s, drive FF %s (clk %s), OE %s", pad, io["dir"], drv, g.ff[drv]["clk"] if drv in g.ff else None, oe)
    log.info("[V] members: engine pad path pad_%s %s %s", pad, drv, oe)
    smp = [c for c, k in g.cons.get("pad_" + pad, ()) if c in g.ff]
    log.info("[V] pad %s sampled by FF %s; also LUT sinks %s", pad, smp, [c for c, k in g.cons.get("pad_" + pad, ()) if c in g.lut])
    for n in (drv, oe):
        if n in g.lut:
            L = g.lut[n]
            log.info("[V] %s init %04x pins %s depends on pins %s", n, L["init"], L["pins"], lut_deps(L["init"]))
    # drive LUT chain: drv FF -> lut; OE lut
    dl = g.lut[g.ff[drv]["d"]] if drv in g.ff else None
    if dl:
        log.info("[V] drive FF D = LUT %s init %04x pins %s depends %s (constant-1 pins dropped)", dl["name"], dl["init"], dl["pins"], lut_deps(dl["init"]))
    sclr = collections.Counter(f["sclr"] for n, f in g.ff.items() if n in edom and f.get("sclr"))
    cin = {n for n in edom if g.lut.get(g.ff[n]["d"], {}).get("mode") == "cin"}
    lens = collections.Counter()
    for n in cin:
        x, ln = g.ff[n]["d"], 0
        while x in g.lut and g.lut[x].get("cin"):
            ln += 1
            c = g.lut[x]["cin"]
            x = "lc_" + c[3:] if c.startswith("co_") else c
        lens[ln] += 1
    clr_ffs = {n for n, f in g.ff.items() if n in edom and f.get("sclr") == sclr.most_common(1)[0][0]} if sclr else set()
    log.info("[V] engine counters: %d FFs with sync clear by one net %s; %d FFs fed directly by a carry LE, longest carry chain behind them %d LEs", len(clr_ffs), sclr.most_common(1), len(cin), max(lens) if lens else 0)
    res["engine"].update(pad_dir=io["dir"], sample_ffs=smp, sclr_counter_ffs=len(clr_ffs), carry_depths=dict(lens))
    # AF3 -> address distance (FF stages)
    seen, fr, dist = {"pad_" + pad}, ["pad_" + pad], None
    ap = {s for s in ta["addr"] if s and not s.startswith(CONST)} | {ta["we_b"]}
    stages = 0
    while fr and dist is None and stages < 12:
        nx = []
        for s in fr:
            for c, k in g.cons.get(s, ()):
                if c in seen:
                    continue
                seen.add(c)
                if c in ap:
                    dist = stages
                nx.append(c)
                if c in g.lut:
                    nx.append("co_" + c[3:])
        fr = nx
        stages += 1
    log.info("[V] pad %s reaches an engine-side address / write-enable LUT after %s LUT/FF hops (sampled first)", pad, dist)
    res["engine"]["pad_to_addr_hops"] = dist
    # content
    from lifters.cycloneiv_clean import m9k

    words = []
    for t in (ta, tb):
        r = m9k.read_words(np.asarray(t["content"]), 18)
        words.append([int("".join(str(int(b)) for b in row[::-1]), 2) for row in r])
    wa, wb = words
    u, a, mi, m = sha1_match(wa, wb, base)
    log.info("[V] words %d..%d vs SHA-1 H0..H4, K0..K3: of 32 word bits, %d found in exactly one wire column, %d in several, %d not found", base, base + 8, u, a, mi)
    res["sha1"] = {"unique": u, "ambiguous": a, "missing": mi, "map": {str(j): v for j, v in m.items()}}
    inv = {}
    for j, v in m.items():
        if len(v) == 1:
            inv[v[0]] = j
    log.info("[V] wire map (physical bit -> word bit, unique ones; A = first tile 0..17, B = second tile 18..35): %s", dict(sorted(inv.items())))
    nz = [i for i, w in enumerate(wa) if w and i >= base + 9]
    hi = [i for i, w in enumerate(wb) if w and i >= base + 10]
    log.info("[V] tile A non-zero words beyond the constants: %d in %d..%d; tile B: %d; all with word bits 16..31 zero: %s", len(nz), nz[0] if nz else -1, nz[-1] if nz else -1, len(hi), all((wa[i] & 0x3FFFF & ~0xFFFF) == 0 for i in nz) and not hi)
    ops = collections.Counter((wa[i] >> 12) & 0xF for i in nz)
    log.info("[V] program words: top nibble histogram %s", dict(sorted(ops.items())))
    res["program"] = {"words": len(nz), "span": [nz[0], nz[-1]] if nz else None, "top_nibble": dict(sorted(ops.items()))}
    return res


def fw_scan(paths):
    out = {}
    for p in paths:
        d = open(p, "rb").read()
        r = {}
        for nm, vals in (("IV", SHA1_IV), ("K", SHA1_K)):
            for en, fmt in (("le", "<I"), ("be", ">I")):
                r[nm + en] = d.find(b"".join(struct.pack(fmt, x) for x in vals)) >= 0
        out[os.path.basename(p)] = r
        log.info("[V] firmware %s (%d bytes): SHA-1 IV/K sequences present %s", os.path.basename(p), len(d), {k: v for k, v in r.items()})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", required=True)
    ap.add_argument("--tiles", default="7_85,7_86")
    ap.add_argument("--pad", default="AF3")
    ap.add_argument("--base", type=int, default=256)
    ap.add_argument("--fw", nargs="*", default=[])
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, "w"), logging.StreamHandler()])
    nl = pickle.load(open(a.nl, "rb"))
    res = analyse(nl, a.tiles.split(","), a.pad, a.base)
    if a.fw:
        res["fw"] = fw_scan(a.fw)
    json.dump(res, open(os.path.join(OUT, a.tiles.replace(",", "+") + ".json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
