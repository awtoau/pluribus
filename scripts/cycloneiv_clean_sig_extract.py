#!/usr/bin/env python3.15t
"""Structural signatures of known-design blocks from OUR decode of a built bitstream (clean emit netlist), #165.

  python3.15t scripts/cycloneiv_clean_sig_extract.py NAME [NAME ...]      (tmp/sig/<name>/bitstream.rbf -> tmp/sig/<name>/sig.json)
  python3.15t scripts/cycloneiv_clean_sig_extract.py --all
Log: tmp/logs/cycloneiv_clean_sig_extract.log.  Structure only: no statistics, no learned patterns.

Recognisers (all derived from the decoded netlist, matched against catalogues computed from first principles):
- LINEAR state machines: SCC of the FF graph; D cones evaluated exactly (truth tables over the cone leaves), external inputs
  (pads / FFs outside the SCC) searched for the assignment that makes the most cones GF(2)-affine; state map A (n x n over GF(2));
  minimal polynomial of A (basis-independent) vs. catalogue: LFSR polynomials stepped k bits/clock (k = 1..64), RS generator LFSR.
- SHIFT chains (FF D = another FF) and XOR tap sets over a chain (convolutional encoders): positions vs. catalogue polynomials.
- ROM content: M9K words tested for sine/cosine tables (twiddle ROMs).
- Resource counts: LUT / carry LUT / FF / M9K / MAC / pads.
"""
import argparse
import collections
import itertools
import json
import logging
import math
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.setrecursionlimit(20000)
SIG = os.path.join(REPO, "tmp", "sig")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_sig_extract.log")
log = logging.getLogger("sig_extract")
CONST = {"1'b1": 1, "1'b0": 0}
LEAF_CAP = 18                  # decision: cone leaf cap; a 2^18-bit truth table is 32 KB per node
SCC_MIN, SCC_MAX = 3, 200      # decision: SCC sizes analysed as state machines
EXT_MAX = 40                   # decision: external inputs searched for the linearising assignment


# ---------------------------------------------------------------- GF(2) linear algebra (rows as int bitmasks)
def mat_mul(A, B, n):
    """(A*B) rows: row i of A selects rows of B."""
    out = []
    for i in range(n):
        r, a, j = 0, A[i], 0
        while a:
            if a & 1:
                r ^= B[j]
            a >>= 1
            j += 1
        out.append(r)
    return out


def mat_vec(A, v, n):
    return sum((bin(A[i] & v).count("1") & 1) << i for i in range(n))


def mat_pow(A, k, n):
    R = [1 << i for i in range(n)]
    while k:
        if k & 1:
            R = mat_mul(R, A, n)
        A = mat_mul(A, A, n)
        k >>= 1
    return R


def minpoly(A, n):
    """Minimal polynomial of the GF(2) map A (row masks) as int (bit i = coeff of x^i): lcm over a basis of Krylov spaces."""
    import random
    rnd = random.Random(1)
    result = 1
    covered = []   # reduced basis of vectors already covered
    seqs = []
    for trial in range(n + 4):
        v = rnd.getrandbits(n) or 1
        basis, vs = {}, []
        k = 0
        w = v
        poly = None
        while True:
            # reduce w against basis tracking combination
            comb, x = 1 << k, w
            for p in sorted(basis, reverse=True):
                if (x >> p) & 1:
                    x ^= basis[p][0]
                    comb ^= basis[p][1]
            if x == 0:
                poly = comb
                break
            basis[x.bit_length() - 1] = (x, comb)
            w = mat_vec(A, w, n)
            k += 1
        result = pl_lcm(result, poly)
        if result.bit_length() - 1 >= n:
            break
    return result


def pl_mulmod(a, b, m):
    r = 0
    while b:
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
        if a.bit_length() == m.bit_length():
            a ^= m
    return r


def pl_divmod(a, b):
    q = 0
    db = b.bit_length()
    while a.bit_length() >= db:
        s = a.bit_length() - db
        q ^= 1 << s
        a ^= b << s
    return q, a


def pl_mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a <<= 1
        b >>= 1
    return r


def pl_gcd(a, b):
    while b:
        a, b = b, pl_divmod(a, b)[1]
    return a


def pl_lcm(a, b):
    return pl_divmod(pl_mul(a, b), pl_gcd(a, b))[0]


def companion(poly_low, w):
    """Single-step Galois LFSR matrix (rows) of x^w + poly_low: state' = x*state mod poly."""
    rows = []
    for i in range(w):
        r = 0
        # new bit i = old bit i-1 (shift) xor (feedback old bit w-1 if poly bit i)
        if i > 0:
            r |= 1 << (i - 1)
        if (poly_low >> i) & 1:
            r |= 1 << (w - 1)
        rows.append(r)
    return rows


# first-principles catalogue: name -> (width, low-order polynomial bits)
LFSR_CAT = {
    "PRBS15 x^15+x^14+1 (IEEE 802.16 randomiser)": (15, (1 << 14) | 1),
    "PRBS7 x^7+x^4+1 / x^7+x^6+1 (IEEE 802.11 scrambler)": (7, (1 << 4) | 1),
    "PRBS7 x^7+x^6+1": (7, (1 << 6) | 1),
    "PRBS9 x^9+x^5+1": (9, (1 << 5) | 1),
    "PRBS11 x^11+x^9+1": (11, (1 << 9) | 1),
    "PRBS20 x^20+x^3+1": (20, 0b1001),
    "PRBS23 x^23+x^18+1": (23, (1 << 18) | 1),
    "PRBS31 x^31+x^28+1": (31, (1 << 28) | 1),
    "CRC32 IEEE 802.3 (04C11DB7)": (32, 0x04C11DB7),
    "CRC16-CCITT (1021)": (16, 0x1021),
    "CRC16-ANSI (8005)": (16, 0x8005),
    "CRC8 (07) / 802.16 HCS": (8, 0x07),
    "CRC8-DVB-S2 (D5)": (8, 0xD5),
    "CRC24-Q": (24, 0x864CFB),
    "CRC5-USB (05)": (5, 0x05),
}


def gf256_rs_genpoly(nroots, genstart=0, irr=0x11D):
    exp, x = [], 1
    for _ in range(255):
        exp.append(x)
        x <<= 1
        if x & 0x100:
            x ^= irr
    mul = lambda a, b: 0 if a == 0 or b == 0 else exp[(exp.index(a) + exp.index(b)) % 255]
    g = [1]
    for i in range(nroots):
        r = exp[(genstart + i) % 255]
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j + 1] ^= c
            ng[j] ^= mul(c, r)
        g = ng
    return g, mul, exp


def rs_encoder_matrix(nroots, genstart=0, irr=0x11D):
    """GF(2) state map of the systematic RS encoder LFSR (parity = remainder mod g(x)), state = nroots bytes."""
    g, mul, _ = gf256_rs_genpoly(nroots, genstart, irr)
    n = 8 * nroots
    # parity register p[0..nroots-1]; fb = in ^ p[nroots-1]; p[i] <= p[i-1] ^ g[i]*fb ; with input 0: fb = p[last]
    def mulbits(c):                      # 8x8 matrix columns of x -> c*x
        return [mul(c, 1 << j) for j in range(8)]
    rows = [0] * n
    def setrow_from(col_vec_fn):
        pass
    # build state' as linear function: out bit (i*8+b) = XOR of in bits
    for i in range(nroots):
        # contribution of p[i-1]
        for b in range(8):
            r = 0
            if i > 0:
                r ^= 1 << ((i - 1) * 8 + b)
            # g[i]*fb with fb = p[last]: bit b of g[i]*x = XOR_j x_j * bit b of (g[i]*e_j)
            cols = mulbits(g[i])
            for j in range(8):
                if (cols[j] >> b) & 1:
                    r ^= 1 << ((nroots - 1) * 8 + j)
            rows[i * 8 + b] = r
    return rows, n


def pow_alpha(j, irr=0x11D):
    x = 1
    for _ in range(j % 255):
        x <<= 1
        if x & 0x100:
            x ^= irr
    return x


def mulmat_rows(c, irr=0x11D):
    """Row masks of x -> c*x over GF(2^8) (bit b of the result = parity(row[b] & x))."""
    def mul(a, b):
        r = 0
        while b:
            if b & 1:
                r ^= a
            a <<= 1
            if a & 0x100:
                a ^= irr
            b >>= 1
        return r
    cols = [mul(c, 1 << j) for j in range(8)]
    return [sum(((cols[j] >> b) & 1) << j for j in range(8)) for b in range(8)]


def conv_taps(polys_octal):
    """Delay-tap sets (delay 0 = newest bit) of a feed-forward convolutional code."""
    out = []
    for p in polys_octal:
        v = int(str(p), 8)
        k = v.bit_length()
        out.append(frozenset(i for i in range(k) if (v >> (k - 1 - i)) & 1))
    return out


# ---------------------------------------------------------------- netlist cones
class Cones:
    def __init__(self, nl):
        self.nl = nl
        self.lut = {L["name"]: L for L in nl.luts}
        self.ff = {F["name"]: F for F in nl.ffs}
        self.leafsets = {}

    def leaves(self, sig):
        """Leaf signals of the combinational cone of `sig` (FF Q / pad / co_ / block source), iterative."""
        if sig in self.leafsets:
            return self.leafsets[sig]
        out, stack, seen = set(), [sig], set()
        while stack:
            s = stack.pop()
            if s in CONST or s in seen:
                continue
            seen.add(s)
            L = self.lut.get(s)
            if L is None:
                out.add(s)
            else:
                stack.extend(L["pins"])
        self.leafsets[sig] = out
        return out

    def tt(self, sig, leaves, assign):
        """Truth table (int over len(leaves) vars, leaf j = bit j of the index) of `sig`; `assign`: leaf -> 0/1 fixed."""
        k = len(leaves)
        full = (1 << (1 << k)) - 1
        var = {}
        for s, v in assign.items():
            var[s] = full if v else 0
        for j, s in enumerate(leaves):
            if s not in assign:
                t, blk = 0, 1 << j
                pat = ((1 << blk) - 1) << blk       # bits where var j = 1 within a period of 2*blk
                period = 2 * blk
                t = pat
                while period < (1 << k):
                    t |= t << period
                    period *= 2
                var[s] = t & full
        memo = {}

        def ev(s):
            if s in CONST:
                return full if CONST[s] else 0
            if s in var:
                return var[s]
            if s in memo:
                return memo[s]
            L = self.lut[s]
            ins = [ev(p) for p in L["pins"]]
            r = 0
            for li in range(16):
                if (L["init"] >> li) & 1:
                    m = full
                    for q in range(4):
                        m &= ins[q] if (li >> q) & 1 else ~ins[q] & full
                    r |= m
            memo[s] = r
            return r
        return ev(sig)


def affine_form(tt, k):
    """(const, mask of linear vars) if tt over k vars is affine, else None."""
    full = (1 << (1 << k)) - 1
    c = tt & 1
    mask, cand = 0, (full if c else 0)
    for j in range(k):
        if (tt >> (1 << j)) & 1 != c:
            mask |= 1 << j
            blk = 1 << j
            pat = ((1 << blk) - 1) << blk
            period = 2 * blk
            t = pat
            while period < (1 << k):
                t |= t << period
                period *= 2
            cand ^= t & full
    return (c, mask) if cand == tt else None


def tarjan(nodes, edges):
    idx, low, onst, st, comps, c = {}, {}, set(), [], [], [0]
    for root in nodes:
        if root in idx:
            continue
        work = [(root, iter(edges.get(root, ())))]
        idx[root] = low[root] = c[0]
        c[0] += 1
        st.append(root)
        onst.add(root)
        while work:
            v, it = work[-1]
            adv = False
            for w in it:
                if w not in idx:
                    idx[w] = low[w] = c[0]
                    c[0] += 1
                    st.append(w)
                    onst.add(w)
                    work.append((w, iter(edges.get(w, ()))))
                    adv = True
                    break
                elif w in onst:
                    low[v] = min(low[v], idx[w])
            if adv:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == idx[v]:
                comp = []
                while True:
                    w = st.pop()
                    onst.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                comps.append(comp)
    return comps


def analyse_scc(cn, comp):
    """State map of an FF SCC: (n, A rows, affine count, assignment) or a reason string."""
    state = sorted(comp)
    n = len(state)
    ext = set()
    for f in state:
        ext |= {s for s in cn.leaves(cn.ff[f]["d"]) if s not in cn.ff or s not in comp}
    ext = sorted(ext)
    if len(ext) > EXT_MAX:
        return "too many external inputs (%d)" % len(ext)
    leaf_all = {f: sorted(cn.leaves(cn.ff[f]["d"])) for f in state}
    if any(len(v) > LEAF_CAP + 8 for v in leaf_all.values()):
        return "cone leaf cap"

    def evaluate(assign):
        rows, ok, nnz = [], 0, 0
        for f in state:
            lv = [s for s in leaf_all[f] if s not in assign]
            if len(lv) > LEAF_CAP:
                rows.append(None)
                continue
            t = cn.tt(cn.ff[f]["d"], lv, assign)
            af = affine_form(t, len(lv))
            if af is None:
                rows.append(None)
                continue
            r = 0
            for j, s in enumerate(lv):
                if (af[1] >> j) & 1 and s in comp:
                    r |= 1 << state.index(s)
            rows.append(r)
            ok += 1
            nnz += bin(r).count("1")
        return rows, ok, nnz
    assign = {e: 0 for e in ext}
    best = evaluate(assign)
    improved = True
    while improved:
        improved = False
        for e in ext:
            a2 = dict(assign)
            a2[e] ^= 1
            r = evaluate(a2)
            if (r[1], r[2]) > (best[1], best[2]):
                assign, best, improved = a2, r, True
    rows, ok, nnz = best
    if ok != n:
        return "%d / %d D cones affine in the SCC state under the best input assignment" % (ok, n)
    return n, rows, assign


def lfsr_match(A, n, minp):
    """Catalogue hits; polynomial in either orientation (connection vs recurrence polynomial)."""
    hits = []
    for name, (w, low) in LFSR_CAT.items():
        if w != n:
            continue
        full = (1 << w) | low
        rec = int(bin(full)[2:].zfill(w + 1)[::-1], 2)
        for orient, pf in (("", full), (" (reciprocal)", rec)):
            M = companion(pf & ((1 << w) - 1), w)
            for k in (1, 3, 5, 7, 8, 16, 32, 64):    # k and 2^j*k share a minimal polynomial: bits/clk is determined only up to that
                if minpoly(mat_pow(M, k, w), w) == minp:
                    hits.append("%s%s, %s" % (name, orient, "x^%d step" % k))
                    break
    return hits


# ---------------------------------------------------------------- ROM content
def rom_sine(content):
    """Test an M9K image for sine/cosine table content.  Returns list of descriptors."""
    import numpy as np
    from lifters.cycloneiv_clean import m9k as M9
    bits = np.asarray(content, np.uint8)
    hits = []
    for W in (8, 9, 16, 18):
        try:
            rw = M9.read_words(bits, W)
        except Exception:
            continue
        nw = rw.shape[0]
        w = (rw.astype(np.int64) * (1 << np.arange(W))).sum(1)
        nzi = np.flatnonzero(w)
        if len(nzi) < 16:
            continue
        w = w[nzi[0]:nzi[-1] + 1]          # the table sits at some offset inside the 9 Kbit array
        nw = len(w)
        for sgn in (False, True):
            v = np.where(w >= (1 << (W - 1)), w - (1 << W), w) if sgn else w
            for D in (nw, nw // 2, nw // 4, nw // 8):
                if D < 16:
                    continue
                s = v[:D].astype(float)
                if s.max() - s.min() < 8:
                    continue
                for span, label in ((2 * math.pi, "full"), (math.pi, "half"), (math.pi / 2, "quarter")):
                    t = np.arange(D) * span / D
                    best = None
                    for ph in (0.0, math.pi / 2, math.pi, 1.5 * math.pi):
                        c = np.cos(t + ph)
                        A = np.dot(s - s.mean(), c) / np.dot(c, c) if True else 0
                        for off in (0.0,):
                            fit = (s.mean() if not sgn else 0.0) + A * c
                            res = np.abs(s - fit).max() / max(1.0, np.abs(A))
                            if best is None or res < best[0]:
                                best = (res, ph, A)
                    if best and best[0] < 0.01 and abs(best[2]) > 4:
                        hits.append("W=%d %s D=%d %s-wave %s peak=%d resid=%.4f" % (W, "signed" if sgn else "unsigned", D, label, "cos/sin", round(abs(best[2])), best[0]))
    return hits[:4]


# ---------------------------------------------------------------- per-design extraction
def extract(name):
    from lifters.cycloneiv_clean import emit
    import heavy_guard
    rbf = os.path.join(SIG, name, "bitstream.rbf")
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    t0 = time.time()
    with heavy_guard.lease(gb, "cyc4_clean_sig_extract", log):
        nl = emit.Builder(emit.Ctx(), rbf, name).run()
    cn = Cones(nl)
    from lifters.cycloneiv_clean import rtl
    _, rep = rtl.lift(nl)
    out = dict(rtl={k: rep[k] for k in ("adders", "subtractors", "comparators", "counters", "shift_registers", "fsms", "muxes", "xor", "reg_bits", "adder_widths")},
               name=name, luts=len(nl.luts), carry_luts=sum(1 for L in nl.luts if L["mode"] == "cin"), ffs=len(nl.ffs),
               m9k=len(nl.m9k), mac=len(nl.mac), pads_in=sum(1 for i in nl.ios if i["dir"] == "input"),
               pads_out=sum(1 for i in nl.ios if i["dir"] != "input"))
    # FF graph
    edges = {f: [s for s in cn.leaves(F["d"]) if s in cn.ff] for f, F in cn.ff.items()}
    comps = [c for c in tarjan(sorted(cn.ff), edges) if len(c) >= 2]
    sccs = []
    for comp in sorted(comps, key=len, reverse=True):
        rec = dict(n=len(comp))
        if len(comp) < SCC_MIN or len(comp) > SCC_MAX:
            rec["linear"] = "not analysed (size)"
            sccs.append(rec)
            continue
        r = analyse_scc(cn, comp)
        if isinstance(r, str):
            rec["linear"] = False
            rec["why"] = r
        else:
            n, A, assign = r
            mp = minpoly(A, n)
            rec.update(linear=True, minpoly_deg=mp.bit_length() - 1, minpoly=hex(mp), nnz=sum(bin(x).count("1") for x in A),
                       inputs_set_1=sorted(k for k, v in assign.items() if v)[:8])
            if n <= 64:
                rec["lfsr_catalogue"] = lfsr_match(A, n, mp)
            for nr in (16, 8, 32, 4):
                if n == 8 * nr:
                    rows, nn = rs_encoder_matrix(nr)
                    if minpoly(rows, nn) == mp:
                        rec.setdefault("rs_catalogue", []).append("RS encoder LFSR GF(2^8) poly 0x11D, %d check symbols (RS(%d,%d) family), genstart 0" % (nr, 255, 255 - nr))
        sccs.append(rec)
    out["scc"] = sccs
    # RS syndrome registers: 8-FF linear SCCs whose minimal polynomial is that of a^j (multiply-by-a^j feedback), GF(2^8) poly 0x11D
    found = collections.Counter(int(r["minpoly"], 16) for r in sccs if r.get("linear") is True and r["n"] == 8)
    for nr in (32, 16, 8, 4, 2):
        for gs in (0, 1):
            want = collections.Counter()
            for j in range(gs, gs + nr):
                c = pow_alpha(j)
                if c != 1:           # a^0: identity feedback, the register is a self-loop (no 8-FF SCC)
                    want[minpoly(mulmat_rows(c), 8)] += 1
            if want and all(found[k] >= v for k, v in want.items()):
                out.setdefault("rs_syndrome_catalogue", []).append("minimal polynomials of a^%d..a^%d (%d roots, t=%d) all present among 8-FF linear SCCs (GF(2^8) 0x11D)" % (gs, gs + nr - 1, nr, nr // 2))
                break
        if out.get("rs_syndrome_catalogue"):
            break
    # shift chains: FF whose D cone is exactly one signal (buffer LUTs resolved)
    leafs = {f: sorted(cn.leaves(F["d"])) for f, F in cn.ff.items()}
    use = collections.Counter(s for lv in leafs.values() for s in lv)
    pads = sorted(s for s in use if s.startswith("pad_") or (s in cn.ff and use[s] >= 4))   # gating inputs: pads and widely used FFs

    def shift_edges(assign):
        sr = {}
        for f, F in cn.ff.items():
            lv = [s for s in leafs[f] if s not in assign]
            if len(lv) == 1 and len(leafs[f]) <= LEAF_CAP and cn.tt(F["d"], lv, assign) == 0b10 and lv[0] in cn.ff:
                sr[f] = lv[0]
        return sr
    assign, src = {}, shift_edges({})
    if len(cn.ff) <= 800 and len(pads) <= EXT_MAX:
        assign = {p: 0 for p in pads}
        src = shift_edges(assign)
        improved = True
        while improved:
            improved = False
            for p in pads:
                a2 = dict(assign)
                a2[p] ^= 1
                s2 = shift_edges(a2)
                if len(s2) > len(src):
                    assign, src, improved = a2, s2, True
    out["shift_assign_ones"] = sorted(k for k, v in assign.items() if v)
    fan = collections.Counter(src.values())
    nxt = {s: f for f, s in src.items() if fan[s] == 1}
    prev = {v: k for k, v in nxt.items()}
    chains = []
    for s in [f for f in cn.ff if f in nxt and f not in prev]:
        ch, c = [s], s
        while c in nxt and nxt[c] not in ch:
            c = nxt[c]
            ch.append(c)
        if len(ch) >= 3:
            chains.append(ch)
    out["shift_chains"] = sorted((len(c) for c in chains), reverse=True)[:12]
    pos = {f: (ci, p) for ci, ch in enumerate(chains) for p, f in enumerate(ch)}
    taps = collections.Counter()
    gate = set(pads)
    for f, F in cn.ff.items():
        lv0 = leafs[f]
        if not 3 <= len(lv0) <= LEAF_CAP + 4:
            continue
        gl = [s for s in lv0 if s in gate and s not in pos]
        if len(gl) > 6:
            continue
        seen = set()
        for r in range(len(gl) + 1):        # fewest assigned gating inputs first: data inputs stay free (counted as external)
            for sub in itertools.combinations(gl, r):
                for m in range(1 << r):
                    asg = {s: (m >> i) & 1 for i, s in enumerate(sub)}
                    lv = [s for s in lv0 if s not in asg]
                    if len(lv) > LEAF_CAP:
                        continue
                    af = affine_form(cn.tt(F["d"], lv, asg), len(lv))
                    if not af or af[0]:
                        continue
                    sel = [lv[j] for j in range(len(lv)) if (af[1] >> j) & 1]
                    inch = [s for s in sel if s in pos]
                    chs = {pos[s][0] for s in inch}
                    if len(chs) == 1 and len(inch) >= 2:
                        ci = next(iter(chs))
                        key = (ci, tuple(sorted(pos[s][1] for s in inch)), len(sel) - len(inch))
                        if key not in seen:
                            seen.add(key)
                            taps[key] += 1
            if seen:
                break
    out["chain_taps"] = [dict(chain_len=len(chains[ci]), chain_positions=list(ps), external_inputs=e, cones=c) for (ci, ps, e), c in taps.most_common(10)]
    conv = collections.defaultdict(set)
    for (ci, ps, e) in taps:
        for off in (0, 1):
            conv[(ci, off)].add(frozenset(p + off for p in ps) - {0})   # delay 0 (the live input) is gated separately in registered designs
    cat = {"K=7 171/133 (CCSDS / IEEE 802.16 / 802.11a)": conv_taps([171, 133]), "K=3 7/5": conv_taps([7, 5]), "K=9 561/753": conv_taps([561, 753])}
    hits = []
    for nm, want in cat.items():
        K = max(max(w) for w in want) + 1
        for (ci, off), got in conv.items():
            for rev in (False, True):
                ws = [(frozenset(K - 1 - d for d in w) if rev else w) - {0} for w in want]
                if all(w in got for w in ws):
                    hits.append("%s on chain of %d (delay offset %d%s)" % (nm, len(chains[ci]), off, ", reversed" if rev else ""))
    out["conv_catalogue"] = sorted(set(hits))
    # M9K ROM content
    rom = []
    for m in nl.m9k:
        h = rom_sine(m["content"]) if m.get("content") is not None else []
        rom.append(dict(x=m["x"], y=m["y"], W=m["W"], nonzero_bits=int(m["content"].sum()) if m.get("content") is not None else 0, sine_table=h))
    out["m9k_blocks"] = rom
    out["m9k_sine_blocks"] = sum(1 for r in rom if r["sine_table"])
    out["seconds"] = round(time.time() - t0, 1)
    json.dump(out, open(os.path.join(SIG, name, "sig.json"), "w"), indent=1)
    log.info("%s: %s", name, json.dumps({k: v for k, v in out.items() if k not in ("m9k_blocks",)})[:900])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    names = a.names or sorted(d for d in os.listdir(SIG) if os.path.exists(os.path.join(SIG, d, "bitstream.rbf")))
    for n in names:
        try:
            extract(n)
        except Exception:
            log.exception("%s failed", n)


if __name__ == "__main__":
    main()
