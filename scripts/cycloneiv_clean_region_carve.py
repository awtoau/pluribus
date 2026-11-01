#!/usr/bin/env python3.15t
"""Carve an unknown partition blob (e.g. 802.16-rx / 802.16-tx) into 50-800-LUT regions and write one dense fact sheet per region (#189 step 1).

  python3.15t scripts/cycloneiv_clean_region_carve.py --nl tmp/image_sim_dji_push/nl.pkl --blob 802.16-rx [--blob 802.16-tx]
Deterministic, no LLM.  Inputs: tmp/cycloneiv_clean/partition.json (scripts/cycloneiv_clean_partition.py), boards/dji-m2001/blocks.json,
patterns.detect() (cached tmp/cycloneiv_clean/regions/patterns.json).  Outputs tmp/cycloneiv_clean/regions/<blob>/{index.json, rNNNN.json, rNNNN.md}.
Log tmp/logs/cycloneiv_clean_region_carve.log.
Carve: anchors first (LFSR/CRC groups > M9K groups sharing an address bus > MAC chains > carry chains + their registers > FF groups sharing an
enable), each absorbs exclusive drivers/consumers (2 passes); the rest joins the anchor reaching it first by multi-source BFS on comb edges
(GROW_ROUNDS), never through another anchor; leftovers = connected components.  Small regions merge into their strongest neighbour, >800-LUT
regions are cut into LAB-ordered chunks.
"""
import argparse
import collections
import json
import logging
import os
import pickle
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "regions")
log = logging.getLogger("region_carve")

MAX_LUT = 800
MIN_LUT = 50              # decision: regions under this many LUTs (no M9K/MAC/LFSR anchor) carry too little to name alone -> merged
GROW_ROUNDS = 8           # decision: BFS rounds from anchors; cells further than 8 comb hops from any anchor become leftover components
REG_MIN, REG_MAX = 4, 256  # FF enable groups treated as register anchors
CONE_MAX = 6


def cid(c):
    return c if isinstance(c, str) else f"{c[0]}_{c[1]}_{c[2]}"


def xy_of(P, c):
    if isinstance(c, tuple):
        return (c[1], c[2])
    r = P.lut.get(c) or P.ff.get(c)
    return (r["x"], r["y"])


# ---------------------------------------------------------------------------------------------------------------------------- M9K content shape
def berlekamp_massey(bits):
    n = len(bits)
    c, b = [1] + [0] * n, [1] + [0] * n
    L, m = 0, -1
    for i in range(n):
        d = bits[i]
        for j in range(1, L + 1):
            d ^= c[j] & bits[i - j]
        if d:
            t = c[:]
            for j in range(n - i + m):
                if b[j]:
                    c[j + i - m] ^= 1
            if 2 * L <= i:
                L, m, b = i + 1 - L, i, t
    return L, [j for j in range(L + 1) if c[j]]


def bitrev(i, n):
    return int(format(i, f"0{n}b")[::-1], 2)


def signed(v, w):
    return v - (1 << w) if v >> (w - 1) & 1 else v


def shape_tests(words, W, A):
    """Shape of an M9K init image; returns a list of short findings."""
    n = len(words)
    if not any(words):
        return ["all-zero init (RAM, not ROM)"]
    out = []
    distinct = len(set(words))
    out.append(f"{distinct} distinct values of {n}")
    if distinct == 1:
        return out + [f"constant 0x{words[0]:X}"]
    lo, used = 0, n
    while used > 1 and words[used - 1] == 0:
        used -= 1
    while lo < used - 1 and words[lo] == 0:
        lo += 1
    if lo or used < n:
        out.append(f"non-zero span words {lo}..{used - 1} (rest 0)")
    span = words[lo:used]
    if all(span[i] == bitrev(lo + i, A) for i in range(len(span))):
        out.append(f"bit-reversal permutation over {A} address bits")
    views = []
    for f in (W, 18, 16, 12, 9, 8, 6, 4):
        if f > W or W % f or (f != W and f < 4):
            continue
        for j in range(W // f):
            nm = "word" if f == W else f"field[{j * f + f - 1}:{j * f}]"
            views.append((nm, f, [(v >> (j * f)) & ((1 << f) - 1) for v in span]))
    seen = set()
    for name, w, raw in views:
        key = tuple(raw)
        if key in seen or len(set(raw)) < 3:
            continue
        seen.add(key)
        for sg in (False, True):
            x = np.array([signed(v, w) if sg else v for v in raw], dtype=float)
            tag = f"{name} ({w}b {'signed' if sg else 'unsigned'})"
            d = np.diff(x)
            if len(x) >= 16 and (np.all(d >= 0) or np.all(d <= 0)):
                t = np.linspace(0, 1, len(x))
                y = (x - x.min()) / np.ptp(x)
                if d[0] < 0 or (np.all(d <= 0) and not np.all(d >= 0)):
                    y = 1 - y
                fits = {"linear": t, "quarter-sine": np.sin(np.pi / 2 * t), "sqrt": np.sqrt(t), "log2(1+x)": np.log2(1 + t),
                        "x^2": t ** 2, "exp": np.expm1(t * 3) / np.expm1(3), "atan": np.arctan(t * 4) / np.arctan(4), "1-cos": 1 - np.cos(np.pi / 2 * t)}
                best = min(fits.items(), key=lambda kv: float(np.max(np.abs(kv[1] - y))))
                err = float(np.max(np.abs(best[1] - y)))
                shape = f"shape {best[0]} (max err {100 * err:.1f}%)" if err < 0.05 else "no simple shape"
                out.append(f"{tag}: monotone {x[0]:.0f}->{x[-1]:.0f} over {len(x)} words, {len(set(raw))} distinct, {shape}")
                break
            if len(x) >= 16 and np.ptp(x) > 0:
                p = np.abs(np.fft.rfft(x - x.mean())) ** 2
                k = int(np.argmax(p[1:]) + 1)
                frac = p[k] / p[1:].sum()
                if frac > 0.85:
                    out.append(f"{tag}: single tone {k} cycles / {len(x)} words -> period {len(x) / k:.1f}, amplitude {np.ptp(x) / 2:.0f}, power {frac:.3f}")
                    break
    out = out[:10]
    for b in range(min(W, 36)):
        col = [(v >> b) & 1 for v in words[:used]]
        if 0 < sum(col) < len(col) and len(col) >= 64:
            L, taps = berlekamp_massey(col)
            if L <= 32 and L * 4 <= len(col):
                out.append(f"bit {b}: LFSR sequence, linear complexity {L}, connection poly taps {taps}")
    m = max(words).bit_length()
    if 3 <= m <= 16 and used >= (1 << m) - 1:
        seq = words[:(1 << m) - 1]
        if sorted(seq) == list(range(1, 1 << m)):
            polys = {((a << 1) ^ b) for a, b in zip(seq, seq[1:]) if a >> (m - 1) & 1}
            if len(polys) == 1:
                out.append(f"GF(2^{m}) antilog table, poly 0x{polys.pop():X}")
            else:
                out.append(f"permutation of 1..2^{m}-1 (GF log/antilog candidate)")
    return out


# ------------------------------------------------------------------------------------------------------------------------------- LUT functions
def classify_tt(tt, k):
    n = 1 << k
    full = (1 << n) - 1
    tt &= full
    if tt in (0, full):
        return "const"
    c = tt & 1
    S = sum(1 << j for j in range(k) if ((tt >> (1 << j)) & 1) ^ c)
    if all(((tt >> i) & 1) == c ^ (bin(i & S).count("1") & 1) for i in range(n)):
        w = bin(S).count("1")
        return "buf/inv" if w == 1 else f"xor{w}"
    ones = bin(tt).count("1")
    if ones == 1 or ones == n - 1:
        return f"and{k}" if ones == 1 else f"or{k}"
    if k == 3:
        for s in range(3):
            a, b = [j for j in range(3) if j != s]
            for pa, pb in ((a, b), (b, a)):
                if all(((tt >> i) & 1) == ((i >> pb) & 1 if (i >> s) & 1 else (i >> pa) & 1) for i in range(8)):
                    return "mux2"
        if all(((tt >> i) & 1) == (bin(i).count("1") >= 2) for i in range(8)):
            return "maj3"
    return f"other{k}"


# ------------------------------------------------------------------------------------------------------------------------------------ carver
class Carver:
    def __init__(self, P, D, pat, owner, blob, cells):
        self.P, self.D, self.pat, self.owner, self.blob = P, D, pat, owner, blob
        self.cells = set(cells)
        self.nin, self.nout = {}, {}
        for c in self.cells:
            self.nin[c] = P.inputs(c)
            self.nout[c] = P.consumers(c)
        self.reg = {}            # cell -> anchor index
        self.anchors = []        # dict(kind, cells:set, info)

    def blob_nb(self, c):
        return [n for n in (self.nin[c] | self.nout[c]) if n in self.cells]

    def add_anchor(self, kind, cells, info=None):
        cells = {c for c in cells if c in self.cells and c not in self.reg}
        if not cells:
            return
        i = len(self.anchors)
        self.anchors.append(dict(kind=kind, cells=cells, info=info or {}))
        for c in cells:
            self.reg[c] = i

    def build_anchors(self):
        P = self.P
        for key in ("lfsr", "parallel"):
            for g in self.pat.get(key, []):
                self.add_anchor(key, set(g["members"]), dict(n=g["n"], poly=g["poly"], match=g["match"], autonomous=g["autonomous"],
                                                             whiten_consumers=g.get("whiten_consumers"), conf=g["conf"]))
        m9 = [c for c in self.cells if isinstance(c, tuple) and c[0] == "m9k"]
        by_addr = collections.defaultdict(list)
        for c in m9:
            m = P.m9k[(c[1], c[2])]
            by_addr[tuple(m.get("addr") or ())].append(c)
        for addr, grp in by_addr.items():
            self.add_anchor("m9k", set(grp), dict(n=len(grp)))
        macs = [c for c in self.cells if isinstance(c, tuple) and c[0] == "mac"]
        par = {c: c for c in macs}

        def find(c):
            while par[c] != c:
                par[c] = par[par[c]]
                c = par[c]
            return c
        for c in macs:
            for i in self.nin[c]:
                if i in par:
                    par[find(i)] = find(c)
        grp = collections.defaultdict(set)
        for c in macs:
            grp[find(c)].add(c)
        for g in grp.values():
            self.add_anchor("mac", g, dict(n=len(g)))
        chains = collections.defaultdict(set)
        cpar = {}
        for c in self.cells:
            if isinstance(c, str) and c.startswith("lc_") and P.lut[c]["mode"] == "cin":
                cpar[c] = c
        for c in cpar:
            ci = P.lut[c].get("cin")
            if ci and ci.startswith("co_"):
                prev = "lc_" + ci[3:]
                if prev in cpar:
                    a, b = c, prev
                    while cpar[a] != a:
                        a = cpar[a]
                    while cpar[b] != b:
                        b = cpar[b]
                    cpar[a] = b
        for c in cpar:
            r = c
            while cpar[r] != r:
                r = cpar[r]
            chains[r].add(c)
        for ch in chains.values():
            regs = {o for c in ch for o in self.nout[c] if isinstance(o, str) and o.startswith("ff_") and o in self.cells
                    and P.ff[o].get("d") in ch}
            self.add_anchor("carry", ch | regs, dict(chain=len(ch), regs=len(regs)))
        en = collections.defaultdict(set)
        for c in self.cells:
            if isinstance(c, str) and c.startswith("ff_") and c not in self.reg:
                F = P.ff[c]
                e = F.get("ena")
                if e and e not in ("1'b1", "1'b0"):
                    en[(F.get("clk"), e, F.get("sclr"))].add(c)
        for (clk, e, s), ffs in en.items():
            if REG_MIN <= len(ffs) <= REG_MAX:
                self.add_anchor("register", ffs, dict(ena=e, sclr=s, n=len(ffs)))
        log.info("%s anchors: %s", self.blob, dict(collections.Counter(a["kind"] for a in self.anchors)))

    def absorb(self):
        for _ in range(2):
            n = 0
            for i, a in enumerate(self.anchors):
                for c in list(a["cells"]):
                    for x in self.blob_nb(c):
                        if x in self.reg:
                            continue
                        cons = [o for o in self.nout[x] if o in self.cells]
                        ins = [o for o in self.nin[x] if o in self.cells]
                        if (cons and all(self.reg.get(o) == i for o in cons)) or (ins and all(self.reg.get(o) == i for o in ins)):
                            self.reg[x] = i
                            a["cells"].add(x)
                            n += 1
            log.info("%s absorb pass: +%d", self.blob, n)

    def grow(self):
        for r in range(GROW_ROUNDS):
            claims = {}
            for c in self.cells:
                if c in self.reg:
                    continue
                cnt = collections.Counter(self.reg[n] for n in self.blob_nb(c) if n in self.reg)
                if cnt:
                    best = max(cnt.items(), key=lambda kv: (kv[1], -kv[0]))[0]
                    claims[c] = best
            if not claims:
                break
            for c, i in claims.items():
                self.reg[c] = i
                self.anchors[i]["cells"].add(c)
            log.info("%s grow round %d: +%d, unclaimed %d", self.blob, r + 1, len(claims), sum(1 for c in self.cells if c not in self.reg))
        rest = [c for c in self.cells if c not in self.reg]
        seen = set()
        for c in rest:
            if c in seen:
                continue
            comp, st = set(), [c]
            while st:
                x = st.pop()
                if x in seen:
                    continue
                seen.add(x)
                comp.add(x)
                st.extend(n for n in self.blob_nb(x) if n not in self.reg and n not in seen)
            self.add_anchor("leftover", comp)
        log.info("%s leftovers: %d cells in %d components", self.blob, len(rest), sum(1 for a in self.anchors if a["kind"] == "leftover"))

    def nluts(self, cells):
        return sum(1 for c in cells if isinstance(c, str) and c.startswith("lc_"))

    def merge_small(self):
        """Merge regions under MIN_LUT LUTs (not LFSR/M9K/MAC anchors) into the neighbour they share most edges with, never past MAX_LUT."""
        keep = {"lfsr", "parallel", "m9k", "mac"}
        for it in range(12):
            nl_ = {i: self.nluts(a["cells"]) for i, a in enumerate(self.anchors) if a["cells"]}
            moved = 0
            for i in sorted(nl_, key=lambda i: nl_[i]):
                a = self.anchors[i]
                if not a["cells"] or a["kind"] in keep or nl_.get(i, 0) >= MIN_LUT:
                    continue
                cnt = collections.Counter(self.reg[n] for c in a["cells"] for n in self.blob_nb(c) if self.reg.get(n, i) != i)
                for j, _w in cnt.most_common():
                    if self.anchors[j]["cells"] and nl_.get(j, 0) + nl_[i] <= MAX_LUT:
                        for c in a["cells"]:
                            self.reg[c] = j
                        self.anchors[j]["cells"] |= a["cells"]
                        self.anchors[j].setdefault("merged", []).append(a["kind"])
                        nl_[j] = nl_.get(j, 0) + nl_[i]
                        nl_[i] = 0
                        a["cells"] = set()
                        moved += 1
                        break
            log.info("%s merge pass %d: %d small regions merged", self.blob, it + 1, moved)
            if not moved:
                break

    def split_big(self):
        for i in range(len(self.anchors)):
            a = self.anchors[i]
            if self.nluts(a["cells"]) <= MAX_LUT:
                continue
            labs = collections.defaultdict(set)
            for c in a["cells"]:
                labs[xy_of(self.P, c)].add(c)
            chunks, cur = [], set()
            for lab in sorted(labs):
                if cur and self.nluts(cur) + self.nluts(labs[lab]) > MAX_LUT:
                    chunks.append(cur)
                    cur = set()
                cur |= labs[lab]
            if cur:
                chunks.append(cur)
            a["cells"] = chunks[0]
            a["split"] = len(chunks)
            for ch in chunks[1:]:
                j = len(self.anchors)
                self.anchors.append(dict(kind=a["kind"], cells=ch, info=dict(a["info"]), split_from=i))
                for c in ch:
                    self.reg[c] = j

    def regions(self):
        live = [a for a in self.anchors if a["cells"]]
        live.sort(key=lambda a: min(xy_of(self.P, c) for c in a["cells"]))
        pre = "-".join(self.blob.split("-")[:2]) if self.blob.startswith("802") else self.blob
        for k, a in enumerate(live, 1):
            a["id"] = f"{pre}-r{k:04d}"
        self.cell_region = {c: a["id"] for a in live for c in a["cells"]}
        return live


# ------------------------------------------------------------------------------------------------------------------------------- fact sheet
def PT_cone_tt(D, sig, leaves):
    """Bit-parallel truth table of sig over `leaves` via D.comb (memoised DFS; cone is <= 40 nodes by small_support)."""
    k = len(leaves)
    full = (1 << (1 << k)) - 1
    memo = {s: sum(1 << i for i in range(1 << k) if (i >> j) & 1) for j, s in enumerate(leaves)}
    memo["1'b0"], memo["1'b1"] = 0, full

    busy = set()

    def ev(s):
        if s in memo:
            return memo[s]
        if s in busy:
            raise KeyError(f"combinational loop at {s}")
        busy.add(s)
        _S, _c, uniq, tt = D.comb(s)
        v = [ev(u) for u in uniq]
        out = 0
        for idx in range(1 << len(uniq)):
            if (tt >> idx) & 1:
                t = full
                for b, vb in enumerate(v):
                    t &= vb if (idx >> b) & 1 else ~vb & full
                out |= t
        memo[s] = out
        return out
    return ev(sig)


def small_support(D, sig, cap=40):
    """Leaves of sig's comb cone if there are 1..CONE_MAX of them; None otherwise (bounded: gives up after `cap` cone nodes)."""
    out, seen, st = set(), set(), [sig]
    while st:
        s = st.pop()
        if s in seen or s in ("1'b0", "1'b1"):
            continue
        seen.add(s)
        if len(seen) > cap:
            return None
        cb = D.comb(s)
        if cb is None:
            out.add(s)
            if len(out) > CONE_MAX:
                return None
        else:
            st.extend(cb[2])
    return out or None


def own(cv, c):
    return cv.cell_region.get(c) or cv.owner.get(c) or "unassigned"


def fact_sheet(cv, a, pat_idx):
    P, D = cv.P, cv.D
    cells = a["cells"]
    luts = sorted(c for c in cells if isinstance(c, str) and c.startswith("lc_"))
    ffs = sorted(c for c in cells if isinstance(c, str) and c.startswith("ff_"))
    m9 = sorted(c for c in cells if isinstance(c, tuple) and c[0] == "m9k")
    mac = sorted(c for c in cells if isinstance(c, tuple) and c[0] == "mac")
    xs = [xy_of(P, c) for c in cells]
    fs = dict(id=a["id"], blob=cv.blob, anchor=a["kind"], anchor_info=a.get("info", {}), merged=dict(collections.Counter(a.get("merged", []))),
              counts=dict(lut=len(luts), ff=len(ffs), m9k=len(m9), mac=len(mac), carry_lut=sum(1 for c in luts if P.lut[c]["mode"] == "cin")),
              bbox=[min(x for x, _ in xs), min(y for _, y in xs), max(x for x, _ in xs), max(y for _, y in xs)])
    dn = P.domain_name
    fs["clocks"] = {dn.get(k, k): v for k, v in collections.Counter(P.ff[f].get("clk") for f in ffs).most_common()}
    fs["enables"] = collections.Counter(P.ff[f].get("ena") for f in ffs if P.ff[f].get("ena") not in (None, "1'b1")).most_common(4)
    fs["sclrs"] = collections.Counter(P.ff[f].get("sclr") for f in ffs if P.ff[f].get("sclr") not in (None, "1'b0")).most_common(3)
    cin, cout = collections.defaultdict(lambda: collections.defaultdict(set)), collections.defaultdict(lambda: collections.defaultdict(set))
    for c in cells:
        for i in cv.nin.get(c, ()):
            if i not in cells:
                cin[own(cv, i)][xy_of(P, i) if not (isinstance(i, tuple) and i[0] == "pad") else i].add(cid(i) if not isinstance(i, tuple) or i[0] != "pad" else i[1])
        for o in cv.nout.get(c, ()):
            if o not in cells:
                cout[own(cv, o)][xy_of(P, c)].add(cid(c))

    def bus(d):
        rows = []
        for o, labs in d.items():
            w = sum(len(v) for v in labs.values())
            rows.append(dict(peer=o, bits=w, groups=sorted(((str(k), len(v)) for k, v in labs.items()), key=lambda t: -t[1])[:6]))
        return sorted(rows, key=lambda r: -r["bits"])
    fs["cut_in"], fs["cut_out"] = bus(cin), bus(cout)
    fh = collections.Counter()
    for c in luts:
        if P.lut[c]["mode"] == "cin":
            continue
        cb = D.comb(c)
        if cb is not None:
            fh[classify_tt(cb[3], len(cb[2]))] += 1
    fs["lut_functions"] = dict(fh.most_common())
    outs = [c for c in luts if any(o not in cells for o in cv.nout.get(c, ()))]
    oh, examples = collections.Counter(), []
    for c in outs[:400]:
        if P.lut[c]["mode"] == "cin":
            continue
        sup = small_support(D, c)
        if sup:
            lv = sorted(sup)
            try:
                f = classify_tt(PT_cone_tt(D, c, lv), len(lv))
            except KeyError:
                continue
            oh[f] += 1
            if len(examples) < 6 and f not in ("buf/inv",):
                examples.append(f"{c} = {f}({', '.join(lv)})")
    fs["output_cones"] = dict(n_outputs=len(outs), small_cone_functions=dict(oh.most_common()), examples=examples)
    fs["xor_ffs"] = sum(1 for f in ffs if f in D.faff and D.faff[f][0].bit_count() >= 2)
    fs["copy_ffs"] = sum(1 for f in ffs if f in D.faff and D.faff[f][0].bit_count() == 1)
    fs["m9k"] = []
    for c in m9:
        m = P.m9k[(c[1], c[2])]
        ctl = m.get("ctl") or {}
        A = m.get("A")
        r = dict(tile=[c[1], c[2]], W=m.get("W"), A=A, words=len(m.get("init") or []), sdp=m.get("sdp"), tdp=bool(ctl.get("RAM_USE_TRUE_DUAL_PORT_MODE")),
                 oreg=m.get("oreg"), we=m.get("we"), addr_class=pat_idx["m9k"].get((c[1], c[2]), {}).get("cls"),
                 addr_perm=pat_idx["m9k"].get((c[1], c[2]), {}).get("perm"))
        init = list(m.get("init") or [])
        r["contents"] = shape_tests(init, int(m.get("W") or 1), int(A or 0))
        nz = [i for i, v in enumerate(init) if v]
        if nz:
            r["sample_hex"] = dict(first_nonzero=nz[0], words=[f"{v:X}" for v in init[nz[0]:nz[0] + 24]])
        fs["m9k"].append(r)
    fs["mac"] = []
    for c in mac:
        m = P.mac[(c[1], c[2])]
        src = {}
        for op in ("a", "b"):
            k = collections.Counter()
            for s in m[op]:
                cc = __import__("cycloneiv_clean_partition").cell_of(s)
                if cc is None:
                    continue
                k[(cc[0] if isinstance(cc, tuple) else cc[:2]) + ":" + own(cv, cc)] += 1
            src[op] = dict(k.most_common(4))
        fs["mac"].append(dict(tile=[c[1], c[2]], units=[dict(n=u["n"], w=u["w"], ireg=u.get("ireg"), oreg=u.get("oreg")) for u in m.get("units", [])],
                              sign=m.get("sign"), oreg=m.get("oreg"), operand_src=src, rom=pat_idx["mac"].get((c[1], c[2]))))
    fs["carry_chains"] = []
    ctr_of = pat_idx["ctr"]
    seen = set()
    for c in luts:
        if P.lut[c]["mode"] != "cin" or c in seen:
            continue
        ch, st = set(), [c]
        while st:
            x = st.pop()
            if x in ch or x not in cells or P.lut.get(x, {}).get("mode") != "cin":
                continue
            ch.add(x)
            ci = P.lut[x].get("cin")
            if ci and ci.startswith("co_"):
                st.append("lc_" + ci[3:])
            st.extend(o for o in cv.nout.get(x, ()) if isinstance(o, str) and o.startswith("lc_") and P.lut[o].get("cin") == "co_" + x[3:])
        seen |= ch
        regs = [o for x in ch for o in cv.nout.get(x, ()) if isinstance(o, str) and o.startswith("ff_") and P.ff[o].get("d") == x]
        kinds = {ctr_of[f] for f in regs if f in ctr_of}
        fb = any(f in {p for x in ch for p in P.lut[x]["pins"]} for f in regs)
        used_sum = sum(1 for x in ch if any(o not in ch for o in cv.nout.get(x, ())))
        fs["carry_chains"].append(dict(len=len(ch), regs=len(regs), feedback=fb, kind="/".join(sorted(kinds)) or ("register+feedback" if fb else
                                       ("compare (carry-out only)" if used_sum <= 1 else "adder/subtractor")), start=sorted(ch)[0]))
    fs["carry_chains"].sort(key=lambda r: -r["len"])
    fs["lfsr"] = [dict(kind=g["kind"], n=g["n"], poly=g["poly"], match=g["match"], autonomous=g["autonomous"], whiten=g.get("whiten_consumers"))
                  for g in pat_idx["lfsr"] if set(g["members"]) & set(ffs)]
    fs["headline"] = headline(fs)
    return fs


def headline(fs):
    h = []
    for g in fs["lfsr"]:
        h.append(f"{g['kind'].upper()} {g['poly']}" + (f" = {g['match'][0][0]}" if g["match"] else ""))
    for m in fs["m9k"]:
        if m["contents"] and "all-zero" not in m["contents"][0]:
            hit = [x for x in m["contents"] if any(k in x for k in ("tone", "shape ", "LFSR", "GF", "bit-reversal"))]
            h.append(f"ROM M9K({m['tile'][0]},{m['tile'][1]}) {2 ** m['A']}x{m['W']}: {(hit or m['contents'])[0]}")
    if fs["counts"]["m9k"] and not any("M9K" in x for x in h):
        w = collections.Counter(f"{2 ** m['A']}x{m['W']}" for m in fs["m9k"])
        h.append("RAM " + ", ".join(f"{n}x {k}" for k, n in w.items()))
    if fs["counts"]["mac"]:
        h.append(f"{fs['counts']['mac']} MAC" + ("" if not any(m["rom"] for m in fs["mac"]) else " (M9K-ROM operand)"))
    if fs["carry_chains"]:
        c = fs["carry_chains"][0]
        h.append(f"{len(fs['carry_chains'])} carry chains (longest {c['len']}, {c['kind']})")
    lf = fs["lut_functions"]
    tot = sum(lf.values()) or 1
    xo = sum(v for k, v in lf.items() if k.startswith("xor"))
    if xo / tot > 0.3:
        h.append(f"XOR-heavy logic ({100 * xo // tot}% of LUTs)")
    if fs["xor_ffs"] >= max(4, 0.25 * fs["counts"]["ff"]):
        h.append(f"{fs['xor_ffs']}/{fs['counts']['ff']} FFs load an XOR of >= 2 leaves")
    if fs["copy_ffs"] >= max(16, 0.6 * fs["counts"]["ff"]):
        h.append(f"{fs['copy_ffs']}/{fs['counts']['ff']} FFs are plain copies (delay line / pipeline)")
    return "; ".join(h) or f"{fs['anchor']} region, {fs['counts']['lut']} LUT / {fs['counts']['ff']} FF"


def markdown(fs):
    c = fs["counts"]
    L = [f"# {fs['id']}  ({fs['blob']})", "", f"**{fs['headline']}**", "",
         f"- anchor: {fs['anchor']} {json.dumps(fs['anchor_info'], default=str)}" + (f"; merged in: {fs['merged']}" if fs["merged"] else ""),
         f"- cells: {c['lut']} LUT ({c['carry_lut']} carry), {c['ff']} FF, {c['m9k']} M9K, {c['mac']} MAC; LAB bbox x{fs['bbox'][0]}-{fs['bbox'][2]} y{fs['bbox'][1]}-{fs['bbox'][3]}",
         f"- clocks: {fs['clocks']}", f"- enables (top): {fs['enables']}", f"- sync clears: {fs['sclrs']}",
         f"- FF next-state: {fs['xor_ffs']} XOR of >= 2 leaves, {fs['copy_ffs']} plain copy, of {c['ff']}", "", "## Inputs (peer: bits, source LAB groups)"]
    for r in fs["cut_in"][:12]:
        L.append(f"- {r['peer']}: {r['bits']} bits  {r['groups']}")
    if len(fs["cut_in"]) > 12:
        L.append(f"- ... {len(fs['cut_in']) - 12} more peers")
    L += ["", "## Outputs (peer: bits, our LAB groups)"]
    for r in fs["cut_out"][:12]:
        L.append(f"- {r['peer']}: {r['bits']} bits  {r['groups']}")
    if len(fs["cut_out"]) > 12:
        L.append(f"- ... {len(fs['cut_out']) - 12} more peers")
    L += ["", f"## LUT functions (non-carry): {fs['lut_functions']}",
          f"## Output cones <= {CONE_MAX} leaves: {fs['output_cones']['small_cone_functions']} of {fs['output_cones']['n_outputs']} outputs"]
    L += [f"- {e}" for e in fs["output_cones"]["examples"]]
    if fs["lfsr"]:
        L += ["", "## LFSR / CRC groups"] + [f"- {json.dumps(g, default=str)}" for g in fs["lfsr"]]
    if fs["m9k"]:
        L += ["", "## M9K"]
        for m in fs["m9k"][:16]:
            L.append(f"- ({m['tile'][0]},{m['tile'][1]}) {2 ** m['A']}x{m['W']} tdp={m['tdp']} sdp={m['sdp']} oreg={m['oreg']} we={m['we']} addr={m['addr_class']}"
                     + (f" perm={m['addr_perm']}" if m["addr_perm"] else "") + f"; contents: {'; '.join(m['contents'][:4])}")
            if m.get("sample_hex"):
                L.append(f"  - init from word {m['sample_hex']['first_nonzero']}: {' '.join(m['sample_hex']['words'])}")
        if len(fs["m9k"]) > 16:
            L.append(f"- ... {len(fs['m9k']) - 16} more")
    if fs["mac"]:
        L += ["", "## MAC"]
        for m in fs["mac"]:
            L.append(f"- ({m['tile'][0]},{m['tile'][1]}) units {[(u['n'], u['w']) for u in m['units']]} sign={m['sign']} oreg={m['oreg']} a<-{m['operand_src']['a']} b<-{m['operand_src']['b']}"
                     + (f" ROM {m['rom']}" if m["rom"] else ""))
    if fs["carry_chains"]:
        L += ["", "## Carry chains"] + [f"- len {r['len']}, regs {r['regs']}, {r['kind']} (from {r['start']})" for r in fs["carry_chains"][:10]]
        if len(fs["carry_chains"]) > 10:
            L.append(f"- ... {len(fs['carry_chains']) - 10} more")
    return "\n".join(L[:150]) + "\n"


# ------------------------------------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", required=True)
    ap.add_argument("--blob", action="append", required=True)
    ap.add_argument("--partition", default=os.path.join(REPO, "tmp", "cycloneiv_clean", "partition.json"))
    ap.add_argument("--board", default=os.path.join(REPO, "boards", "dji-m2001"))
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_region_carve.log"))])
    from lifters.cycloneiv_clean import patterns as PT
    from cycloneiv_clean_partition import Partition
    nl = pickle.load(open(a.nl, "rb"))
    P = Partition(nl, [], nets_tsv=os.path.join(a.board, "nets.tsv"))
    D = PT.Design(nl).prepare()
    cache = os.path.join(OUT, "patterns.json")
    if os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(a.nl):
        pat = json.load(open(cache))
    else:
        pat = json.loads(json.dumps(PT.detect(nl), default=str))
        json.dump(pat, open(cache, "w"))
    pat_idx = dict(m9k={tuple(r["xy"]): r for r in pat["m9k_addr"]},
                   mac={tuple(r["xy"]): r for r in pat["mac_rom"] if r.get("m9k")},
                   ctr={f: c["kind"] for c in pat["counters"] for f in c["ffs"]},
                   lfsr=pat["lfsr"] + pat["parallel"])
    part = json.load(open(a.partition))
    owner = {}
    for b in part["blocks"]:
        cl = b["cells"]
        for c in cl["luts"] + cl["ffs"]:
            owner[c] = b["name"]
        for x, y in cl["m9k"]:
            owner[("m9k", x, y)] = b["name"]
        for x, y in cl["mac"]:
            owner[("mac", x, y)] = b["name"]
        for p in cl["pads"]:
            owner[("pad", p)] = b["name"]
    for blob in a.blob:
        row = next(b for b in part["blocks"] if b["name"] == blob)
        cl = row["cells"]
        cells = cl["luts"] + cl["ffs"] + [("m9k", x, y) for x, y in cl["m9k"]] + [("mac", x, y) for x, y in cl["mac"]]
        cv = Carver(P, D, pat, owner, blob, cells)
        cv.build_anchors()
        cv.absorb()
        cv.grow()
        cv.merge_small()
        cv.split_big()
        regs = cv.regions()
        od = os.path.join(OUT, blob)
        os.makedirs(od, exist_ok=True)
        index = []
        adj = collections.defaultdict(collections.Counter)
        for r in regs:
            fs = fact_sheet(cv, r, pat_idx)
            json.dump(fs, open(os.path.join(od, f"{r['id']}.json"), "w"), indent=1, default=str)
            open(os.path.join(od, f"{r['id']}.md"), "w").write(markdown(fs))
            for side in ("cut_in", "cut_out"):
                for e in fs[side]:
                    adj[r["id"]][e["peer"]] += e["bits"]
            index.append(dict(id=r["id"], headline=fs["headline"], anchor=fs["anchor"], **fs["counts"], bbox=fs["bbox"]))
        index.sort(key=lambda r: -(r["lut"] + r["ff"]))
        sizes = [r["lut"] for r in index]
        stat = dict(regions=len(index), lut_min=min(sizes), lut_median=sorted(sizes)[len(sizes) // 2], lut_max=max(sizes),
                    over_max=sum(1 for s in sizes if s > MAX_LUT), under_50=sum(1 for s in sizes if s < 50),
                    anchors=dict(collections.Counter(r["anchor"] for r in index)))
        json.dump(dict(blob=blob, stats=stat, regions=index, adjacency={k: dict(v.most_common()) for k, v in adj.items()}),
                  open(os.path.join(od, "index.json"), "w"), indent=1)
        json.dump({cid(c): r for c, r in cv.cell_region.items()}, open(os.path.join(od, "cell_region.json"), "w"))
        log.info("%s: %s", blob, json.dumps(stat))
        for r in index[:12]:
            log.info("  %s %d LUT %d FF: %s", r["id"], r["lut"], r["ff"], r["headline"])


if __name__ == "__main__":
    main()
