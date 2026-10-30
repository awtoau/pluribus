"""Cyclone IV clean pipeline: structural pattern detectors on a recovered `emit.Netlist` (#165).

Generic: no image data, no statistics.  Every detector is exact algebra / graph structure over the LUT / FF / block records and reports
evidence plus a confidence (high = matched a documented standard or full-rank structure, medium = structure only, low = weak).  Unknown stays unknown.
Linear (XOR) logic is analysed over GF(2): each combinational signal is expressed as an affine form (mask over leaves, constant) when every LUT
on its cone is affine in its inputs; leaves are FF outputs, pads, block outputs, undecoded sources and carry-mode LUT outputs.

Detectors (result key: construct)
  lfsr        strongly connected FF group with an affine next-state: Fibonacci / Galois, taps, charpoly, known-polynomial match, whitening consumers
  parallel    same groups with width-w stepping (CRC engines, word-parallel scramblers): charpoly(M^w) match for w = 1..64
  conv        shift chain + >= 2 XOR tap outputs compared with known convolutional generators
  gfmul       8 outputs over 8 leaves, invertible GF(2) matrix == multiplication by a constant (matched up to bit relabelling)
  shift       straight FF chains (>= 3), loadable (mux) chains
  syncword    AND-of-literals cone over >= 8 FFs (constant comparator), from a shift chain or a counter
  counters    carry-chain registers with self feedback (counter / accumulator)
  m9k_addr    modelled M9K whose address support is counter bits (identity / bit permutation / function)
  mac_rom     MAC operands fed by M9K outputs (twiddle-ROM / butterfly shape)
  cdc         2-FF synchronisers, cross-domain register edges, gray-coded counter registers, pointer comparators
"""
import collections
import itertools


CONSTV = {"1'b1": 1, "1'b0": 0}
# source: emit.py signal name prefixes (lc_/ff_/co_ cells, pad_<ball>, m9k_/mac_ block outputs, u_ undecoded sources)
LEAF_PREFIX = {"ff": "ff", "pad": "pad", "m9k": "m9k", "mac": "mac", "u": "src", "co": "co", "lc": "lc"}
MAX_SCC = 512                             # decision: larger SCCs are not LFSR / CRC groups (a 512-bit parallel CRC is not a thing)
MIN_SCC = 3
MAX_W = 64                                # decision: parallel step widths tried (bus widths up to 64)
CONSUMER_MASK_CAP = 256                   # decision: affine cones with more leaves are not indexed as consumers
SYNC_MIN = 8
SHIFT_MIN = 3
CONV_MIN_CHAIN = 2                        # K - 1 >= 2
GATE_FAN = 3                              # decision: a gate pin (sync clear / set / load condition) is read by >= 3 LUT / FF pins
PRIM_MAX_N = 64                           # decision: primitivity test (factoring 2^n - 1) up to n = 64

# source: ITU-T O.150 s5 (PRBS 7/9/11/15/20/23/31); IEEE 802.16 data randomiser and ETSI EN 300 744 s4.3.1 / EN 302 307 s5.2.2 (x^15+x^14+1); IEEE 802.11 s17.3.5.5 (x^7+x^4+1); CCSDS 131.0-B pseudo-randomiser (x^8+x^7+x^5+x^3+1); IEEE 802.3 cl.49 (x^58+x^39+1); PCIe 2.x (x^16+x^5+x^4+x^3+1); ETSI EN 302 307 s5.2.2 PL scrambler (x^18+x^7+1)
LFSR_POLYS = {
    "PRBS7 x7+x6+1": (7, 6, 0), "PRBS9 x9+x5+1": (9, 5, 0), "PRBS11 x11+x9+1": (11, 9, 0), "x15+x14+1 (PRBS15 / 802.16 / DVB randomiser)": (15, 14, 0),
    "PRBS20 x20+x3+1": (20, 3, 0), "PRBS23 x23+x18+1": (23, 18, 0), "PRBS31 x31+x28+1": (31, 28, 0), "802.11 x7+x4+1": (7, 4, 0),
    "CCSDS x8+x7+x5+x3+1": (8, 7, 5, 3, 0), "10GBASE-R x58+x39+1": (58, 39, 0), "PCIe x16+x5+x4+x3+1": (16, 5, 4, 3, 0),
    "DVB-S2 PL x18+x7+1": (18, 7, 0),
}

# source: IEEE 802.16 HCS (x^8+x^2+x+1); USB CRC5 (x^5+x^2+1); ITU-T V.41 CRC-16-CCITT (0x1021); CRC-16-ANSI (0x8005); IEEE 802.3 CRC-32 (0x04C11DB7); RFC 3720 CRC-32C (0x1EDC6F41); RFC 4880 CRC-24 (0x864CFB); ETSI EN 302 307 s5.1.4 CRC-8 (0xD5); SAE J1850 CRC-8 (0x1D)
CRC_POLYS = {
    "CRC-8 802.16 HCS x8+x2+x+1": (8, 0x07), "CRC-5-USB": (5, 0x05), "CRC-16-CCITT": (16, 0x1021), "CRC-16-ANSI": (16, 0x8005),
    "CRC-32 IEEE 802.3": (32, 0x04C11DB7), "CRC-32C": (32, 0x1EDC6F41), "CRC-24 OpenPGP": (24, 0x864CFB), "CRC-8 DVB-S2": (8, 0xD5),
    "CRC-8 J1850": (8, 0x1D),
}

# source: GF(2^8) primitive polynomials: 0x11D RS(255,239) IEEE 802.16 / DVB, 0x11B AES (FIPS-197), 0x187 CCSDS RS(255,223)
GF_POLYS = (0x11D, 0x11B, 0x187)

# source: CCSDS 131.0-B / IEEE 802.16 / DVB K=7 (171,133 octal); GSM 05.03 K=5 (23,33); UMTS 25.212 K=9 (561,753); K=3 (7,5); NASA rate 1/3 K=7 (171,133,165)
CONV_KNOWN = (("K7 171/133", 7, (0o171, 0o133)), ("K5 23/33", 5, (0o23, 0o33)), ("K9 561/753", 9, (0o561, 0o753)), ("K3 7/5", 3, (0o7, 0o5)),
              ("K7 r1/3 171/133/165", 7, (0o171, 0o133, 0o165)))


def _bits(m):
    while m:
        low = m & -m
        yield low.bit_length() - 1
        m ^= low


def _par(x):
    return x.bit_count() & 1


# ---- GF(2) linear algebra (rows = ints, bit j of row i = A[i][j]) ---------------------------------------------------------------------------
def rank(rows):
    piv, r = {}, 0
    for v in rows:
        while v:
            h = v.bit_length() - 1
            if h in piv:
                v ^= piv[h]
            else:
                piv[h] = v
                r += 1
                break
    return r


def matvec(rows, v):
    out = 0
    for i, row in enumerate(rows):
        out |= _par(row & v) << i
    return out


def matmul(a, b):
    out = []
    for row in a:
        r = 0
        for j in _bits(row):
            r ^= b[j]
        out.append(r)
    return out


def charpoly(rows):
    """Characteristic polynomial of the n x n GF(2) matrix: int, bit k = coefficient of x^k (monic, degree n).  Krylov chains over a growing
    invariant subspace; each chain contributes the minimal polynomial of its generator in the quotient."""
    n = len(rows)
    piv = {}                                         # pivot bit -> (vector, tag); tag bit j = coefficient of A^j e_i
    poly = 1
    for i in range(n):
        e = 1 << i
        v = e
        while v:                                     # skip e_i already inside the span
            h = v.bit_length() - 1
            if h in piv:
                v ^= piv[h][0]
            else:
                break
        if not v:
            continue
        vec, k = e, 0
        while True:
            r, tag = vec, 1 << k
            while r:
                h = r.bit_length() - 1
                if h in piv:
                    r ^= piv[h][0]
                    tag ^= piv[h][1]
                else:
                    break
            if not r:
                poly = clmul(poly, tag)
                break
            piv[r.bit_length() - 1] = (r, tag)
            vec, k = matvec(rows, vec), k + 1
    return poly


def clmul(a, b):
    out = 0
    while b:
        low = b & -b
        out ^= a << (low.bit_length() - 1)
        b ^= low
    return out


def companion(poly):
    n = poly.bit_length() - 1
    return [((1 << (i - 1)) if i else 0) | ((1 << (n - 1)) if (poly >> i) & 1 else 0) for i in range(n)]


def reciprocal(poly):
    n = poly.bit_length() - 1
    return sum(((poly >> k) & 1) << (n - k) for k in range(n + 1))


def poly_of(exps):
    return sum(1 << e for e in exps)


def poly_str(p):
    return "+".join(("1" if k == 0 else "x" if k == 1 else f"x{k}") for k in range(p.bit_length() - 1, -1, -1) if (p >> k) & 1)


_POW_CACHE = {}


def powers_charpoly(poly):
    """{w: charpoly(M^w)} for w = 1..MAX_W, M = companion(poly)."""
    got = _POW_CACHE.get(poly)
    if got is None:
        m = companion(poly)
        cur, got = m, {1: poly}
        for w in range(2, MAX_W + 1):
            cur = matmul(cur, m)
            got[w] = charpoly(cur)
        _POW_CACHE[poly] = got
    return got


def known_polys():
    out = {name: poly_of(e) for name, e in LFSR_POLYS.items()}
    out.update({name: (1 << n) | low for name, (n, low) in CRC_POLYS.items()})
    return out


def match_known(cp, n):
    """{(name, orientation): [w, ...]} for every known polynomial of degree n whose M^w has characteristic polynomial cp.
    w and 2w give the same polynomial (Frobenius), so the data width is read from the input count, not from w alone."""
    hits = collections.defaultdict(list)
    for name, p in known_polys().items():
        if p.bit_length() - 1 != n:
            continue
        for orient, q in (("direct", p), ("reciprocal", reciprocal(p))):
            for w, c in powers_charpoly(q).items():
                if c == cp:
                    hits[(name, orient)].append(w)
    return dict(hits)


def _pmulmod(a, b, m, n):
    r = 0
    while b:
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
        if (a >> n) & 1:
            a ^= m
    return r


def _ppow(x, e, m, n):
    r = 1
    while e:
        if e & 1:
            r = _pmulmod(r, x, m, n)
        x = _pmulmod(x, x, m, n)
        e >>= 1
    return r


def _factor(v):
    out, d = [], 2
    while d * d <= v and d < 1 << 22:
        while v % d == 0:
            out.append(d)
            v //= d
        d += 1 if d == 2 else 2
    if v > 1:
        out.append(v)
    return sorted(set(out)) if all(_is_prime(q) for q in set(out)) else None


def _is_prime(v):
    if v < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if v % p == 0:
            return v == p
    d, s = v - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        x = pow(a, d, v)
        if x in (1, v - 1):
            continue
        for _ in range(s - 1):
            x = x * x % v
            if x == v - 1:
                break
        else:
            return False
    return True


def is_primitive(p):
    """True / False / None (None: n > PRIM_MAX_N or 2^n - 1 not fully factored).  x has order 2^n - 1 modulo p <=> p primitive."""
    n = p.bit_length() - 1
    if n < 2 or n > PRIM_MAX_N or not p & 1:
        return False if n >= 2 else None
    N = (1 << n) - 1
    fs = _factor(N)
    if fs is None:
        return None
    if _ppow(2, N, p, n) != 1:
        return False
    return all(_ppow(2, N // q, p, n) != 1 for q in fs)


# ---- canonical form of an 8x8 GF(2) matrix under row and column permutations ----------------------------------------------------------------
def canon(rows, ncols):
    cols = [sum(((r >> j) & 1) << i for i, r in enumerate(rows)) for j in range(ncols)]
    col = [c.bit_count() for c in cols]
    row = [r.bit_count() for r in rows]
    for _ in range(4):
        row = [(row[i], tuple(sorted(col[j] for j in _bits(rows[i])))) for i in range(len(rows))]
        col = [(col[j], tuple(sorted(row[i] for i in _bits(cols[j])))) for j in range(ncols)]
        rk = {v: k for k, v in enumerate(sorted(set(row)))}
        ck = {v: k for k, v in enumerate(sorted(set(col)))}
        row, col = [rk[v] for v in row], [ck[v] for v in col]
    cells = collections.defaultdict(list)
    for j, c in enumerate(col):
        cells[c].append(j)
    order = [cells[c] for c in sorted(cells)]
    best = None
    for perms in itertools.product(*(itertools.permutations(c) for c in order)):
        seq = [j for p in perms for j in p]
        key = tuple(sorted(sum(((r >> j) & 1) << k for k, j in enumerate(seq)) for r in rows))
        if best is None or key < best:
            best = key
    return best


def gf_mul_matrix(c, poly):
    """Rows of x -> c * x in GF(2^8) mod poly, polynomial basis (bit i of x = coefficient of a^i)."""
    cols = []
    for j in range(8):
        x = c
        for _ in range(j):
            x <<= 1
            if x & 0x100:
                x ^= poly
        cols.append(x)
    return [sum(((cols[j] >> i) & 1) << j for j in range(8)) for i in range(8)]


_GF_TABLE = {}


def gf_table():
    if not _GF_TABLE:
        for poly in GF_POLYS:
            for c in range(1, 256):
                _GF_TABLE.setdefault(canon(gf_mul_matrix(c, poly), 8), []).append((poly, c))
    return _GF_TABLE


# ---- the design view ------------------------------------------------------------------------------------------------------------------------
class Design:
    def __init__(self, nl):
        self.nl = nl
        self.lut = {L["name"]: L for L in nl.luts}
        self.ff = {F["name"]: F for F in nl.ffs}
        self.leaf_idx, self.leaf_names = {}, []
        self._aff, self._open, self._comb_c, self._eff_c, self.gates = {}, set(), {}, {}, {}
        self.fan = collections.Counter()
        for L in nl.luts:
            for p in L["pins"]:
                self.fan[p] += 1
        for F in nl.ffs:
            for k in ("d", "clk", "ena", "aclr", "sclr", "sload", "asdata"):
                if F.get(k):
                    self.fan[F[k]] += 1
        for io in nl.ios:
            for k in ("drv", "oe"):
                if io.get(k):
                    self.fan[io[k]] += 1
        for m in nl.m9k:
            for s in (m.get("data") or []) + (m.get("addr") or []) + [m.get("we"), m.get("clk")]:
                if s:
                    self.fan[s] += 1
        for m in nl.mac:
            for s in m["a"] + m["b"] + m["sign"] + [m.get("clk"), m.get("ena"), m.get("aclr")]:
                if s:
                    self.fan[s] += 1
        self.clocked = [F for F in nl.ffs if F["clk"] is not None and F["d"] is not None]

    # signals -----
    @staticmethod
    def kind(s):
        if s in CONSTV:
            return "const"
        return LEAF_PREFIX.get(s.split("_", 1)[0], "other")

    def leaf(self, s):
        i = self.leaf_idx.get(s)
        if i is None:
            i = self.leaf_idx[s] = len(self.leaf_names)
            self.leaf_names.append(s)
        return i

    def gkey(self, F):
        return (F["clk"], bool(F.get("clk_inv")), F.get("ena"), bool(F.get("ena_inv")))

    def comb(self, s):
        """(S mask over uniq, const, uniq pins, tt) for a non-carry LUT output; None for any leaf."""
        got = self._comb_c.get(s, 0)
        if got != 0:
            return got
        L = self.lut.get(s) if s.startswith("lc_") else None
        if L is None or L["mode"] == "cin":
            self._comb_c[s] = None
            return None
        uniq, pm = [], []
        for p in L["pins"]:
            if p in CONSTV:
                pm.append((1, CONSTV[p]))
            else:
                if p not in uniq:
                    uniq.append(p)
                pm.append((0, uniq.index(p)))
        k, init, tt = len(uniq), L["init"], 0
        for idx in range(1 << k):
            a = [(v if c else (idx >> v) & 1) for c, v in pm]
            tt |= ((init >> (a[0] | a[1] << 1 | a[2] << 2 | a[3] << 3)) & 1) << idx
        c, S = tt & 1, 0
        for j in range(k):
            if ((tt >> (1 << j)) & 1) ^ c:
                S |= 1 << j
        lin = all(((tt >> idx) & 1) == c ^ _par(idx & S) for idx in range(1 << k))
        res = (S if lin else None, c, uniq, tt)
        self._comb_c[s] = res
        return res

    def eff(self, s):
        """(S, const, uniq, gate) for a LUT: affine as is (gate None), or `G(gate pins) ? constant : affine(rest)` with 1..3 control-like gate pins
        (each read by >= GATE_FAN pins): sync clear / set / load / enable conditions."""
        got = self._eff_c.get(s, 0)
        if got != 0:
            return got
        cb = self.comb(s)
        res = None
        if cb is not None:
            S, c, u, tt = cb
            if S is not None:
                res = (S, c, u, None)
            else:
                k, best = len(u), None
                ctl = [j for j in range(k) if self.fan[u[j]] >= GATE_FAN]
                for size in (1, 2, 3):
                    for gp in itertools.combinations(ctl, size):
                        rest = [j for j in range(k) if j not in gp]
                        if not rest:
                            continue
                        cofs = {}
                        for g in range(1 << size):
                            idx0 = sum(((g >> t) & 1) << gp[t] for t in range(size))
                            cofs[g] = tuple((tt >> (idx0 | sum(((r >> t) & 1) << rest[t] for t in range(len(rest))))) & 1 for r in range(1 << len(rest)))
                        vals = set(cofs.values())
                        const = [v for v in vals if len(set(v)) == 1]
                        aff_ = [v for v in vals if len(set(v)) > 1]
                        if len(vals) != 2 or len(const) != 1 or len(aff_) != 1:
                            continue
                        a0 = aff_[0]
                        c2 = a0[0]
                        S2r = sum(1 << t for t in range(len(rest)) if a0[1 << t] ^ c2)
                        if all(a0[r] == c2 ^ _par(r & S2r) for r in range(1 << len(rest))):
                            S2 = sum(1 << rest[t] for t in _bits(S2r))
                            key = (len(rest), -size, sum(self.fan[u[j]] for j in gp))
                            if best is None or key > best[0]:
                                best = (key, S2, c2, tuple(sorted(u[j] for j in gp)))
                if best is not None:
                    res = (best[1], best[2], u, best[3])
        self._eff_c[s] = res
        return res

    def aff(self, sig):
        """(leaf mask, const) of `sig` over the region where every gate is active (sync clear / set / load conditions idle); None if not affine.
        Gates met on the cone are collected in self.gates[sig]."""
        memo = self._aff
        if sig in memo:
            return memo[sig]
        stack = [sig]
        while stack:
            s = stack[-1]
            if s in memo:
                stack.pop()
                continue
            cb = self.comb(s)
            if cb is None:
                memo[s] = (0, CONSTV[s]) if s in CONSTV else (1 << self.leaf(s), 0)
                stack.pop()
                continue
            e = self.eff(s)
            if e is None:
                memo[s] = None
                stack.pop()
                continue
            S, c, uniq, gate = e
            need = [uniq[j] for j in _bits(S)]
            pend = [u for u in need if u not in memo]
            if pend:
                if s in self._open:
                    memo[s] = None
                    stack.pop()
                    continue
                self._open.add(s)
                stack.extend(pend)
                continue
            mask, cc = 0, c
            gs = {gate} if gate else set()
            for u in need:
                f = memo[u]
                if f is None:
                    mask = None
                    break
                mask ^= f[0]
                cc ^= f[1]
                gs |= self.gates.get(u, set())
            memo[s] = None if mask is None else (mask, cc)
            if mask is not None and gs:
                self.gates[s] = gs
            self._open.discard(s)
            stack.pop()
        return memo[sig]

    def gate_aff(self, sig, own):
        """LUT = gate ? affine(x) : inactive, with `inactive` a constant (sync clear / seed) or the register's own Q (hold): -> ((mask, const), (gate signal, active level, inactive))."""
        cb = self.comb(sig)
        if cb is None or cb[0] is not None:
            return None
        _S, _c, u, tt = cb
        k = len(u)
        best = None
        for j in range(k):
            for v in (0, 1):
                inact = [(tt >> i) & 1 for i in range(1 << k) if ((i >> j) & 1) != v]
                act = [i for i in range(1 << k) if ((i >> j) & 1) == v]
                i0 = act[0]
                c2 = (tt >> i0) & 1
                S2 = sum(1 << b for b in range(k) if b != j and ((tt >> (i0 | (1 << b))) & 1) ^ c2)
                if not all(((tt >> i) & 1) == c2 ^ _par(i & S2) for i in act):
                    continue
                if len(set(inact)) == 1:
                    ina = ("const", inact[0])
                elif own in u and all(((tt >> i) & 1) == ((i >> u.index(own)) & 1) for i in range(1 << k) if ((i >> j) & 1) != v):
                    ina = ("hold", None)
                else:
                    continue
                key = (self.fan[u[j]], -j)
                if best is None or key > best[0]:
                    best = (key, j, v, S2, c2, ina)
        if best is None:
            return None
        _k, j, v, S2, c2, ina = best
        mask, cc = 0, c2
        for b in _bits(S2):
            f = self.aff(u[b])
            if f is None:
                return None
            mask ^= f[0]
            cc ^= f[1]
        return (mask, cc), (u[j], v, ina)

    def support(self, sig, hops=0):
        """Leaf signals of the cone of `sig`, looking through `hops` register stages."""
        out, seen, stack = set(), set(), [sig]
        while stack:
            s = stack.pop()
            if s in seen or s in CONSTV:
                continue
            seen.add(s)
            cb = self.comb(s)
            if cb is None:
                out.add(s)
            else:
                stack.extend(cb[2])
        return out if hops == 0 else self._through_ffs(out, hops)

    def _through_ffs(self, leaves, hops):
        out, seen, stack = set(), set(), [(s, hops) for s in leaves]
        while stack:
            s, h = stack.pop()
            if (s, h) in seen:
                continue
            seen.add((s, h))
            F = self.ff.get(s)
            if F is not None and h > 0 and F["d"] is not None:
                stack.extend((u, h - 1) for u in self.support(F["d"], 0))
            else:
                out.add(s)
        return out

    def xy(self, names):
        pts = [(self.ff[n]["x"], self.ff[n]["y"]) for n in names if n in self.ff]
        if not pts:
            return None
        return (round(sum(p[0] for p in pts) / len(pts), 1), round(sum(p[1] for p in pts) / len(pts), 1))

    def clk_of(self, name):
        F = self.ff.get(name)
        return None if F is None else F["clk"]

    # ---- register affine forms and consumer index -----------------------------------------------------------------------------------------
    def prepare(self):
        self.faff, self.fgate = {}, {}
        for F in self.clocked:
            a = self.aff(F["d"])
            if a is not None and self.gates.get(F["d"]):
                self.fgate[F["name"]] = sorted(self.gates[F["d"]], key=str)[0]
            if a is None:
                g = self.gate_aff(F["d"], F["name"])
                if g is not None:
                    a, self.fgate[F["name"]] = g
            if a is not None:
                self.faff[F["name"]] = a
        self.consumers = collections.defaultdict(list)
        for n, (m, _c) in self.faff.items():
            if m.bit_count() <= CONSUMER_MASK_CAP:
                for j in _bits(m):
                    self.consumers[j].append(n)
        self.io_aff = {}
        for io in self.nl.ios:
            if io.get("drv") and io["dir"] == "output":
                a = self.aff(io["drv"])
                if a is not None:
                    self.io_aff[f"pad_{io['ball']}"] = a
                    for j in _bits(a[0]):
                        self.consumers[j].append(f"pad_{io['ball']}")
        self.ff_leaf = {self.leaf(n): n for n in self.ff}
        return self


# ---- SCC ------------------------------------------------------------------------------------------------------------------------------------
def sccs(nodes, succ):
    index, low, on, st, out, idx = {}, {}, set(), [], [], [0]
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(succ.get(root, ())))]
        index[root] = low[root] = idx[0]
        idx[0] += 1
        st.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = idx[0]
                    idx[0] += 1
                    st.append(w)
                    on.add(w)
                    work.append((w, iter(succ.get(w, ()))))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = st.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    out.append(comp)
    return out


# ---- (a)(b) LFSR / parallel LFSR / CRC -------------------------------------------------------------------------------------------------------
def lfsr_groups(D):
    gk = {n: D.gkey(D.ff[n]) for n in D.faff}
    preds, succ = {}, collections.defaultdict(list)
    for n, (m, _c) in D.faff.items():
        ps = []
        for j in _bits(m):
            f = D.ff_leaf.get(j)
            if f is not None and f in D.faff and gk[f] == gk[n]:
                ps.append(f)
                succ[f].append(n)
        preds[n] = ps
    res = []
    for comp in sccs(list(D.faff), succ):
        n = len(comp)
        if n < MIN_SCC or n > MAX_SCC:
            continue
        res.append(analyse_scc(D, comp))
    return [r for r in res if r]


def analyse_scc(D, comp):
    n = len(comp)
    ix = {f: i for i, f in enumerate(comp)}
    smask = sum(1 << D.leaf(f) for f in comp)
    rows, T, ext_all, cs = [], [], 0, 0
    for f in comp:
        m, c = D.faff[f]
        row = 0
        t = []
        for j in _bits(m & smask):
            k = ix[D.ff_leaf[j]]
            row |= 1 << k
            t.append(k)
        rows.append(row)
        T.append(t)
        ext_all |= m & ~smask
        cs += c
    ext = [D.leaf_names[j] for j in _bits(ext_all)]
    ext_per = [(D.faff[f][0] & ~smask).bit_count() for f in comp]
    outdeg = collections.Counter(j for t in T for j in t)
    xors = sum(1 for i in range(n) if len(T[i]) + (1 if ext_per[i] else 0) >= 2)
    if xors == 0:
        return None
    cp = charpoly(rows)
    rk = rank(rows)
    form, taps, order = _structure(n, T, ext_per, outdeg)
    rec = dict(n=n, form=form, taps=taps, rank=rk, charpoly=cp, poly=poly_str(cp), ext=len(ext), autonomous=not ext,
               ext_kinds=dict(collections.Counter(Design.kind(e) for e in ext)), xor_ffs=xors, const_ffs=cs,
               clk=D.ff[comp[0]]["clk"], xy=D.xy(comp), members=[comp[i] for i in order] if order else list(comp),
               ctl=_ctl_summary(D, comp), density=round(sum(len(t) for t in T) / n, 2))
    hits = match_known(cp, n) if rk == n else {}
    want = max(1, len(ext))
    rec["w"] = want
    rec["match"] = sorted((k[0], k[1]) for k, v in hits.items() if want in v)
    rec["match_other_w"] = sum(1 for k, v in hits.items() if want not in v)
    rec["primitive"] = is_primitive(cp) if rk == n else False
    if rk != n:
        rec["conf"] = "low"
    elif hits:
        rec["conf"] = "high" if n >= 7 else "medium"
    elif form in ("fibonacci", "galois") and rec["primitive"] and n >= 7:
        rec["conf"] = "high"
    elif form in ("fibonacci", "galois"):
        rec["conf"] = "medium"
    else:
        rec["conf"] = "low"
    rec["kind"] = ("lfsr" if form in ("fibonacci", "galois") and (not ext or ext_per.count(0) >= n - 1) else "parallel")
    if form == "ring":
        rec["kind"] = "ring"
    return rec


def _ctl_summary(D, comp):
    Fs = [D.ff[f] for f in comp]
    c = collections.Counter()
    c["ena"] = len({F.get("ena") for F in Fs if F.get("ena")})
    for k in ("aclr", "sclr", "sload"):
        c[k] = len({F.get(k) for F in Fs if F.get(k)})
    c["seed_const_ffs"] = sum(1 for F in Fs if F.get("sload") and (F.get("asdata") in CONSTV))
    c["gate"] = len({D.fgate[f] for f in comp if f in D.fgate})
    c["gated_ffs"] = sum(1 for f in comp if f in D.fgate)
    return dict(c)


def _structure(n, T, ext_per, outdeg):
    """-> (form, taps, path order).  fibonacci: all but one FF are straight shifts; galois: shifts plus taps from one tail FF."""
    link = [i for i in range(n) if len(T[i]) == 1 and not ext_per[i] and T[i][0] != i]
    if len(link) == n - 1:
        head = next(i for i in range(n) if i not in link)
        succ = {T[i][0]: i for i in link}
        if len(succ) == len(link):
            path, cur = [head], head
            while cur in succ and len(path) < n:
                cur = succ[cur]
                path.append(cur)
            if len(path) == n:
                pos = {f: p for p, f in enumerate(path)}
                taps = sorted(pos[j] for j in T[head])
                return ("ring" if len(taps) == 1 and not ext_per[head] else "fibonacci"), taps, path
    if not outdeg:
        return "linear", [], None
    L = max(outdeg, key=lambda j: outdeg[j])
    if outdeg[L] >= 2:
        pred, head = {}, []
        okk = True
        for i in range(n):
            rest = [j for j in T[i] if j != L]
            if len(rest) > 1:
                okk = False
                break
            if not rest:
                head.append(i)
            elif rest[0] in pred:
                okk = False
                break
            else:
                pred[rest[0]] = i
        if okk and len(head) == 1:
            path, cur = [head[0]], head[0]
            while cur in pred and len(path) < n:
                cur = pred[cur]
                path.append(cur)
            if len(path) == n and path[-1] == L:
                pos = {f: p for p, f in enumerate(path)}
                return "galois", sorted(pos[i] for i in range(n) if L in T[i]), path
    return "linear", [], None


def whitening(D, rec):
    """Autonomous group: consumers whose affine cone mixes group bits with outside leaves (additive scrambler) -> (consumers, distinct group bits used)."""
    members = set(rec["members"])
    smask = sum(1 << D.leaf(f) for f in members)
    cons, used = set(), 0
    for j in _bits(smask):
        for c in D.consumers.get(j, ()):
            if c in members:
                continue
            m = D.faff[c][0] if c in D.faff else D.io_aff[c][0]
            if m & ~smask:
                cons.add(c)
                used |= m & smask
    return len(cons), used.bit_count()


# ---- chains -----------------------------------------------------------------------------------------------------------------------------------
def shift_chains(D):
    """Straight FF chains: D of FF i is exactly the Q (possibly inverted) of FF j in the same clock / enable group, j has no other shift reader."""
    link = {}
    for n, (m, _c) in D.faff.items():
        if m.bit_count() == 1:
            j = m.bit_length() - 1
            f = D.ff_leaf.get(j)
            if f is not None and f != n and f in D.faff and D.gkey(D.ff[f]) == D.gkey(D.ff[n]):
                link[n] = f
    outs = collections.defaultdict(list)
    for i, j in link.items():
        outs[j].append(i)
    nxt = {j: v[0] for j, v in outs.items() if len(v) == 1}
    pv = {i: j for j, i in nxt.items()}
    chains, seen = [], set()
    for j in list(nxt):
        if j in pv:
            continue
        ch, cur = [j], j
        while cur in nxt and nxt[cur] not in seen and nxt[cur] not in ch:
            cur = nxt[cur]
            ch.append(cur)
        seen.update(ch)
        chains.append(ch)
    return chains, link


def loadable_chains(D):
    """FF i whose D LUT is a 2:1 mux (s ? b : a) with one data input a previous FF j of the same group -> chains linked by one shared select."""
    link = {}
    for F in D.clocked:
        cb = D.comb(F["d"])
        if cb is None or len(cb[2]) != 3:
            continue
        tt, u = cb[3], cb[2]
        for sel in range(3):
            a, b = [v for v in range(3) if v != sel]
            if all(((tt >> idx) & 1) == ((idx >> (b if (idx >> sel) & 1 else a)) & 1) for idx in range(8)):
                for d0, d1 in ((a, b), (b, a)):
                    j = u[d0]
                    if j in D.ff and j != F["name"] and D.gkey(D.ff[j]) == D.gkey(F):
                        link[F["name"]] = (j, u[sel], u[d1])
                break
    outs = collections.defaultdict(list)
    for i, (j, _sel, _p) in link.items():
        outs[j].append(i)
    nxt = {j: v[0] for j, v in outs.items() if len(v) == 1}
    pv = {i: j for j, i in nxt.items()}
    chains = []
    for j in nxt:
        if j in pv:
            continue
        sel = link[nxt[j]][1]
        ch, cur = [j], j
        while cur in nxt and nxt[cur] not in ch and link[nxt[cur]][1] == sel:
            cur = nxt[cur]
            ch.append(cur)
        chains.append((ch, sel))
    return chains


# ---- (c) convolutional encoders ---------------------------------------------------------------------------------------------------------------
def fir_xor(D, chains):
    """Feed-forward XOR of >= 3 positions of a straight chain (+ its input): self-synchronising descrambler / FIR over GF(2); tap exponents
    compared with the known LFSR / CRC polynomials (both orientations)."""
    known = {name: set(e) for name, e in LFSR_POLYS.items()}
    known.update({name: {k for k in range(n + 1) if k == n or k == 0 or (low >> k) & 1} for name, (n, low) in CRC_POLYS.items()})
    out = []
    for ch in chains:
        if len(ch) < 6:
            continue
        hm = D.faff[ch[0]][0]
        x = hm.bit_length() - 1 if hm.bit_count() == 1 else None
        window = [x] + [D.leaf(f) for f in ch] if x is not None else [D.leaf(f) for f in ch]
        wmask = sum(1 << j for j in window)
        pos = {j: p for p, j in enumerate(window)}
        seen = set()
        for j in window:
            for c in D.consumers.get(j, ()):
                if c in seen or c in ch:
                    continue
                seen.add(c)
                m = D.faff[c][0] if c in D.faff else D.io_aff[c][0]
                if m & ~wmask or m.bit_count() < 3:
                    continue
                ps = sorted(pos[j2] for j2 in _bits(m))
                exps = {ps[-1] - q for q in ps}
                rev = set(ps[i] - ps[0] for i in range(len(ps)))
                names = [nm for nm, e in known.items() if e in (exps, rev)]
                out.append(dict(taps=len(ps), span=ps[-1] - ps[0], match=names, chain=len(ch), conf="high" if names else "low", xy=D.xy(ch)))
    return out


def conv_encoders(D, chains):
    out = []
    for ch in chains:
        if len(ch) < CONV_MIN_CHAIN:
            continue
        head = ch[0]
        hm = D.faff[head][0]
        x = hm.bit_length() - 1 if hm.bit_count() == 1 else None
        window = [x] + [D.leaf(f) for f in ch] if x is not None else [D.leaf(f) for f in ch]
        wmask = sum(1 << j for j in window)
        pos = {j: p for p, j in enumerate(window)}
        cand = {}
        for j in window:
            for c in D.consumers.get(j, ()):
                if c in ch or c in cand:
                    continue
                m = D.faff[c][0] if c in D.faff else D.io_aff[c][0]
                if m & ~wmask or m.bit_count() < 2:
                    continue
                cand[c] = tuple(sorted(pos[j2] for j2 in _bits(m)))
        sets = sorted(set(cand.values()))
        sets = [s for s in sets if s and s[0] == 0 and len(s) >= 2] or sets
        if len(sets) < 2:
            continue
        k = max(s[-1] for s in sets) + 1
        gens = tuple(sum(1 << (k - 1 - p) for p in s) for s in sets)
        matches = []
        for name, kk, gset in CONV_KNOWN:
            if kk != k:
                continue
            fwd = set(gset)
            rev = {sum(((g >> b) & 1) << (k - 1 - b) for b in range(k)) for g in gset}
            if set(gens) >= fwd or set(gens) >= rev:
                matches.append(name)
        out.append(dict(k=k, outputs=len(sets), gens_octal=[oct(g) for g in gens], match=matches, chain=len(ch), has_input_leaf=x is not None,
                        conf="high" if matches else "medium", xy=D.xy(ch), clk=D.ff[ch[0]]["clk"]))
    return out


# ---- (d) GF(2^8) constant multipliers ---------------------------------------------------------------------------------------------------------
def gf_multipliers(D):
    outs = {}
    for n, (m, _c) in D.faff.items():
        if 1 <= m.bit_count() <= 8:
            outs[n] = m
    for n, (m, _c) in D.io_aff.items():
        if 1 <= m.bit_count() <= 8:
            outs[n] = m
    par = {}

    def find(a):
        while par.setdefault(a, a) != a:
            par[a] = par[par[a]]
            a = par[a]
        return a
    for n, m in outs.items():
        bs = list(_bits(m))
        for b in bs[1:]:
            par[find(bs[0])] = find(b)
        find(bs[0])
    comp = collections.defaultdict(list)
    for n, m in outs.items():
        comp[find(m.bit_length() - 1)].append(n)
    res = []
    tbl = None
    for root, names in comp.items():
        if len(names) != 8:
            continue
        leaves = sorted({j for n in names for j in _bits(outs[n])})
        if len(leaves) != 8:
            continue
        li = {j: i for i, j in enumerate(leaves)}
        rows = [sum(1 << li[j] for j in _bits(outs[n])) for n in names]
        if rank(rows) != 8:
            continue
        if all(r.bit_count() == 1 for r in rows):
            res.append(dict(kind="permutation", conf="low"))
            continue
        tbl = tbl or gf_table()
        cands = tbl.get(canon(rows, 8), [])
        res.append(dict(kind="gf_const_mult" if cands else "linear_8x8", candidates=[(hex(p), hex(c)) for p, c in cands], exact=len(cands) == 1,
                        conf="high" if cands else "low", leaf_kinds=dict(collections.Counter(Design.kind(D.leaf_names[j]) for j in leaves)),
                        xy=D.xy([n for n in names if n in D.ff])))
    return res


def _reduce(tt, u):
    """Truth table with the variables it does not depend on removed."""
    u = list(u)
    j = 0
    while j < len(u):
        k = len(u)
        if all(((tt >> i) & 1) == ((tt >> (i | (1 << j))) & 1) for i in range(1 << k) if not (i >> j) & 1):
            nt = 0
            n = 0
            for i in range(1 << k):
                if not (i >> j) & 1:
                    nt |= ((tt >> i) & 1) << n
                    n += 1
            tt = nt
            del u[j]
        else:
            j += 1
    return tt, u


# ---- constant comparators / sync words ---------------------------------------------------------------------------------------------------------
def conj_literals(D):
    """{signal: {leaf: required value}} for every LUT cone that is an AND of literals (one satisfying assignment); sub-cones are folded in
    when used positively (AND form, value 1) or as a single-zero OR form used at value 0."""
    one, zero = {}, {}

    def req(p, v, depth):
        sub = (one if v else zero)
        if D.comb(p) is not None and depth < 48:
            visit(p, depth + 1)
        return sub[p].items() if sub.get(p) else ((p, v),)

    def visit(s, depth=0):
        if s in one or s in zero:
            return
        one[s] = zero[s] = None
        cb = D.comb(s)
        if cb is None:
            return
        tt, u = _reduce(cb[3], cb[2])
        k = len(u)
        if not k:
            return
        for table, idx, want in ((one, tt.bit_length() - 1, tt.bit_count() == 1),
                                 (zero, ((~tt) & ((1 << (1 << k)) - 1)).bit_length() - 1, (tt.bit_count() == (1 << k) - 1))):
            if not want:
                continue
            lit, ok = {}, True
            for j, p in enumerate(u):
                for leaf, val in req(p, (idx >> j) & 1, depth):
                    if lit.setdefault(leaf, val) != val:
                        ok = False
            if ok:
                table[s] = lit
    for s in list(D.lut):
        if D.comb(s) is not None:
            visit(s)
    return {s: l for s, l in one.items() if l}


def sync_words(D, chains, counters_ff):
    memo = conj_literals(D)
    cand = {s: l for s, l in memo.items() if l and sum(1 for k in l if k.startswith("ff_")) >= SYNC_MIN}
    keep = []
    for s, l in sorted(cand.items(), key=lambda kv: -len(kv[1])):
        keys = frozenset(l)
        if not any(keys <= k for k, _s in keep):
            keep.append((keys, s))
    chain_of = {f: (i, p) for i, ch in enumerate(chains) for p, f in enumerate(ch)}
    out = []
    for keys, s in keep:
        ffl = [k for k in keys if k.startswith("ff_")]
        per = collections.Counter(chain_of[f][0] for f in ffl if f in chain_of)
        cn = sum(1 for f in ffl if f in counters_ff)
        src = "shift_chain" if per and per.most_common(1)[0][1] >= SYNC_MIN else "counter" if cn >= SYNC_MIN else "other"
        ones = sum(1 for k in keys if memo[s][k])
        contiguous = False
        if src == "shift_chain":
            ci = per.most_common(1)[0][0]
            ps = sorted(chain_of[f][1] for f in ffl if f in chain_of and chain_of[f][0] == ci)
            contiguous = ps == list(range(ps[0], ps[0] + len(ps)))
        out.append(dict(literals=len(keys), ff_literals=len(ffl), source=src, contiguous=contiguous, ones=ones, xy=D.xy(ffl),
                        conf="high" if src == "shift_chain" and contiguous else "medium"))
    return out


# ---- counters, M9K, MAC, CDC -------------------------------------------------------------------------------------------------------------------
def counters(D):
    """Carry-chain registers with self feedback.  -> (counters, comparator chains).
    counter: consecutive chain LEs whose sum LUT reads its own register (other operand constant, sum = XOR / XNOR of own Q and carry);
    accumulator: same, other operand a signal.  Bit 0 may sit outside the chain, so bit indices are relative to the chain."""
    order = {}
    for L in D.nl.luts:
        if L["mode"] == "cin" and L["cin"]:
            order.setdefault(L["cin"][3:], []).append(L)
    head = {L["name"]: L for L in D.nl.luts if L["mode"] == "cin"}
    chains, seen = [], set()
    for L in D.nl.luts:
        if L["mode"] != "cin" or L["name"] in seen:
            continue
        prev = head.get("lc_" + L["cin"][3:]) if L["cin"] else None
        if prev is not None and prev["mode"] == "cin":
            continue
        ch, cur = [L], L
        while True:
            nx = [m for m in order.get(cur["name"][3:], []) if m["name"] not in seen]
            if not nx:
                break
            cur = nx[0]
            ch.append(cur)
            seen.add(cur["name"])
        seen.add(L["name"])
        chains.append(ch)
    ctr, cmp_ = [], []
    for ch in chains:
        runs, run = [], []
        for L in ch:
            own = f"ff_{L['x']}_{L['y']}_{L['le']}"
            F = D.ff.get(own)
            if F is not None and F["d"] == L["name"] and own in L["pins"] and L["pins"][2] == L["cin"]:
                run.append((L, own))
            else:
                if run:
                    runs.append(run)
                run = []
        if run:
            runs.append(run)
        for r in runs:
            if len(r) < 3:
                continue
            others = [p for L, own in r for i, p in enumerate(L["pins"]) if i != 2 and p != own]
            kind = "counter" if all(p in CONSTV for p in others) else "accumulator"
            ffs = [own for _L, own in r]
            src = D.lut.get("lc_" + r[0][0]["cin"][3:]) if r[0][0] is ch[0] and r[0][0]["cin"] else None
            low = [p for p in (src["pins"] if src and src["mode"] != "cin" else []) if p in D.ff and p not in ffs and D.ff[p]["d"] and p in D.support(D.ff[p]["d"])]
            if kind == "counter" and low:
                lowset = set(low)
                low.sort(key=lambda f: len(D.support(D.ff[f]["d"]) & (lowset - {f})))
                ffs = low + ffs
            ctr.append(dict(ffs=ffs, width=len(ffs), kind=kind, low_bits=len(low) if kind == "counter" else 0))
        ffp = [(L["pins"][0], L["pins"][1]) for L in ch if L["pins"][0] in D.ff and L["pins"][1] in D.ff and L["pins"][0] != f"ff_{L['x']}_{L['y']}_{L['le']}"]
        if len(ffp) >= 3:
            cmp_.append(dict(pairs=ffp, width=len(ffp)))
    return ctr, cmp_


def cone_tt(D, sig, leaves):
    """Truth table (bit-parallel int over `leaves`) of the cone of `sig`; leaves must cover its support."""
    k = len(leaves)
    full = (1 << (1 << k)) - 1
    memo = {s: sum(1 << i for i in range(1 << k) if (i >> j) & 1) for j, s in enumerate(leaves)}
    memo["1'b0"], memo["1'b1"] = 0, full
    stack = [sig]
    while stack:
        s = stack[-1]
        if s in memo:
            stack.pop()
            continue
        L = D.lut[s]
        pend = [p for p in L["pins"] if p not in memo]
        if pend:
            stack.extend(pend)
            continue
        v = [memo[p] for p in L["pins"]]
        out = 0
        for idx in range(16):
            if (L["init"] >> idx) & 1:
                t = full
                for b in range(4):
                    t &= v[b] if (idx >> b) & 1 else ~v[b] & full
                out |= t
        memo[s] = out
        stack.pop()
    return memo[sig]


def lut_counters(D, known):
    """Binary up-counters built from plain LUTs (bit i toggles when all lower bits are 1): nested FF supports {f_0..f_i}, <= 3 extra (enable) leaves,
    exact function check: for every enable assignment the cone is count, hold or clear, and some assignment counts on every bit."""
    sup = {}
    for F in D.clocked:
        n = F["name"]
        if n in known:
            continue
        s = D.support(F["d"], 0)
        ffs = frozenset(x for x in s if x in D.ff)
        ext = sorted(x for x in s if x not in D.ff)
        if n in ffs and len(ffs) <= 12 and len(ext) <= 3 and all(x not in CONSTV for x in ext) and all(x in D.lut or x in D.ff or x[:4] in ("pad_", "u_cl") or x.startswith("u_") for x in ext):
            sup[n] = (ffs, tuple(ext))
    rest = collections.defaultdict(list)
    for n, (s, _e) in sup.items():
        rest[s - {n}].append(n)
    out = []
    for f0 in [n for n, (s, _e) in sup.items() if len(s) == 1]:
        bits, cur = [f0], frozenset([f0])
        while True:
            nx = [g for g in rest.get(cur, []) if g not in cur and D.gkey(D.ff[g])[:2] == D.gkey(D.ff[f0])[:2]]
            if len(nx) != 1:
                break
            bits.append(nx[0])
            cur = cur | {nx[0]}
        if len(bits) < 3:
            continue
        E = sorted({x for f in bits for x in sup[f][1]})
        if len(E) > 3 or any(D.comb(x) is not None for x in E):
            continue
        ok, enable_sets = True, None
        for i, f in enumerate(bits):
            k = i + 1
            leaves = bits[:k] + E
            tt = cone_tt(D, D.ff[f]["d"], leaves)
            good = set()
            for e in range(1 << len(E)):
                sub = [(tt >> (idx | (e << k))) & 1 for idx in range(1 << k)]
                count = [((idx >> i) & 1) ^ (1 if (idx & ((1 << i) - 1)) == (1 << i) - 1 else 0) for idx in range(1 << k)]
                hold = [(idx >> i) & 1 for idx in range(1 << k)]
                zero = [0] * (1 << k)
                if sub in (count, [1 - c for c in count]):
                    good.add(e)
                elif sub not in (hold, [1 - h for h in hold], zero, [1] * (1 << k)):
                    ok = False
            enable_sets = good if enable_sets is None else enable_sets & good
            if not ok or not enable_sets:
                ok = False
                break
        if ok:
            out.append(dict(ffs=bits, width=len(bits), kind="counter", low_bits=0, lut_built=True))
    return out


def m9k_addresses(D, ctr):
    cmap = {}
    for ci, c in enumerate(ctr):
        for bi, f in enumerate(c["ffs"]):
            cmap[f] = (ci, bi)
    res = []
    for m in D.nl.m9k:
        if not m.get("modelled"):
            res.append(dict(modelled=False))
            continue
        rom = m["we"] == "1'b0"
        bits, other, perm, rot = [], 0, None, False
        for a in m["addr"]:
            if a in CONSTV:
                bits.append(None)
                continue
            sup = set()
            for leaf in D.support(a, 0):
                sup |= {leaf} if (leaf in cmap or leaf not in D.ff) else D.support(D.ff[leaf]["d"], 0)
            cs = {cmap[s] for s in sup if s in cmap}
            other += sum(1 for s in sup if s not in cmap)
            bits.append(cs)
        live = [b for b in bits if b is not None]
        cids = {ci for b in live for ci, _bi in b}
        if not live:
            cls = "constant"
        elif other or not cids:
            cls = "other" if not cids else "counter_plus_other"
        elif len(cids) == 1 and all(len(b) == 1 for b in live):
            perm = [next(iter(b))[1] for b in live]
            if len(set(perm)) != len(perm):
                cls = "counter_function"
            else:
                d = {(p - k) for k, p in enumerate(perm)}
                cls = "counter_identity" if len(d) == 1 else "counter_bit_permutation"
                rot = len({(p - k) % len(perm) for k, p in enumerate(perm)}) == 1 and sorted(perm) == list(range(min(perm), min(perm) + len(perm)))
        elif len(cids) == 1:
            cls = "counter_function"
        else:
            cls = "counters_function"
        res.append(dict(modelled=True, rom=rom, cls=cls, perm=perm if cls == "counter_bit_permutation" else None, rotation=bool(cls == "counter_bit_permutation" and rot), addr_bits=len(live), xy=(m["x"], m["y"]), words=1 << m["A"], width=m["W"], clk=m["clk"]))
    return res


def m9k_buses(D, ctr):
    """Modelled M9Ks grouped by identical address bus: sharing count, address bits, and the FF / pad / other leaves of the bus cones."""
    cmap = {f: ci for ci, c in enumerate(ctr) for f in c["ffs"]}
    groups = collections.defaultdict(list)
    for m in D.nl.m9k:
        if m.get("modelled"):
            groups[tuple(m["addr"])].append(m)
    out = []
    for addr, ms in groups.items():
        sup = set()
        for a in addr:
            sup |= D.support(a, 0)
        ffs = [x for x in sup if x in D.ff]
        out.append(dict(m9k=len(ms), bits=sum(1 for a in addr if a not in CONSTV), counters=len({cmap[f] for f in ffs if f in cmap}),
                        counter_ffs=sum(1 for f in ffs if f in cmap), other_ffs=sum(1 for f in ffs if f not in cmap),
                        pads=sum(1 for x in sup if x.startswith("pad_")), srcs=sum(1 for x in sup if not x.startswith(("ff_", "pad_", "lc_"))),
                        widths=sorted({m["W"] for m in ms}), we_distinct=len({m["we"] for m in ms}), words=1 << ms[0]["A"]))
    return out


def mac_roms(D, m9k_res):
    idx = {(m["x"], m["y"]): i for i, m in enumerate(D.nl.m9k)}
    out = []
    for mac in D.nl.mac:
        srcs = {"a": set(), "b": set()}
        for side in ("a", "b"):
            for s in mac[side]:
                if s in CONSTV:
                    continue
                for leaf in D.support(s, 1):
                    if leaf.startswith("m9k_"):
                        x, y = leaf.split("_")[1:3]
                        srcs[side].add((int(x), int(y)))
        ms = srcs["a"] | srcs["b"]
        rom_ctr = [mm for mm in ms if mm in idx and m9k_res[idx[mm]].get("modelled") and m9k_res[idx[mm]]["rom"]
                   and m9k_res[idx[mm]]["cls"].startswith("counter")]
        out.append(dict(m9k_a=len(srcs["a"]), m9k_b=len(srcs["b"]), m9k=sorted(ms), rom_counter=len(rom_ctr), xy=(mac["x"], mac["y"])))
    return out


def cdc(D, chains, ctr, cmp_):
    clk = lambda n: D.ff[n]["clk"]
    syncs = []
    for ch in chains:
        h = ch[0]
        if len(ch) < 2 or D.fan[h] != 1:
            continue
        m = D.faff[h][0]
        src = D.ff_leaf.get(m.bit_length() - 1) if m.bit_count() == 1 else None
        if src is not None and clk(src) != clk(h):
            syncs.append((clk(src), clk(h), "ff", len(ch)))
        elif src is None and m.bit_count() == 1 and D.leaf_names[m.bit_length() - 1].startswith("pad_"):
            syncs.append((None, clk(h), "pad", len(ch)))
    cross = collections.Counter()
    for n, (m, _c) in D.faff.items():
        for j in _bits(m):
            f = D.ff_leaf.get(j)
            if f is not None and clk(f) != clk(n):
                cross[(clk(f), clk(n))] += 1
    cmap = {f: (ci, bi) for ci, c in enumerate(ctr) for bi, f in enumerate(c["ffs"])}
    gray = collections.defaultdict(set)
    for n, (m, _c) in D.faff.items():
        if n in cmap:
            continue
        bs = [cmap[D.ff_leaf[j]] for j in _bits(m) if j in D.ff_leaf and D.ff_leaf[j] in cmap]
        if len(bs) == 2 and m.bit_count() == 2 and bs[0][0] == bs[1][0] and abs(bs[0][1] - bs[1][1]) == 1:
            gray[bs[0][0]].add(n)
    ptr = []
    for c in cmp_:
        cc, bus, both = collections.Counter(), [], 0
        for x, y in c["pairs"]:
            if x in cmap and y in cmap:
                both += 1
            elif x in cmap or y in cmap:
                cc[cmap[x][0] if x in cmap else cmap[y][0]] += 1
                bus.append(y if x in cmap else x)
        if cc and sum(cc.values()) >= 3 and len(cc) == 1:
            cid = next(iter(cc))
            ptr.append(dict(width=c["width"], kind="counter_vs_bus", same_clk={clk(f) for f in bus} == {clk(ctr[cid]["ffs"][0])}))
        elif both >= 3:
            ptr.append(dict(width=c["width"], kind="counter_counter", same_clk=None))
    return dict(syncs=syncs, cross={f"{a}>{b}": v for (a, b), v in cross.items()}, gray={k: len(v) for k, v in gray.items()}, pointer_compares=ptr)


# ---- driver ---------------------------------------------------------------------------------------------------------------------------------------
def detect(nl):
    D = Design(nl).prepare()
    res = {"design": dict(luts=len(nl.luts), ffs=len(nl.ffs), affine_ffs=len(D.faff), m9k=len(nl.m9k), mac=len(nl.mac),
                          clk_domains=len({F["clk"] for F in D.clocked}))}
    groups = lfsr_groups(D)
    by_name = set()
    for g in groups:
        g["whiten_consumers"], g["whiten_bits"] = whitening(D, g) if g["autonomous"] else (0, 0)
        by_name.update(g["members"])
    res["lfsr"] = [g for g in groups if g["kind"] == "lfsr"]
    res["parallel"] = [g for g in groups if g["kind"] == "parallel"]
    res["ring"] = [g for g in groups if g["kind"] == "ring"]
    chains, _link = shift_chains(D)
    res["shift"] = dict(plain=[dict(n=len(c), clk=D.ff[c[0]]["clk"], xy=D.xy(c), in_lfsr=all(f in by_name for f in c)) for c in chains if len(c) >= SHIFT_MIN],
                        loadable=[dict(n=len(c), xy=D.xy(c)) for c, _s in loadable_chains(D) if len(c) >= SHIFT_MIN])
    res["conv"] = conv_encoders(D, [c for c in chains if not all(f in by_name for f in c)])
    res["fir"] = fir_xor(D, [c for c in chains if not all(f in by_name for f in c)])
    res["gfmul"] = gf_multipliers(D)
    ctr, cmp_ = counters(D)
    ctr += lut_counters(D, {f for c in ctr for f in c["ffs"]})
    res["counters"] = ctr
    res["syncword"] = sync_words(D, chains, {f for c in ctr for f in c["ffs"]})
    m9 = m9k_addresses(D, ctr)
    res["m9k_addr"] = m9
    res["m9k_buses"] = m9k_buses(D, ctr)
    res["mac_rom"] = mac_roms(D, m9)
    res["cdc"] = cdc(D, chains, ctr, cmp_)
    return res


def summary(res):
    """Counts only (no polynomials, no coordinates, no signal names)."""
    s = collections.OrderedDict()
    s.update(res["design"])
    for key in ("lfsr", "parallel", "ring"):
        g = res[key]
        s[key] = len(g)
        s[key + "_by_conf"] = dict(collections.Counter(x["conf"] for x in g))
        s[key + "_matched_known"] = sum(1 for x in g if x["match"])
        s[key + "_by_form"] = dict(collections.Counter(x["form"] for x in g))
        s[key + "_by_n"] = dict(sorted(collections.Counter(x["n"] for x in g).items()))
    s["lfsr_autonomous"] = sum(1 for x in res["lfsr"] if x["autonomous"])
    s["lfsr_with_whitening_consumers"] = sum(1 for x in res["lfsr"] if x.get("whiten_consumers"))
    s["shift_chains"] = len(res["shift"]["plain"])
    s["shift_chains_ge8"] = sum(1 for c in res["shift"]["plain"] if c["n"] >= 8)
    s["shift_loadable"] = len(res["shift"]["loadable"])
    s["conv"] = len(res["conv"])
    s["conv_matched_known"] = sum(1 for c in res["conv"] if c["match"])
    s["fir_xor"] = len(res["fir"])
    s["fir_xor_matched_known"] = sum(1 for x in res["fir"] if x["match"])
    s["gfmul"] = collections.Counter(x["kind"] for x in res["gfmul"])
    s["counters"] = collections.Counter(c["kind"] for c in res["counters"])
    s["syncword"] = collections.Counter(x["source"] for x in res["syncword"])
    s["m9k_modelled"] = sum(1 for x in res["m9k_addr"] if x["modelled"])
    s["m9k_addr_classes"] = collections.Counter(x["cls"] for x in res["m9k_addr"] if x["modelled"])
    s["m9k_address_buses"] = len(res["m9k_buses"])
    s["m9k_largest_shared_buses"] = sorted((b["m9k"] for b in res["m9k_buses"]), reverse=True)[:6]
    s["macs_both_operands_m9k"] = sum(1 for x in res["mac_rom"] if x["m9k_a"] and x["m9k_b"])
    s["macs_with_m9k_operand"] = sum(1 for x in res["mac_rom"] if x["m9k"])
    s["macs_with_counter_rom_operand"] = sum(1 for x in res["mac_rom"] if x["rom_counter"])
    c = res["cdc"]
    s["sync_chains"] = collections.Counter(k[2] for k in c["syncs"])
    s["cross_domain_ff_edges"] = sum(c["cross"].values())
    s["gray_registers"] = len(c["gray"])
    s["pointer_compares"] = len(c["pointer_compares"])
    return dict(s)
