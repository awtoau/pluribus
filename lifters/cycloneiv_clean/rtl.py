"""Cyclone IV clean pipeline: flat netlist -> structured RTL (#165).

Input: the `emit.Netlist` (LUT / FF / IO / block records).  Output: Verilog with recovered constructs, each tagged `[R:<rule>]`.
Structure only: no names exist in the bitstream, so names are generated (io_<ball>, r_<n>, sr_<n>, st_<n>, w_<n>, bus_<n>, add_<n>, mem_<n>).
Anything not recognised stays in the flat LUT form (rule FLAT_LUT); nothing is guessed.  Every recovered construct is exact (truth-table
self-check at emit time).  Threads only, no state outside the Lift object.

Rules (id: recovered construct)
  ADD / SUB / ADDC / CMP_GE / CMP_GT / CARRY   carry chain operand buses + width (chain bit = full adder over operand bits, polarity per operand)
  CNT_UP / CNT_DOWN                            chain whose operand A is the register it feeds and operand B is constant
  REG / REG_CHAIN / SHIFT                      FF bundles sharing clock / enable / clears (one always block); chain-fed register; shift register
  MUX<n> / XOR / SOP / TT / CONST / BUF / INV  LUT cones (single-fanout LUT trees, <= MAXL leaves) simplified by exact minimisation
  FSM                                          strongly connected FF group with a small state/input support, as case statement
  M9K / MAC / IO                               blocks passed through from the emit text (names rewritten); pads io_<ball>
  FLAT_LUT                                     LUT of an unrecognised carry chain, kept as INIT-indexed assign
"""
import collections
import itertools
import re

from . import emit as _emit

_FLAT_VERILOG = _emit.verilog      # captured at import: callers may substitute emit.verilog (rtl_check --vo)

UNC = "1'b1"                              # emit.UNCONNECTED
# source: emit.py constant-signal spellings (UNCONNECTED, FF control idle values)
CONSTV = {"1'b1": 1, "1'b0": 0}
MAXL = 6                                  # decision: cone leaf cap = 6 (64-bit truth table; readable SOP); counts per design in the stats
SOP_LIT_MAX = 16                          # decision: SOP above this many literals prints as an indexed truth table (rule TT)
FSM_STATE_MAX = 24                        # decision: state register width cap (one-hot FSMs up to 24 states)
FSM_REACH_MAX = 64                        # decision: reachable-state cap
FSM_STATE_INPUT_MAX = 10                  # decision: inputs one state's next-state cone may depend on (2^10 vectors)
FSM_SUP_CAP = 96                          # decision: cap on the leaf support of a state FF's D cone
FSM_EVAL_MAX = 300000                     # decision: next-state evaluations per machine
_FSM_OLD = 6                         # decision: <= 64 states printed exactly
FSM_INPUT_MAX = 5                         # decision: <= 32 input vectors per state
SUP_CAP = FSM_STATE_MAX + FSM_INPUT_MAX + 1
LINE_MAX = 2000                           # decision: block lines longer than this are split at statement boundaries (verilator token cap)
BUS_MAX = 32                              # decision: register bundle chunk
SHIFT_MIN = 3                             # decision: a shift register has >= 3 stages
# source: emit.py FF record keys (Builder._logic / _ff_controls: d, clk, ena, aclr, sclr, sload, asdata)
FF_KEYS = ("d", "clk", "ena", "aclr", "sclr", "sload", "asdata")
# source: this module (rule ids reported in stats / `[R:id]` tags)
RULES = ("ADD", "SUB", "ADDC", "CMP_GE", "CMP_GT", "CARRY", "CNT_UP", "CNT_DOWN", "REG", "REG_CHAIN", "SHIFT", "MUX", "XOR", "SOP", "TT",
         "CONST", "BUF", "INV", "FSM", "M9K", "MAC", "IO", "FLAT_LUT")
BLOCK_NAME = re.compile(r"\b(?:lc|ff|co)_\d+_\d+_\d+\b|\bpad_\w+\b")


# ---- truth tables over k leaves: bit idx of the int = value for assignment idx (leaf j = (idx >> j) & 1) ---------------------------------
def tt_of_var(j, k):
    return sum(1 << i for i in range(1 << k) if (i >> j) & 1)


def tt_mask(k):
    return (1 << (1 << k)) - 1


def depends(tt, k, j):
    return any(((tt >> i) & 1) != ((tt >> (i | (1 << j))) & 1) for i in range(1 << k) if not (i >> j) & 1)


def cofactor(tt, k, j, v):
    """tt with leaf j fixed to v, over k - 1 leaves (leaf order kept)."""
    out, n = 0, 0
    for i in range(1 << k):
        if ((i >> j) & 1) == v:
            out |= ((tt >> i) & 1) << n
            n += 1
    return out


def reduce_tt(leaves, tt):
    leaves, k = list(leaves), len(leaves)
    j = 0
    while j < k:
        if not depends(tt, k, j):
            tt = cofactor(tt, k, j, 0)
            del leaves[j]
            k -= 1
        else:
            j += 1
    return leaves, tt


# ---- exact minimisation (Quine-McCluskey, small k) ------------------------------------------------------------------------------------
def primes(minterms, k):
    cur = {(m, 0) for m in minterms}
    prime = set()
    while cur:
        nxt, used = set(), set()
        by = collections.defaultdict(list)
        for v, m in cur:
            by[m].append(v)
        for m, vs in by.items():
            vs_set = set(vs)
            for v in vs:
                for b in range(k):
                    bit = 1 << b
                    if m & bit or v & bit:
                        continue
                    if v | bit in vs_set:
                        nxt.add((v, m | bit))
                        used.add((v, m))
                        used.add((v | bit, m))
        prime |= cur - used
        cur = nxt
    return prime


def covers(imp, minterm):
    v, m = imp
    return (minterm & ~m) == v


def cover_min(minterms, k):
    """Minimal-literal cover: essential primes, then exact branch search for the remainder (k <= 6: small)."""
    if not minterms:
        return []
    ps = sorted(primes(minterms, k))
    ms = set(minterms)
    chosen, rest = [], set(ms)
    while True:
        ess = None
        for m in sorted(rest):
            cs = [p for p in ps if covers(p, m)]
            if len(cs) == 1:
                ess = cs[0]
                break
        if ess is None:
            break
        chosen.append(ess)
        rest = {m for m in rest if not covers(ess, m)}
    if rest:
        cost = lambda p: k - bin(p[1]).count("1")
        best = [None]

        def go(rem, pick, c):
            if best[0] is not None and c >= best[0][0]:
                return
            if not rem:
                best[0] = (c, list(pick))
                return
            m = min(rem)
            for p in sorted((p for p in ps if covers(p, m)), key=cost):
                pick.append(p)
                go({x for x in rem if not covers(p, x)}, pick, c + cost(p) + 1)
                pick.pop()
        go(rest, [], 0)
        chosen += best[0][1]
    return chosen


def lit_count(imps, k):
    return sum(k - bin(m).count("1") for _, m in imps)


def eval_imps(imps, k):
    out = 0
    for i in range(1 << k):
        if any(covers(p, i) for p in imps):
            out |= 1 << i
    return out


def find_mux(tt, k):
    """Largest-selects-first search: f = mux over m select leaves of literal data leaves -> (sel idx list, [(data idx, neg)] by select value)."""
    for m in (1, 2, 3):
        if k - m < 2:
            break
        for sel in itertools.combinations(range(k), m):
            data = [j for j in range(k) if j not in sel]
            cof, ok = [], True
            for s in range(1 << m):
                sub = tt
                # fix the selects high index first so remaining positions stay valid
                order = sorted(sel, reverse=True)
                cur_k = k
                rem = list(range(k))
                for pos in order:
                    p = rem.index(pos)
                    v = (s >> sel.index(pos)) & 1
                    sub = cofactor(sub, cur_k, p, v)
                    cur_k -= 1
                    rem.remove(pos)
                lit = None
                for q, dj in enumerate(rem):
                    vt = tt_of_var(q, cur_k)
                    if sub == vt:
                        lit = (dj, False)
                    elif sub == (~vt & tt_mask(cur_k)):
                        lit = (dj, True)
                    if lit:
                        break
                if lit is None:
                    ok = False
                    break
                cof.append(lit)
            if ok and len({d for d, _ in cof}) >= 2 and {d for d, _ in cof} | set(sel) >= set(range(k)):
                return list(sel), cof
    return None


_SIMP_MEMO = {}          # (k, tt) -> (kind, data): the minimisation depends only on the reduced truth table


def simp(leaves, tt):
    """-> (kind, data, leaves) with the exact function; kinds: const, lit, mux, xor, sop, tt."""
    leaves, tt = reduce_tt(leaves, tt)
    key = (len(leaves), tt)
    got = _SIMP_MEMO.get(key)
    if got is None:
        got = _SIMP_MEMO[key] = _simp_core(len(leaves), tt)
    return (got[0], got[1], leaves)


def _simp_core(k, tt):
    if k == 0:
        return ("const", tt & 1)
    if k == 1:
        return ("lit", tt == 1)                               # data = negated
    full = tt_mask(k)
    par = 0
    for j in range(k):
        par ^= tt_of_var(j, k)
    if tt == par:
        return ("xor", False)
    if tt == (~par & full):
        return ("xor", True)
    if k >= 3:
        mx = find_mux(tt, k)
        if mx:
            return ("mux", mx)
    mt = [i for i in range(1 << k) if (tt >> i) & 1]
    nt = [i for i in range(1 << k) if not (tt >> i) & 1]
    pos, neg = cover_min(mt, k), cover_min(nt, k)
    if lit_count(pos, k) <= lit_count(neg, k):
        imps, ng = pos, False
    else:
        imps, ng = neg, True
    check = eval_imps(imps, k)
    if ng:
        check = ~check & full
    if check != tt:
        raise SystemExit("rtl: minimisation self-check failed")
    if lit_count(imps, k) > SOP_LIT_MAX:
        return ("tt", tt)
    return ("sop", (ng, imps))


def render(simple, names):
    """names: leaf expression strings aligned with simple[2]; -> (expr text, rule id)."""
    kind, data, leaves = simple
    if kind == "const":
        return f"1'b{data}", "CONST"
    if kind == "lit":
        return (f"~{names[0]}" if data else names[0]), ("INV" if data else "BUF")
    if kind == "xor":
        e = " ^ ".join(names)
        return (f"~({e})" if data else e), "XOR"
    if kind == "mux":
        sel, cof = data
        def lit(c):
            d, ng = c
            return f"~{names[d]}" if ng else names[d]

        def build(level, base):
            if level < 0:
                return lit(cof[base])
            return f"{names[sel[level]]} ? {build(level - 1, base | (1 << level))} : {build(level - 1, base)}"
        e = build(len(sel) - 1, 0)
        return e, f"MUX{1 << len(sel)}"
    if kind == "tt":
        k = len(leaves)
        return f"|(({1 << k}'h{data:X} >> {{{', '.join(reversed(names))}}}) & {1 << k}'d1)", "TT"
    ng, imps = data
    k = len(names)
    terms = []
    for v, m in sorted(imps):
        lits = [(names[j] if (v >> j) & 1 else f"~{names[j]}") for j in range(k) if not (m >> j) & 1]
        terms.append(" & ".join(lits) if lits else "1'b1")
    if len(terms) == 1 and not ng:
        return terms[0], "SOP"
    body = " | ".join(f"({t})" if " & " in t and len(terms) > 1 else t for t in terms)
    return (f"~({body})" if ng else body), "SOP"


class Lift:
    def __init__(self, nl, prefix="io_", module="cyc4_top", flat_text=None):
        self.nl, self.prefix, self.module = nl, prefix, module
        self.stats = collections.Counter()
        self.adder_widths = []
        self.muxn = []
        self.counters = {}
        self.flat_text = flat_text

    # ---- indices ------------------------------------------------------------------------------------------------------------------
    def index(self):
        nl = self.nl
        self.lut = {L["name"]: L for L in nl.luts}
        self.co_of = {f"co_{L['x']}_{L['y']}_{L['le']}": L for L in nl.luts}
        self.ffd = {F["name"]: F for F in nl.ffs}
        self.alias = {}
        self.home = {}
        for io in nl.ios:
            self.home[f"pad_{io['ball']}"] = (f"{self.prefix}{io['ball']}", None)
        self.fan, self.sole = collections.Counter(), {}
        self.blk_text = self.block_text()
        blk_names = set(BLOCK_NAME.findall(self.blk_text))

        def slot(s, kind, owner):
            if s and s not in CONSTV:
                self.fan[s] += 1
                self.sole[s] = (kind, owner)
        for L in nl.luts:
            for i, p in enumerate(L["pins"]):
                slot(p, "cin" if (L["mode"] == "cin" and i == 2 and p in self.co_of) else "lut", L)
        for F in nl.ffs:
            for key in FF_KEYS:
                slot(F.get(key), "ff" + key, F)
        for io in nl.ios:
            slot(io.get("drv"), "io", io)
            slot(io.get("oe"), "io", io)
        for s in blk_names:
            self.fan[s] += 2                                 # block consumer: never inlined
            self.sole[s] = ("blk", None)

    def block_text(self):
        """Body lines of the emit's block sections (M9K / MAC / PLL), produced by emit.verilog on a block-only copy so the text tracks emit.py."""
        if not (self.nl.m9k or self.nl.mac or self.nl.pll):
            return ""
        import copy
        nb = copy.copy(self.nl)
        nb.luts, nb.ffs, nb.ios, nb.srcs = [], [], [], {}
        t = _FLAT_VERILOG(nb, self.module).split("\n")
        a = next(i for i, l in enumerate(t) if l.startswith("// declarations"))
        b = max(i for i, l in enumerate(t) if l.startswith("endmodule"))
        body = [l for l in t[a + 1:b] if not l.startswith("// LUTs:")]
        return "\n".join(body)

    def res(self, s):
        while s in self.alias:
            s = self.alias[s]
        return s

    # ---- carry chains -------------------------------------------------------------------------------------------------------------
    def chains(self):
        nl = self.nl
        nxt, prev = {}, {}
        for L in nl.luts:
            if L["mode"] == "cin" and L["cin"] in self.co_of:
                src = self.co_of[L["cin"]]
                nxt[src["name"]] = L["name"]
                prev[L["name"]] = src["name"]
        self.chain_of, self.chain_list, self.tail_free = {}, [], set()
        heads = [n for n in nxt if n not in prev]
        for h in sorted(heads):
            seq, cur = [h], h
            while cur in nxt and nxt[cur] not in seq:
                cur = nxt[cur]
                seq.append(cur)
            k = len(self.chain_list)
            ch = dict(k=k, luts=[self.lut[n] for n in seq], ok=False)
            self.analyse_chain(ch)
            self.chain_list.append(ch)
            for i, L_ in enumerate(ch["luts"]):
                self.chain_of[L_["name"]] = (ch, i)
            if ch.get("tail_free"):
                self.tail_free.add(ch["tail"]["name"])
        # cin-mode LUTs not in a chain with a head (unresolved carry-in, loops): opaque
        self.opaque = set()
        for L in nl.luts:
            n = L["name"]
            if n in self.chain_of:
                ch = self.chain_of[n][0]
                if not ch["ok"]:
                    self.opaque.add(n)
            elif L["mode"] == "cin" and n not in self.tail_free:
                self.opaque.add(n)

    @staticmethod
    def maj(a, b, c):
        return (a & b) | (a & c) | (b & c)

    def analyse_chain(self, ch):
        """Try the whole chain; if the last LE fits no adder form (a comparator's result LUT, or an adder's final gating LUT), analyse the chain
        without it: its carry-in is then the chain's carry out and the LE is ordinary logic (`tail_free`)."""
        full = list(ch["luts"])
        ch["tail_free"] = False
        self._analyse(ch, len(full), True)
        if not ch["ok"] and len(full) >= 3 and ch.get("why") == "no_operand_form" and ch.get("fail_at") == len(full) - 1:
            for k in ("why", "fail_at"):
                ch.pop(k, None)
            ch["luts"] = full[:-1]
            self._analyse(ch, len(full) - 1, False)
            if ch["ok"]:
                ch["tail_free"] = True
                ch["tail"] = full[-1]
            else:
                ch["luts"] = full

    def _analyse(self, ch, n_eff, exempt_last):
        """Per bit (X, Y) operand forms such that sum = X ^ Y ^ c and cout = maj(X, Y, c) ^ po (carry signal polarity po per stage, as stored
        by the fitter); incoming signal polarity of stage i = po of stage i - 1.  Head: constant carry-in c0 (signal 0 into cout)."""
        bits, pols, c0, pin = [], [], None, None
        ch["free_head"] = False
        forms = [("s", 0), ("s", 1), ("c", 0), ("c", 1)]
        ev = lambda f, v: (v ^ f[1]) if f[0] == "s" else f[1]
        nl_ = n_eff + (0 if exempt_last else 1)          # cout of the last analysed LE is checked unless it is the real last LE
        for i, L in enumerate(ch["luts"][:n_eff]):
            pins, init = L["pins"], L["init"]
            sumfree = self.fan[L["name"]] == 0
            if L.get("und"):
                ch.setdefault('why', 'R1'); return
            if i == 0 and L["mode"] == "cin":
                ch.setdefault('why', 'R2'); return
            # operand pin pairs: the two non-constant (or constant) inputs read as X, Y; the remaining pin must be a constant (datad of the last LE may carry a control)
            pairs = [(0, 1)] if pins[3] in CONSTV else [(0, 3), (3, 0), (1, 3), (3, 1)]
            found = None
            for px, py in pairs:
                other = ({0, 1, 3} - {px, py}).pop()
                if pins[other] not in CONSTV:
                    continue

                def idx(x, y, c, dc=None):
                    v = {px: x, py: y, other: CONSTV[pins[other]]}
                    return (v[0] | (v[1] << 1) | (c << 2) | (v[3] << 3)) if dc is None else (v[0] | (v[1] << 1) | (c << 2) | (dc << 3))
                sx, sy = pins[px], pins[py]

                def sum_fn(x, y, c):
                    return (init >> idx(x, y, c)) & 1

                def cout_fn(x, y, c):
                    return (init >> (idx(x, y, c) & 7)) & 1                 # emit semantics: cout reads INIT[{0, c, b, a}]
                for fx in forms:
                    if fx[0] == "s" and sx in CONSTV:
                        continue
                    for fy in forms:
                        if fy[0] == "s" and sy in CONSTV:
                            continue
                        for po in ((0, 1) if i < nl_ - 1 else (0,)):
                            if i == 0:
                                cc_ok = [cc for cc in (0, 1) if all(cout_fn(x, y, 0) == self.maj(ev(fx, x), ev(fy, y), cc) ^ po for x in (0, 1) for y in (0, 1))]
                                if not cc_ok:
                                    continue
                                cv = CONSTV[pins[2]] if pins[2] in CONSTV else None
                                good = [cc for cc in cc_ok if cv is not None and all(sum_fn(x, y, cv) == ev(fx, x) ^ ev(fy, y) ^ cc for x in (0, 1) for y in (0, 1))]
                                cand = (fx, fy, po, (good or cc_ok[:1])[0], sx, sy, not good)
                                if good or found is None:
                                    found = cand
                            elif all((sumfree or sum_fn(x, y, c) == ev(fx, x) ^ ev(fy, y) ^ c ^ pin) and
                                     (i == nl_ - 1 or cout_fn(x, y, c) == self.maj(ev(fx, x), ev(fy, y), c ^ pin) ^ po)
                                     for x in (0, 1) for y in (0, 1) for c in (0, 1)):
                                found = (fx, fy, po, None, sx, sy, False)
                            if found and (i > 0 or not found[6]):
                                break
                        if found and (i > 0 or not found[6]):
                            break
                    if found and (i > 0 or not found[6]):
                        break
                if found and (i > 0 or not found[6]):
                    break
            if not found:
                ch['why'] = 'no_operand_form'
                ch['fail_at'] = i
                return
            if i == 0:
                c0 = found[3]
                ch["free_head"] = found[6]
            pin = found[2]
            pols.append(pin)
            bits.append((found[0], found[1], found[4], found[5]))
        if c0 is None:
            ch.setdefault('why', 'R4'); return
        # orientation: the fitter swaps which pin carries which operand between bits; the signal read by most bits is the shared (B) operand
        cnt = collections.Counter(s for fx_, fy_, sx_, sy_ in bits for f_, s_ in ((fx_, sx_), (fy_, sy_)) if f_[0] == "s" for s in (s_,))
        ob = []
        for fx_, fy_, sx_, sy_ in bits:
            xs, ys = fx_[0] == "s", fy_[0] == "s"
            if (ys and not xs) or (xs and ys and (cnt[sx_] > cnt[sy_] or (cnt[sx_] == cnt[sy_] and fx_[1] > fy_[1]))):
                fx_, fy_, sx_, sy_ = fy_, fx_, sy_, sx_             # shared signal -> B; on a tie the inverted operand -> B (compare / subtract chains)
            ob.append((fx_, fy_, sx_, sy_))
        bits = ob
        # last LE: cout is unused, so (X inverted, Y inverted) and (X, Y) give the same sum; follow the previous bit's polarities
        if len(bits) >= 2:
            (lx, ly, lsx, lsy), (px_, py_, _a, _b) = bits[-1], bits[-2]
            if (lx[0], ly[0]) == (px_[0], py_[0]) and lx[1] ^ ly[1] == px_[1] ^ py_[1]:
                bits[-1] = (px_, py_, lsx, lsy)
        ch["bits"], ch["c0"], ch["po"] = bits, c0, pols
        # trailing collector LE (both operands constant 0): its sum is the carry out
        n = len(bits)
        top = n
        while top > 0 and bits[top - 1][0] == ("c", 0) and bits[top - 1][1] == ("c", 0):
            top -= 1
        if n - top > 1 or top == 0:
            ch.setdefault('why', 'R5'); return
        W = top
        ch["W"], ch["collector"] = W, n - top

        def operand(sel):
            sig = [(i, b[sel + 0], b[2 + sel]) for i, b in enumerate(bits[:W])]
            inv = {f[1] for _, f, _p in sig if f[0] == "s"}
            return sig, inv
        sa, ia_ = operand(0)
        sb, ib_ = operand(1)
        if len(ia_) > 1 or len(ib_) > 1:
            ch.setdefault('why', 'R6'); return
        pa_, pb_ = (next(iter(ia_)) if ia_ else 0), (next(iter(ib_)) if ib_ else 0)
        if pa_ and pb_:
            ch.setdefault('why', 'R7'); return
        swap = pa_ == 1
        if swap or (not any(f[0] == "s" for _, f, _p in sa) and any(f[0] == "s" for _, f, _p in sb)):
            sa, sb, pa_, pb_ = sb, sa, pb_, pa_
        if not any(f[0] == "s" for _, f, _p in sa):
            ch.setdefault('why', 'R8'); return
        if pa_:
            ch.setdefault('why', 'R9'); return
        ch["A"] = [(f, p) for _, f, p in sa]
        ch["B"] = [(f, p) for _, f, p in sb]
        ch["pol"] = pb_
        ch["ok"] = True

    def chain_operand_sigs(self, ch):
        """-> (raw A bit signals (const strings for const bits), raw B bit signals)."""
        def raw(side, pol):
            out = []
            for f, p in side:
                if f[0] == "s":
                    out.append(p)
                else:
                    out.append(f"1'b{f[1] ^ pol}")
            return out
        return raw(ch["A"], 0), raw(ch["B"], ch["pol"])

    # ---- cones --------------------------------------------------------------------------------------------------------------------
    def free_head(self, n):
        """LUT n is the first LE of a recognised chain whose sum is not an adder bit (a pure carry generator): its sum output is ordinary logic."""
        c = self.chain_of.get(n)
        return bool(c and c[0]["ok"] and c[0].get("free_head") and c[1] == 0)

    def normal(self, n):
        return n in self.lut and (n not in self.chain_of or self.free_head(n)) and n not in self.opaque

    def inl_ok(self, n, consumer_kinds):
        """LUT n can be inlined into its single consumer of one of the kinds."""
        if not self.normal(n) or self.fan[n] != 1:
            return False
        k, o = self.sole[n]
        if k not in consumer_kinds:
            return False
        return not (k == "lut" and (o["name"] == n or not self.normal(o["name"])))

    def cones(self):
        nl = self.nl
        self.cone = {}
        norm = [L for L in nl.luts if self.normal(L["name"])]
        deps = {L["name"]: [self.res(p) for p in L["pins"]] for L in norm}
        eligible = lambda c: c in deps and self.fan[c] == 1 and self.sole[c][0] == "lut" and self.sole[c][1]["name"] != c
        indeg = {n: 0 for n in deps}
        users = collections.defaultdict(list)
        for n, ps in deps.items():
            for p in ps:
                if eligible(p):
                    indeg[n] += 1
                    users[p].append(n)
        ready = [n for n, d in indeg.items() if d == 0]
        done = set()
        while ready:
            n = ready.pop()
            self.build(n, True)
            done.add(n)
            for u in users[n]:
                indeg[u] -= 1
                if indeg[u] == 0:
                    ready.append(u)
        for L in norm:                                       # combinational loops: no inlining
            if L["name"] not in done:
                self.build(L["name"], False)
        self.stats["loop_luts"] = len(norm) - len(done)

    def build(self, n, allow):
        L = self.lut[n]
        items = []
        for p in L["pins"]:
            p = self.res(p)
            if p in CONSTV:
                items.append(("k", CONSTV[p]))
            elif allow and p in self.cone and self.fan[p] == 1 and self.sole[p][0] == "lut" and self.sole[p][1]["name"] == n and self.normal(p):
                items.append(("n", self.cone[p]))
            else:
                items.append(("l", p))
        leaves = []
        for it in items:
            for s in (it[1][0] if it[0] == "n" else [it[1]] if it[0] == "l" else []):
                if s not in leaves:
                    leaves.append(s)
        if len(leaves) > MAXL:                               # too wide: keep the children materialised
            items = [("l", self.res(p)) if it[0] == "n" else it for p, it in zip(L["pins"], items)]
            leaves = []
            for it in items:
                if it[0] == "l" and it[1] not in leaves:
                    leaves.append(it[1])
            self.stats["cone_cut"] += 1
        k = len(leaves)
        pos = {s: i for i, s in enumerate(leaves)}
        tt = 0
        for idx in range(1 << k):
            li = 0
            for q, it in enumerate(items):
                if it[0] == "k":
                    v = it[1]
                elif it[0] == "l":
                    v = (idx >> pos[it[1]]) & 1
                else:
                    cl, ct = it[1]
                    ci = 0
                    for j, s in enumerate(cl):
                        ci |= ((idx >> pos[s]) & 1) << j
                    v = (ct >> ci) & 1
                li |= v << q
            tt |= ((L["init"] >> li) & 1) << idx
        leaves, tt = reduce_tt(leaves, tt)
        self.cone[n] = (leaves, tt)
        sp = simp(leaves, tt)
        if sp[0] == "const":
            self.alias[n] = f"1'b{sp[1]}"
        elif sp[0] == "lit" and not sp[1] and sp[2][0] != n:
            self.alias[n] = sp[2][0]

    def node_of(self, sig, kinds):
        """(leaves, tt) of a root consumer's input signal; single-fanout LUT cones are inlined."""
        sig = self.res(sig)
        if sig in CONSTV:
            return [], CONSTV[sig]
        if self.inl_ok(sig, kinds) and sig in self.cone:
            return self.cone[sig]
        return [sig], 2

    # ---- naming -------------------------------------------------------------------------------------------------------------------
    def ref(self, s):
        s = self.res(s)
        if s in CONSTV:
            return s
        h = self.home.get(s)
        if h:
            return h[0] if h[1] is None else f"{h[0]}[{h[1]}]"
        return s

    def concat(self, sigs):
        """MSB-first signal list -> concatenation text with slice runs merged."""
        parts = []
        for s in sigs:
            s = self.res(s)
            h = self.home.get(s)
            parts.append(h if (h and h[1] is not None) else (self.ref(s), None))
        out, i = [], 0
        while i < len(parts):
            v, ix = parts[i]
            j = i
            while ix is not None and j + 1 < len(parts) and parts[j + 1][0] == v and parts[j + 1][1] == parts[j][1] - 1:
                j += 1
            if j > i:
                span = (ix, parts[j][1])
                out.append(v if (span[1] == 0 and span[0] + 1 == self.width.get(v, -1)) else f"{v}[{span[0]}:{span[1]}]")
            else:
                out.append(v if ix is None else f"{v}[{ix}]")
            i = j + 1
        return out[0] if len(out) == 1 and not (out[0].startswith("1'b") and False) else "{" + ", ".join(out) + "}"

    # ---- registers ----------------------------------------------------------------------------------------------------------------
    def ctl_key(self, F):
        return tuple((F.get(k), bool(F.get(k + "_inv"))) if F.get(k) is not None else None for k in ("ena", "aclr", "sclr", "sload")) + \
            (F.get("clk"), bool(F.get("clk_inv")))

    def registers(self):
        nl = self.nl
        self.width = {}
        self.dnode = {}
        clocked = [F for F in nl.ffs if F["clk"] is not None and F["d"] is not None]
        self.unclocked = [F for F in nl.ffs if F not in clocked]
        for F in clocked:
            self.dnode[F["name"]] = self.node_of(F["d"], ("ffd",))
        self.dsimp = {n: simp(*v) for n, v in self.dnode.items()}
        used = set()
        groups = collections.defaultdict(list)
        for F in clocked:
            groups[self.ctl_key(F)].append(F)
        self.bundles = []                                    # dict(kind, ffs(list in bit order), key)
        self.counter_bundles(groups, used)
        # fed-by-chain registers: ordered by chain bit
        for key, fs in groups.items():
            byc = collections.defaultdict(list)
            for F in fs:
                if F["name"] in used:
                    continue
                sp = self.dsimp[F["name"]]
                if sp[0] == "lit" and not sp[1]:
                    c = self.chain_of.get(sp[2][0])
                    if c and c[0]["ok"] and not self.free_head(sp[2][0]) and not F.get("sload") and not F.get("sload_vcc"):
                        byc[c[0]["k"]].append((c[1], F))
            for k, lst in byc.items():
                if len(lst) >= 2:
                    lst.sort(key=lambda t: t[0])
                    ffs = [F for _, F in lst]
                    self.bundles.append(dict(kind="REG_CHAIN", ffs=ffs, key=key, chain=k, pos=[p for p, _ in lst]))
                    used.update(F["name"] for F in ffs)
        # shift registers: D is the plain Q of another FF of the same control set (taps and loads do not break a path: longest-path decomposition of the
        # D-copy forest; a stage with several copies continues with its deepest child, the others head their own paths; loads = sload/asdata per bit)
        for key, fs in groups.items():
            names = {F["name"] for F in fs if F["name"] not in used}
            succ = collections.defaultdict(list)
            pred = {}
            for F in fs:
                if F["name"] in used:
                    continue
                sp = self.dsimp[F["name"]]
                if sp[0] == "lit" and not sp[1] and sp[2][0] in names and sp[2][0] != F["name"]:
                    succ[sp[2][0]].append(F["name"])
                    pred[F["name"]] = sp[2][0]
            # loadable shift: D = load ? data : previous stage (mux with two distinct data leaves and one shared select set across the stages)
            mux_of = {}
            for F in fs:
                sp = self.dsimp[F["name"]]
                if F["name"] not in used and sp[0] == "mux":
                    sel, cof = sp[1]
                    dl = {self.res(sp[2][d]) for d, _ in cof}
                    if len(dl) == 2 and all(not ng for _d, ng in cof):
                        mux_of[F["name"]] = (frozenset(self.res(sp[2][j]) for j in sel), dl)
            for n_, (sels, dl) in mux_of.items():
                pc = [x for x in dl if x in mux_of and x != n_ and mux_of[x][0] == sels]
                if len(pc) == 1:
                    succ[pc[0]].append(n_)
                    pred[n_] = pc[0]
            depth = {}

            def dep(n, guard=()):
                if n in depth:
                    return depth[n]
                if n in guard:
                    return 0
                depth[n] = 1 + max([dep(c, guard + (n,)) for c in succ.get(n, [])] or [0])
                return depth[n]
            for n in sorted(names):
                dep(n)
            taken = set()
            progress = True
            while progress:
                progress = False
                cand = sorted((n for n in names if n not in taken and n in succ and (n not in pred or pred[n] in taken or pred[n] not in names)), key=lambda n: (-depth[n], n))
                if not cand:      # cycles (rotating registers): break at the deepest member
                    cand = sorted((n for n in names if n not in taken and n in succ), key=lambda n: (-depth[n], n))[:1]
                for s in cand:
                    if s in taken:
                        continue
                    path, cur = [s], s
                    while True:
                        nx = [c for c in succ.get(cur, []) if c not in taken and c not in path]
                        if not nx:
                            break
                        cur = max(nx, key=lambda c: (depth[c], c))
                        path.append(cur)
                    taken.update(path)               # short paths are consumed too (a stage is not offered twice)
                    progress = True
                    if len(path) >= SHIFT_MIN:
                        self.bundles.append(dict(kind="SHIFT", ffs=[self.ffd[n] for n in path], key=key))
                        used.update(path)
        self.lut_counter_bundles(groups, used)
        # remaining: by control set in location order
        for key, fs in groups.items():
            rest = sorted((F for F in fs if F["name"] not in used), key=lambda F: (F["x"], F["y"], F["le"]))
            for i in range(0, len(rest), BUS_MAX):
                self.bundles.append(dict(kind="REG", ffs=rest[i:i + BUS_MAX], key=key))

    def lut_counter_bundles(self, groups, used):
        """Binary counters built from plain LUTs (patterns.lut_counters: nested FF supports, exact count / hold / clear check per bit).  The bundle keeps
        the per-bit statements (exact), only the register is labelled."""
        from . import patterns
        D = patterns.Design(self.nl)
        known = set(used)
        clocked = {F["name"] for fs in groups.values() for F in fs}
        for c in patterns.lut_counters(D, known):
            names = c["ffs"]
            if any(n in used or n not in clocked for n in names) or len({self.ctl_key(self.ffd[n]) for n in names}) != 1:
                continue
            self.bundles.append(dict(kind="CNTL", ffs=[self.ffd[n] for n in names], key=self.ctl_key(self.ffd[names[0]])))
            used.update(names)

    def counter_bundles(self, groups, used):
        """Recognised carry chain whose bit i is the register FF fed by sum i (its own Q is an operand of the LE: self feedback) and whose other
        operand is a constant or one shared signal s: the register is a counter, next = R + K(s) (K from the operand constants and c0).
        A free head's bit 0 is the FF toggled by the head's constant operand; a shared signal that is itself a toggling FF of the same control
        set is the register's bit 0 (carry-in merged into the first LE).  Controls (enable, clears, load) are the bundle's FF control set, so
        the statement is the chain arithmetic and equivalence holds by construction."""
        clocked = {F["name"] for fs in groups.values() for F in fs}
        fed = {}
        for n in clocked:
            sp = self.dsimp[n]
            if sp[0] == "lit" and not sp[1]:
                fed.setdefault(self.res(sp[2][0]), n)
        for ch in self.chain_list:
            if not ch["ok"] or ch["W"] < 2:
                continue
            W, M = ch["W"], 1 << ch["W"]
            Fs, Bf, sigs, ok = [], [], set(), True
            for i in range(W):
                (fx, fy, sx, sy) = ch["bits"][i]
                sx, sy = self.res(sx), self.res(sy)
                if i == 0 and ch.get("free_head"):
                    cand = [(f, s, o, fo) for (f, s, o, fo) in ((fx, sx, sy, fy), (fy, sy, sx, fx)) if f[0] == "s" and s in self.ffd and fo[0] == "c" and f[1] == 0]
                    if not cand:
                        ok = False
                        break
                    f, s, o, fo = cand[0]
                    Fs.append(self.ffd[s])
                    Bf.append(fo)
                    continue
                n = fed.get(ch["luts"][i]["name"])
                if n is None:
                    ok = False
                    break
                pair = [(fx, sx, fy, sy), (fy, sy, fx, sx)]
                pick = [(f, s, fo, so) for (f, s, fo, so) in pair if f[0] == "s" and s == n and f[1] == 0]
                if not pick:
                    ok = False
                    break
                f, s, fo, so = pick[0]
                Fs.append(self.ffd[n])
                Bf.append(fo)
                if fo[0] == "s":
                    if so in CONSTV or so == n:
                        ok = False
                        break
                    sigs.add(so)
            if not ok or len(sigs) > 1 or len({F["name"] for F in Fs}) != W or any(F["name"] in used for F in Fs):
                continue
            rest_keys = {self.ctl_key(F) for F in Fs[1:]}
            if len(rest_keys) != 1:
                continue
            k0, kr = self.ctl_key(Fs[0]), next(iter(rest_keys))
            enable_in_lut = ch.get("free_head") and k0 != kr and k0[0] is None and kr[0] is not None and k0[1:] == kr[1:]
            if k0 != kr and not enable_in_lut:
                continue
            if ch.get("free_head"):
                fy0 = ch["bits"][0]
                sp = self.dsimp[Fs[0]["name"]]
                par = (Bf[0][1] ^ ch["c0"])
                if enable_in_lut:
                    ok = par == 1 and sp[0] == "xor" and {self.res(x) for x in sp[2]} == {Fs[0]["name"], self.res(kr[0][0])} and sp[1] == bool(kr[0][1])
                else:
                    ok = sp[0] == "lit" and self.res(sp[2][0]) == Fs[0]["name"] and sp[1] == bool(par)
                if not ok:
                    continue

            def K(sv):
                return (sum(((sv ^ f[1]) if f[0] == "s" else f[1]) << i for i, f in enumerate(Bf)) + ch["c0"]) % M
            sig = next(iter(sigs)) if sigs else None
            ks = (K(0), K(1)) if sig else (K(0),)
            ffs, ctl = list(Fs), (Fs[1] if enable_in_lut else None)
            if sig and ks == (0, 1) and sig in self.ffd and sig in clocked and sig not in used and self.ctl_key(self.ffd[sig]) == kr:
                sp = self.dsimp[sig]
                if sp[0] == "lit" and sp[1] and self.res(sp[2][0]) == sig:          # the shared signal is the register's bit 0 (toggles every enabled clock)
                    ffs, ks, sig = [self.ffd[sig]] + ffs, (1,), None
            self.bundles.append(dict(kind="CNT", ffs=ffs, key=kr, chain=ch["k"], sig=sig, ks=ks, ctl=ctl))
            used.update(F["name"] for F in ffs)
            self.counters[id(self.bundles[-1])] = True

    # ---- FSM ----------------------------------------------------------------------------------------------------------------------
    def fsm(self):
        """State machines: strongly connected groups of register FFs (2..FSM_STATE_MAX bits, one control set, no load) whose reachable state set
        from power-up 0 stays small (<= FSM_REACH_MAX).  The next-state function is enumerated per reachable state over the inputs that cone
        actually depends on after constant propagation (<= FSM_STATE_INPUT_MAX), so the number of distinct inputs overall is unbounded; any
        binary / gray / one-hot encoding is covered.  The case lists reachable states only (closed under all inputs, so the machine is exact
        from reset)."""
        cand = {F["name"]: b for b in self.bundles if b["kind"] == "REG" for F in b["ffs"]}
        sup_memo = {}

        def sup(sig):
            sig = self.res(sig)
            if sig in CONSTV:
                return frozenset()
            if sig in sup_memo:
                return sup_memo[sig]
            stack, order = [sig], []
            while stack:
                s = stack[-1]
                if s in sup_memo:
                    stack.pop()
                    continue
                if not self.normal(s):
                    sup_memo[s] = frozenset([s])
                    stack.pop()
                    continue
                pend = [self.res(q) for q in self.lut[s]["pins"] if self.res(q) not in CONSTV and self.res(q) not in sup_memo]
                if pend and not all(q in order for q in pend):
                    order.append(s)
                    stack.extend(q for q in pend if q not in order)
                    if len(order) > 100000:
                        return None
                    continue
                acc, over = set(), False
                for q in self.lut[s]["pins"]:
                    q = self.res(q)
                    if q not in CONSTV:
                        sq = sup_memo.get(q, frozenset([q]))
                        if sq is None:
                            over = True
                            break
                        acc |= sq
                sup_memo[s] = frozenset(acc) if not over and len(acc) <= FSM_SUP_CAP else None
                if s in order:
                    order.remove(s)
                stack.pop()
            return sup_memo.get(sig)
        dep = {n: sup(self.ffd[n]["d"]) for n in cand}
        cn = set(cand)
        idx, low, onst, st, comps, counter = {}, {}, set(), [], [], [0]

        def edges(n):
            return [m for m in (dep.get(n) or ()) if m in cn]
        for root in sorted(cn):
            if root in idx:
                continue
            work = [(root, iter(edges(root)))]
            idx[root] = low[root] = counter[0]
            counter[0] += 1
            st.append(root)
            onst.add(root)
            while work:
                v, it = work[-1]
                adv = False
                for w in it:
                    if w not in idx:
                        idx[w] = low[w] = counter[0]
                        counter[0] += 1
                        st.append(w)
                        onst.add(w)
                        work.append((w, iter(edges(w))))
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
        self.fsms = []
        taken = set()
        for comp in comps:
            if not (2 <= len(comp) <= FSM_STATE_MAX):
                continue
            if len({self.ctl_key(self.ffd[n]) for n in comp}) != 1 or any(self.ffd[n].get("sload") for n in comp):
                continue
            S = sorted(comp)
            Sset = set(S)
            if any(dep[n] is None for n in S):
                continue
            inputs = set()
            for n in S:
                inputs |= dep[n] - Sset
            if any(i in self.lut for i in inputs):         # carry chain / opaque LUT in the cone: not evaluated here
                continue
            res = self.explore(S, Sset)
            if res is None:
                continue
            rows, reach = res
            allin = sorted({x for r_ in rows.values() for x in r_[0]})
            self.fsms.append(dict(S=[self.ffd[n] for n in S], I=allin, rows=rows, reach=len(reach), key=self.ctl_key(self.ffd[S[0]])))
            taken.update(S)
        for b in self.bundles:
            b["ffs"] = [F for F in b["ffs"] if F["name"] not in taken]
        self.bundles = [b for b in self.bundles if b["ffs"]]

    def explore(self, S, Sset):
        """BFS over reachable states from 0; rows[state] = (input names, next-state list over the 2^k input vectors) or None on a cap."""
        sidx = {n: i for i, n in enumerate(S)}
        rows, seen, frontier, evals = {}, {0}, [0], 0
        while frontier:
            s = frontier.pop()
            memo = {}

            def free(sig):
                """('c', v) or ('f', frozenset leaves) of sig with the state fixed to s."""
                sig = self.res(sig)
                if sig in CONSTV:
                    return ("c", CONSTV[sig])
                if sig in sidx:
                    return ("c", (s >> sidx[sig]) & 1)
                got = memo.get(sig)
                if got is not None:
                    return got
                if not self.normal(sig):
                    memo[sig] = ("f", frozenset([sig]))
                    return memo[sig]
                L = self.lut[sig]
                pv = [free(q) for q in L["pins"]]
                fp = [i for i, v in enumerate(pv) if v[0] == "f"]
                if not fp:
                    li = sum(pv[i][1] << i for i in range(4))
                    memo[sig] = ("c", (L["init"] >> li) & 1)
                    return memo[sig]
                rel = []
                for i in fp:                           # a free pin matters if flipping it changes the restricted function somewhere
                    for a in range(1 << len(fp)):
                        li = sum(pv[j][1] << j for j in range(4) if pv[j][0] == "c") + sum(((a >> q) & 1) << fp[q] for q in range(len(fp)))
                        if ((L["init"] >> li) & 1) != ((L["init"] >> (li ^ (1 << i))) & 1):
                            rel.append(i)
                            break
                if not rel:
                    li = sum(pv[j][1] << j for j in range(4) if pv[j][0] == "c")
                    memo[sig] = ("c", (L["init"] >> li) & 1)
                else:
                    memo[sig] = ("f", frozenset().union(*[pv[i][1] for i in rel]))
                return memo[sig]
            Es = set()
            for n in S:
                v = free(self.ffd[n]["d"])
                if v[0] == "f":
                    Es |= v[1]
            Es = sorted(Es)
            if len(Es) > FSM_STATE_INPUT_MAX:
                return None
            tab = []
            for iv in range(1 << len(Es)):
                env = {x: (iv >> j) & 1 for j, x in enumerate(Es)}
                m2 = {}

                def val(sig):
                    sig = self.res(sig)
                    if sig in CONSTV:
                        return CONSTV[sig]
                    if sig in sidx:
                        return (s >> sidx[sig]) & 1
                    if sig in env:
                        return env[sig]
                    got = m2.get(sig)
                    if got is not None:
                        return got
                    if not self.normal(sig):
                        return 0                           # a leaf outside Es: proven irrelevant to the result by the restriction above
                    L = self.lut[sig]
                    li = 0
                    for q, pn in enumerate(L["pins"]):
                        li |= val(pn) << q
                    m2[sig] = (L["init"] >> li) & 1
                    return m2[sig]
                nx = 0
                for n in S:
                    nx |= val(self.ffd[n]["d"]) << sidx[n]
                tab.append(nx)
                evals += 1
                if nx not in seen:
                    seen.add(nx)
                    frontier.append(nx)
                    if len(seen) > FSM_REACH_MAX:
                        return None
            rows[s] = (Es, tab)
            if evals > FSM_EVAL_MAX:
                return None
        if len(seen) < 3:
            return None
        return rows, seen

    # ---- driver -------------------------------------------------------------------------------------------------------------------
    def run(self):
        nl = self.nl
        self.index()
        self.chains()
        self.cones()
        self.leaf_use()
        self.registers()
        self.fsm()
        return self.emit()

    def leaf_use(self):
        """leafuse[sig]: number of consumer nodes (materialised cones, FF D nodes, controls, IO, chain operands, blocks) referencing sig as a leaf."""
        use = collections.Counter()
        for n, (leaves, tt) in self.cone.items():
            if n in self.alias:
                continue
            if self.fan[n] == 1 and self.sole[n][0] in ("lut", "ffd", "io") and self.inl_ok(n, (self.sole[n][0],)):
                continue
            for s in simp(leaves, tt)[2]:
                use[s] += 1
        for F in self.nl.ffs:
            for key in FF_KEYS:
                v = F.get(key)
                if v is None:
                    continue
                if key == "d":
                    lv, tt = self.node_of(v, ("ffd",))
                    for s in simp(lv, tt)[2]:
                        use[s] += 1
                else:
                    use[self.res(v)] += 1
        for io in self.nl.ios:
            for key in ("drv", "oe"):
                if io.get(key) is not None:
                    lv, tt = self.node_of(io[key], ("io",))
                    for s in simp(lv, tt)[2]:
                        use[s] += 1
        for ch in self.chain_list:
            for L in ch["luts"]:
                for p in L["pins"]:
                    use[self.res(p)] += 1
        for s in BLOCK_NAME.findall(self.blk_text):
            use[s] += 2
        self.leafuse = use

    # ---- text ---------------------------------------------------------------------------------------------------------------------
    def need_closure(self):
        """Leaves reachable from the emitted roots: materialised LUT nodes, chains (with the sum / carry bits used), opaque LUTs."""
        nl = self.nl
        self.need_w, self.need_chain, self.need_opaque = set(), collections.defaultdict(lambda: dict(sum=set(), co=set())), set()
        stack = []
        fsm_ff = {F["name"] for f in self.fsms for F in f["S"]}
        for b in self.bundles:
            for F in b["ffs"]:
                stack += [F[k] for k in ("clk", "ena", "aclr", "sclr", "sload", "asdata") if F.get(k) is not None]
                if id(b) not in self.counters:
                    stack += self.dsimp[F["name"]][2]
        for f in self.fsms:
            stack += f["I"]
            F = f["S"][0]
            stack += [F[k] for k in ("clk", "ena", "aclr", "sclr", "sload") if F.get(k) is not None]
        for F in self.unclocked:
            pass
        for io in nl.ios:
            for key in ("drv", "oe"):
                if io.get(key) is not None and io["dir"] in ("output", "bidir-or-tristate"):
                    stack += simp(*self.node_of(io[key], ("io",)))[2]
        stack += BLOCK_NAME.findall(self.blk_text)
        for b in self.bundles:
            if id(b) in self.counters and b["sig"]:
                stack.append(b["sig"])
        seen = set()
        while stack:
            s = self.res(stack.pop())
            if s in seen or s in CONSTV:
                continue
            seen.add(s)
            if (s in self.chain_of and not self.free_head(s)) or s in self.co_of and self.co_of[s]["name"] in self.chain_of:
                L = self.lut.get(s) or self.co_of[s]
                ch, i = self.chain_of[L["name"]]
                if ch["ok"]:
                    d = self.need_chain[ch["k"]]
                    (d["sum"] if s in self.lut else d["co"]).add(i)
                    if not d.get("done"):
                        d["done"] = True
                        A, B = self.chain_operand_sigs(ch)
                        stack += [x for x in A + B if x not in CONSTV]
                    continue
            if s in self.opaque or (s in self.co_of and self.co_of[s]["name"] in self.opaque):
                L = self.lut.get(s) or self.co_of[s]
                if L["name"] not in self.need_opaque:
                    self.need_opaque.add(L["name"])
                    stack += list(L["pins"])
                    seen.add(L["name"])
                    seen.add(f"co_{L['x']}_{L['y']}_{L['le']}")
                continue
            if self.normal(s) and s in self.cone:
                self.need_w.add(s)
                stack += simp(*self.cone[s])[2]
        return fsm_ff

    def always_block(self, F, name, body, tag):
        """always block with the control set of FF record F around `body` lines (list of statements)."""
        r = self.ref
        clk = r(F["clk"])
        ev = ("negedge " if F.get("clk_inv") else "posedge ") + clk
        out = []
        ac = F.get("aclr")
        if ac is not None:
            inv = F.get("aclr_inv")
            ev += (" or posedge " if inv else " or negedge ") + r(ac)
        out.append(f"always @({ev}) begin // [R:{tag}]")
        ind = "  "
        if ac is not None:
            out.append(f"{ind}if ({r(ac) if F.get('aclr_inv') else '!' + r(ac)}) {name} <= 0;")
            out.append(f"{ind}else begin")
            ind += "  "
        if F.get("ena") is not None:
            out.append(f"{ind}if ({'!' + r(F['ena']) if F.get('ena_inv') else r(F['ena'])}) begin")
            ind += "  "
        if F.get("sclr") is not None:
            c = "!" + r(F["sclr"]) if F.get("sclr_inv") else r(F["sclr"])
            out.append(f"{ind}if ({c}) {name} <= 0;")
            out.append(f"{ind}else begin")
            ind += "  "
        out += [ind + l for l in body]
        for _ in range((ac is not None) + (F.get("ena") is not None) + (F.get("sclr") is not None)):
            ind = ind[:-2]
            out.append(f"{ind}end")
        out.append("end")
        return out

    def mux_note(self, sp, out):
        """Record a mux-shaped cone (select leaves, data leaves, output signal) for the structural mux count."""
        if sp[0] != "mux":
            return
        sel, cof = sp[1]
        self.muxn.append((out, frozenset(self.res(sp[2][j]) for j in sel), [self.res(sp[2][d]) for d, _ in cof]))

    def count_muxes(self):
        """A mux construct = a group of mux-shaped cones joined by data flow that either shares a select set between >= 2 cones (a bus mux)
        or is a tree of >= 3 cones.  A lone mux-shaped cone is an expression, not a mux construct."""
        par = list(range(len(self.muxn)))

        def find(i):
            while par[i] != i:
                par[i] = par[par[i]]
                i = par[i]
            return i
        by_out = {o: i for i, (o, _s, _d) in enumerate(self.muxn) if o is not None}
        by_sel = {}
        for i, (_o, s, d) in enumerate(self.muxn):
            for x in d:
                if x in by_out:
                    par[find(i)] = find(by_out[x])
            by_sel.setdefault(s, []).append(i)
        comp = collections.defaultdict(list)
        for i in range(len(self.muxn)):
            comp[find(i)].append(i)
        # cones sharing a select set (bus) are one construct even when they do not feed each other
        for s, idx in by_sel.items():
            for i in idx[1:]:
                par[find(i)] = find(idx[0])
        comp = collections.defaultdict(list)
        for i in range(len(self.muxn)):
            comp[find(i)].append(i)
        n = 0
        for idx in comp.values():
            sels = collections.Counter(self.muxn[i][1] for i in idx)
            if len(idx) >= 3 or max(sels.values()) >= 2:
                n += 1
        self.stats["mux_nodes"] = len(self.muxn)
        self.stats["mux_constructs"] = n

    def num(self, v, w):
        return f"{w}'d{v}"

    def emit(self):
        nl = self.nl
        st = self.stats
        self.need_closure()
        decl, logic = [], []
        wn = collections.Counter()

        def newname(prefix):
            wn[prefix] += 1
            return f"{prefix}_{wn[prefix] - 1}"
        # ---- chains
        chain_names = {}
        for ch in self.chain_list:
            nd = self.need_chain.get(ch["k"])
            if not ch["ok"] or nd is None:
                continue
            W = ch["W"]
            A, B = self.chain_operand_sigs(ch)
            bconst = not any(f[0] == "s" for f, _p in ch["B"])
            sub = bool(ch["pol"])
            vec = newname("sub" if sub else "add")
            chain_names[ch["k"]] = vec
            nd["vec"] = vec
        # ---- registers: names and homes
        for b in self.bundles:
            b["name"] = newname({"SHIFT": "sr", "REG": "r", "REG_CHAIN": "r", "CNT": "cnt", "CNTL": "cnt"}[b["kind"]])
            self.width[b["name"]] = len(b["ffs"])
            for j, F in enumerate(b["ffs"]):
                self.home[F["name"]] = (b["name"], j)
        for f in self.fsms:
            f["name"] = newname("st")
            self.width[f["name"]] = len(f["S"])
            for j, F in enumerate(f["S"]):
                self.home[F["name"]] = (f["name"], j)
        for F in self.unclocked:
            self.home[F["name"]] = (newname("r"), None)
            self.width[self.home[F["name"]][0]] = None
        # ---- wires
        for n in sorted(self.need_w):
            self.home[n] = (newname("w"), None)
        # ---- chain texts
        cmp_names = {}
        for ch in self.chain_list:
            nd = self.need_chain.get(ch["k"])
            if not ch["ok"] or nd is None or "vec" not in nd:
                continue
            k, W, vec, c0 = ch["k"], ch["W"], nd["vec"], ch["c0"]
            A, B = self.chain_operand_sigs(ch)
            sub = bool(ch["pol"])
            bconst = not any(f[0] == "s" for f, _p in ch["B"])
            low_used = {i for i in nd["sum"] if i < W}
            top_used = (W in nd["sum"]) or ((W - 1) in nd["co"])
            cmpmode = sub and not low_used and top_used and not (set(nd["co"]) - {W - 1})
            # operand buses
            ba, bb = newname("bus"), newname("bus")
            decl.append(f"wire [{W - 1}:0] {ba};")
            # deferred: operand bits may be sums of a chain whose homes are assigned later in this loop
            logic.append(lambda A=A, ba=ba, W=W, sub=sub: f"assign {ba} = {self.concat(list(reversed(A)))}; // [R:{'SUB' if sub else 'ADD'}] operand A, {W} bit")
            if bconst:
                beff = sum(f[1] << i for i, (f, _p) in enumerate(ch["B"]))
                kk = beff + c0
                if kk < (1 << W):
                    beff, c0 = kk, 0
                btxt = self.num(beff, W)
            else:
                decl.append(f"wire [{W - 1}:0] {bb};")
                logic.append(lambda B=B, bb=bb, W=W, sub=sub: f"assign {bb} = {self.concat(list(reversed(B)))}; // [R:{'SUB' if sub else 'ADD'}] operand B, {W} bit")
                btxt = bb
            if cmpmode:
                cn = newname("cmp")
                decl.append(f"wire {cn};")
                op = ">=" if c0 else ">"
                logic.append(f"assign `LUT_DELAY {cn} = {ba} {op} {btxt}; // [R:CMP_{'GE' if c0 else 'GT'}] {W} bit unsigned compare (chain carry out)")
                st["rule:CMP_GE" if c0 else "rule:CMP_GT"] += 1
                for i in nd["sum"]:
                    if i >= W:
                        self.home[ch["luts"][i]["name"]] = (cn, None)
                lastco = f"co_{ch['luts'][W - 1]['x']}_{ch['luts'][W - 1]['y']}_{ch['luts'][W - 1]['le']}"
                if ch["po"][W - 1]:
                    cnn = newname("cn")
                    decl.append(f"wire {cnn};")
                    logic.append(f"assign `LUT_DELAY {cnn} = ~{cn}; // [R:CARRY] carry signal stored inverted by the fitter")
                    self.home[lastco] = (cnn, None)
                else:
                    self.home[lastco] = (cn, None)
                st["chains"] += 1
                continue
            decl.append(f"wire [{W}:0] {vec};")
            if sub:
                expr = f"{{1'b0, {ba}}} - {{1'b0, {btxt}}}" + ("" if c0 else " - 1'b1")
                rule = "SUB"
                nb = newname("nb")
                decl.append(f"wire {nb};")
                logic.append(f"assign `LUT_DELAY {nb} = ~{vec}[{W}]; // carry out = no borrow")
                top = (nb, None)
            else:
                expr = f"{{1'b0, {ba}}} + {{1'b0, {btxt}}}" + (" + 1'b1" if c0 else "")
                rule = "ADDC" if bconst else "ADD"
                top = (vec, W)
            logic.append(f"assign `LUT_DELAY {vec} = {expr}; // [R:{rule}] {W} bit")
            st[f"rule:{rule}"] += 1
            st["chains"] += 1
            st["chain_bits"] += W
            if not sub:
                self.adder_widths.append(W)
            for i, L in enumerate(ch["luts"]):
                if i == 0 and ch.get("free_head"):
                    continue
                if i < W:
                    self.home[L["name"]] = (vec, i)
                else:
                    self.home[L["name"]] = top
            for i in range(W):
                L = ch["luts"][i]
                co = f"co_{L['x']}_{L['y']}_{L['le']}"
                if i == W - 1 and not ch["po"][i]:
                    self.home[co] = top
                elif i == W - 1:
                    cn = newname("cn")
                    decl.append(f"wire {cn};")
                    logic.append(f"assign `LUT_DELAY {cn} = ~{top[0]}{'' if top[1] is None else '[' + str(top[1]) + ']'}; // [R:CARRY] carry signal stored inverted by the fitter")
                    self.home[co] = (cn, None)
                elif i in nd["co"]:
                    cy = newname("cy")
                    decl.append(f"wire [{i + 1}:0] {cy};")
                    bsl = f"{btxt}[{i}:0]" if not bconst else f"{i + 1}'d{beff & ((1 << (i + 1)) - 1)}"
                    bsl = ("~" if sub else "") + bsl
                    logic.append(f"assign `LUT_DELAY {cy} = {{1'b0, {ba}[{i}:0]}} + {{1'b0, {bsl}}}{' + 1' + chr(39) + 'b1' if c0 else ''}; // [R:CARRY] carry into bit {i + 1}")
                    if ch["po"][i]:
                        cn = newname("cn")
                        decl.append(f"wire {cn};")
                        logic.append(f"assign `LUT_DELAY {cn} = ~{cy}[{i + 1}]; // [R:CARRY] carry signal stored inverted by the fitter")
                        self.home[co] = (cn, None)
                    else:
                        self.home[co] = (cy, i + 1)
            self.width[vec] = W + 1
            for i in range(W, len(ch["luts"])):               # collector LE: its carry-out is not an adder bit; kept flat if used
                L = ch["luts"][i]
                co = f"co_{L['x']}_{L['y']}_{L['le']}"
                if i in nd["co"]:
                    decl.append(f"wire {co};")
                    logic.append(f"assign `LUT_DELAY {co} = |((16'h{L['init']:04X} >> {{1'b0, {self.ref(L['pins'][2])}, 1'b1, 1'b1}}) & 16'd1); // [R:FLAT_LUT] collector carry-out")
        # ---- opaque LUTs
        for n in sorted(self.need_opaque):
            L = self.lut[n]
            a, b, c, d = [self.ref(p) for p in L["pins"]]
            co = f"co_{L['x']}_{L['y']}_{L['le']}"
            decl.append(f"wire {n}; wire {co};")
            logic.append(f"localparam [15:0] I_{n} = 16'h{L['init']:04X};")
            logic.append(f"assign `LUT_DELAY {n} = I_{n}[{{{d}, {c}, {b}, {a}}}]; // [R:FLAT_LUT]")
            logic.append(f"assign `LUT_DELAY {co} = I_{n}[{{1'b0, {c if L['mode'] == 'cin' else chr(49) + chr(39) + 'b0'}, {b}, {a}}}];")
            st["rule:FLAT_LUT"] += 1
        # ---- wires (materialised cones)
        for n in sorted(self.need_w):
            wname = self.home[n][0]
            sp = simp(*self.cone[n])
            text, rule = render(sp, [self.ref(x) for x in sp[2]])
            self.mux_note(sp, n)
            decl.append(f"wire {wname};")
            logic.append(f"assign `LUT_DELAY {wname} = {text}; // [R:{rule}]")
            st[f"rule:{rule}"] += 1
        # ---- registers
        for b in self.bundles:
            name, ffs = b["name"], b["ffs"]
            w = len(ffs)
            decl.append(f"reg [{w - 1}:0] {name} = {w}'b0;")
            stm, j = [], 0
            F0 = b.get("ctl") or ffs[0]
            if id(b) in self.counters:
                M = 1 << w

                def step(k):
                    return name if k == 0 else f"{name} + {self.num(k, w)}" if k < M // 2 else f"{name} - {self.num(M - k, w)}"
                ks = b["ks"]
                if len(ks) == 1:
                    expr, tag = step(ks[0]), ("CNT_UP" if ks[0] < M // 2 else "CNT_DOWN")
                else:
                    expr = f"{self.ref(b['sig'])} ? ({step(ks[1])}) : ({step(ks[0])})"
                    tag = "CNT_UPDOWN" if (ks[0] + ks[1]) % M == 0 else "CNT_SEL"
                if F0.get("sload"):
                    sload_c = "!" + self.ref(F0["sload"]) if F0.get("sload_inv") else self.ref(F0["sload"])
                    asd = self.concat([F.get("asdata") or "1'b0" for F in reversed(ffs)])
                    stm.append(f"{name} <= {sload_c} ? {asd} : ({expr});")
                else:
                    stm.append(f"{name} <= {expr};")
                st[f"rule:{tag}"] += 1
                st["counters"] += 1
            else:
                tag = b["kind"]
                if tag == "SHIFT":                  # feedback: the head's D is a function of >= 2 stages of its own path
                    hs = self.dsimp[ffs[0]["name"]]
                    pn = {F["name"] for F in ffs}
                    if hs[0] in ("xor", "sop", "tt") and sum(1 for x in hs[2] if self.res(x) in pn) >= 2:
                        tag = "LFSR"
                sl = bool(F0.get("sload"))
                sload_c = None
                if sl:
                    sload_c = "!" + self.ref(F0["sload"]) if F0.get("sload_inv") else self.ref(F0["sload"])
                while j < w:
                    F = ffs[j]
                    sp = self.dsimp[F["name"]]
                    if sl:
                        d = render(sp, [self.ref(x) for x in sp[2]])[0]
                        stm.append(f"{name}[{j}] <= {sload_c} ? {self.ref(F.get('asdata') or chr(49) + chr(39) + 'b0')} : {d};")
                        j += 1
                        continue
                    if sp[0] == "lit" and not sp[1] and self.home.get(self.res(sp[2][0]), (None, None))[1] is not None:
                        v, ix = self.home[self.res(sp[2][0])]
                        e = j
                        while e + 1 < w:
                            sq = self.dsimp[ffs[e + 1]["name"]]
                            if not (sq[0] == "lit" and not sq[1]):
                                break
                            h2 = self.home.get(self.res(sq[2][0]))
                            if not (h2 and h2[0] == v and h2[1] == ix + (e + 1 - j)):
                                break
                            e += 1
                        if e > j:
                            stm.append(f"{name}[{e}:{j}] <= {v}[{ix + e - j}:{ix}];")
                        else:
                            stm.append(f"{name}[{j}] <= {v}[{ix}];")
                        j = e + 1
                        continue
                    text, rule = render(sp, [self.ref(x) for x in sp[2]])
                    if b["kind"] != "SHIFT":           # a load mux inside a shift register is part of that register
                        self.mux_note(sp, None)
                    st[f"rule:{rule}"] += 1
                    stm.append(f"{name}[{j}] <= {text}; // [R:{rule}]")
                    j += 1
            logic += self.always_block(F0, name, stm, tag)
            st[f"rule:{tag}"] += 1 if tag in ("REG", "REG_CHAIN", "SHIFT", "LFSR", "CNTL") else 0
            st["reg_bits"] += w
            st["bundles"] += 1
        for F in self.unclocked:
            nm = self.home[F["name"]][0]
            decl.append(f"reg {nm} = 1'b0; // UNDECODED: no clock or D source; register not clocked")
        # ---- FSMs
        for f in self.fsms:
            S, name = f["S"], f["name"]
            w = len(S)
            decl.append(f"reg [{w - 1}:0] {name} = {w}'b0;")
            stm = [f"case ({name}) // {f['reach']} states reachable from reset (power-up 0); other codes are unreachable"]
            for s in sorted(f["rows"]):
                Is, tab = f["rows"][s]
                names = [self.ref(x) for x in Is]
                row = collections.defaultdict(list)
                for iv, nx in enumerate(tab):
                    row[nx].append(iv)
                if len(row) == 1:
                    stm.append(f"  {self.num(s, w)}: {name} <= {self.num(next(iter(row)), w)};")
                    continue
                dflt = max(row, key=lambda t_: len(row[t_]))
                stm.append(f"  {self.num(s, w)}: begin")
                first = True
                for tg in sorted(row):
                    if tg == dflt:
                        continue
                    imps = cover_min(row[tg], len(Is))
                    cond = render(("sop", (False, imps), Is), names)[0]
                    stm.append(f"    {'if' if first else 'else if'} ({cond}) {name} <= {self.num(tg, w)};")
                    first = False
                stm.append(f"    else {name} <= {self.num(dflt, w)};")
                stm.append("  end")
            stm.append(f"  default: {name} <= {self.num(0, w)};")
            stm.append("endcase")
            logic += self.always_block(S[0], name, stm, "FSM")
            st["rule:FSM"] += 1
            st["fsms"] += 1
            st["fsm_state_bits"] += w
        # ---- IO
        ports, io_lines = [], []
        for io in sorted(nl.ios, key=lambda i: i["ball"]):
            pn = f"{self.prefix}{io['ball']}"
            d = io["dir"]
            ports.append(f"{'input' if d == 'input' else 'output' if d == 'output' else 'inout'} wire {pn}")
            if d in ("output", "bidir-or-tristate") and io.get("drv") is not None:
                sp = simp(*self.node_of(io["drv"], ("io",)))
                text, rule = render(sp, [self.ref(x) for x in sp[2]])
                self.mux_note(sp, None)
                st[f"rule:{rule}"] += 1
                if d == "output":
                    io_lines.append(f"assign {pn} = {text}; // [R:IO]")
                elif io.get("oe") is not None:
                    so = simp(*self.node_of(io["oe"], ("io",)))
                    otext = render(so, [self.ref(x) for x in so[2]])[0]
                    io_lines.append(f"assign {pn} = ({otext}) ? ({text}) : 1'bz; // [R:IO]")
            elif d in ("output", "bidir-or-tristate"):
                io_lines.append(f"// UNDECODED: {pn}: {'; '.join(io['und'])}")
            st["rule:IO"] += 1
        ports += [f"input wire {n} /* UNDECODED: {c} */" for n, (_t, c) in sorted(nl.srcs.items())]
        # ---- blocks
        blk = ""
        if self.blk_text:
            blk = BLOCK_NAME.sub(lambda m: self.ref(m.group(0)), self.blk_text)
            blk = "\n".join(l if len(l) < LINE_MAX else l.replace("; ", ";\n  ") for l in blk.split("\n"))     # tools cap a line near 40 k tokens
            st["rule:M9K"] += len(nl.m9k)
            st["rule:MAC"] += len(nl.mac)
        # ---- assemble
        hdr = [f"// pluribus cycloneiv_clean RTL lift: {nl.label}",
               "// structure-derived (no names in the bitstream): io_<ball> pads, generated r_/sr_/cnt_/st_/w_/bus_/add_/sub_/cmp_ names",
               "// FF model: async clear, then on the clock edge with enable: sync clear -> 0, sync load -> asdata, else D; power-up 0",
               "// `[R:<id>]` tags the rule that recovered each construct; `// UNDECODED` lines are inherited from the flat emit",
               "// combinational delay (empty = zero-delay); compile with -DLUT_DELAY=#1 for a hold-safe simulation (same macro as the flat emit)",
               "`ifndef LUT_DELAY\n`define LUT_DELAY\n`endif"]
        for k, v in sorted(nl.und.items()):
            hdr.append(f"// UNDECODED count: {k}: {v}")
        out = hdr + [f"module {self.module} (", "  " + ",\n  ".join(ports) if ports else "", ");"] + decl
        if blk:
            out.append(blk)                                   # block declarations precede their readers
        out += [l() if callable(l) else l for l in logic] + io_lines
        out.append("endmodule")
        self.count_muxes()
        self.stats["lines"] = len(out)
        return "\n".join(out) + "\n"

    def report(self):
        s = self.stats
        return dict(
            flat_luts=len(self.nl.luts), flat_ffs=len(self.nl.ffs), chains=s["chains"], chain_bits=s["chain_bits"],
            adders=s["rule:ADD"] + s["rule:ADDC"], subtractors=s["rule:SUB"], comparators=s["rule:CMP_GE"] + s["rule:CMP_GT"],
            counters=s["counters"] + s["rule:CNTL"], bundles=s["bundles"], reg_bits=s["reg_bits"], shift_registers=s["rule:SHIFT"] + s["rule:LFSR"], lfsrs=s["rule:LFSR"], fsms=s["fsms"],
            muxes=s["mux_constructs"], mux_nodes=s["mux_nodes"], sop=s["rule:SOP"], xor=s["rule:XOR"], tt=s["rule:TT"],
            flat_lut_left=s["rule:FLAT_LUT"], m9k=len(self.nl.m9k), mac=len(self.nl.mac), cone_cut=s["cone_cut"], loop_luts=s["loop_luts"],
            rtl_lines=s["lines"], adder_widths=sorted(self.adder_widths), fsm_state_bits=s["fsm_state_bits"], rules={k[5:]: v for k, v in s.items() if k.startswith("rule:")})


def lift(nl, prefix="io_", module="cyc4_top"):
    """-> (verilog text, report dict)."""
    L = Lift(nl, prefix, module)
    text = L.run()
    return text, L.report()
