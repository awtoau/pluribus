#!/usr/bin/env python3.15t
"""MCU control interface (SPI-style register file) in a recovered Cyclone IV clean-pipeline netlist, #165.

  python3.15t scripts/cycloneiv_clean_spi_trace.py --nl NL.pkl --pad AB11 [--tag image] [--addr-bits 8] [--show 0-7,e2-eb]
Starting from the serial data input pad, structure only (counts / register map / FF groups); evidence tags V (traced) / I (inferred):
  1 chain      shift chain: FF on the pad, successors `prev & lit(g)` with a common enable; g = frame-clear gate
  2 pads       control pads in the cone of the shift enable (frame = also in cone(g); bit clock = rest); MISO = output pad whose
               driver cone reaches the address register
  3 address    FFs loaded (sload / asdata) from chain taps = address register; command / capture groups = FFs fed by a chain tap
               under one enable; write-enable decode = exact enumeration over address bits + opaque phase terms
  4 readback   address-dependent FF slices behind the MISO cone, source leaves per address (write-register FF = RF, else other)
  5 compare    8-bit-style equality trees (AND of pair XNORs) with a register-file operand, combiner LUTs
Tap t (chain index, 0 = pad FF) carries data bit t-1 (MSB first on the wire). Log: tmp/logs/cycloneiv_clean_spi_trace.log,
results tmp/dji_spi/<tag>.json. Netlist is read-only; no decoder code is touched.
"""
import argparse
import collections
import itertools
import json
import logging
import os
import pickle
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_spi_trace.log")
OUT = os.path.join(REPO, "tmp", "dji_spi")
log = logging.getLogger("spi_trace")
CV = {"1'b1": 1, "1'b0": 0}
MAX_VARS = 22      # decision: 2^22 enumerations per enable net is the ceiling; wider cones are reported undecoded


class Net:
    def __init__(self, nl):
        self.nl = nl
        self.ff = {F["name"]: F for F in nl.ffs}
        self.lut = {L["name"]: L for L in nl.luts}
        self.cons = collections.defaultdict(list)
        for L in nl.luts:
            for p in set(L["pins"]):
                self.cons[p].append(L["name"])
        for F in nl.ffs:
            for k in ("d", "ena", "sload", "sclr", "asdata"):
                if F.get(k):
                    self.cons[F[k]].append(F["name"] + "." + k)
        self._r = {}
        self._has = {}

    def red(self, s):
        """(signals, truth table) of a LUT output with constants folded and don't-care pins dropped; None for non-LUT."""
        if s in self._r:
            return self._r[s]
        L = self.lut.get(s)
        if L is None or L["mode"] == "cin":
            self._r[s] = None
            return None
        sigs = []
        for p in L["pins"]:
            if p not in CV and p not in sigs:
                sigs.append(p)
        tt = []
        for idx in range(1 << len(sigs)):
            v = dict(zip(sigs, [(idx >> i) & 1 for i in range(len(sigs))]))
            i = 0
            for k, p in enumerate(L["pins"]):
                i |= (CV[p] if p in CV else v[p]) << k
            tt.append((L["init"] >> i) & 1)
        tt = list(tt)
        j = 0
        while j < len(sigs):
            n = len(sigs)
            if all(tt[i] == tt[i ^ (1 << j)] for i in range(1 << n)):
                tt = [tt[(i & ((1 << j) - 1)) | ((i >> j) << (j + 1))] for i in range(1 << (n - 1))]
                sigs = sigs[:j] + sigs[j + 1:]
                j = 0
            else:
                j += 1
        self._r[s] = (sigs, tt)
        return self._r[s]

    def comb_leaves(self, sig, depth=40):
        """leaf signals (FF / pad / carry / block outputs) of the combinational cone of `sig`."""
        out, seen = set(), set()

        def rec(s, d):
            if s in CV or s in seen:
                return
            seen.add(s)
            r = self.red(s) if d > 0 else None
            if r is None:
                out.add(s)
            else:
                for x in r[0]:
                    rec(x, d - 1)
        rec(sig, depth)
        return out

    def reach(self, sig, hops, kinds=("pad_",), edges=("d", "ena", "sclr", "sload", "asdata")):
        """signals of the given prefixes in the cone of `sig` through `hops` FF stages (D and enable edges)."""
        found, seen, cur = set(), set(), {sig}
        for _ in range(hops + 1):
            leaves = set()
            for s in cur:
                leaves |= self.comb_leaves(s)
            found |= {x for x in leaves if x.startswith(kinds)}
            nxt = set()
            for x in leaves:
                if x in self.ff and x not in seen:
                    seen.add(x)
                    F = self.ff[x]
                    nxt |= {F[k] for k in edges if F.get(k)}
            cur = nxt
            if not cur:
                break
        return found

    def ev(self, sig, env):
        if sig in CV:
            return CV[sig]
        if sig in env:
            return env[sig]
        s, tt = self.red(sig)
        i = 0
        for k, x in enumerate(s):
            i |= self.ev(x, env) << k
        return tt[i]

    def has(self, sig, aset):
        key = (sig, id(aset))
        if key in self._has:
            return self._has[key]
        r = sig in aset
        if not r:
            rr = self.red(sig)
            r = rr is not None and any(self.has(x, aset) for x in rr[0])
        self._has[key] = r
        return r

    def partial(self, sig, env, cache):
        """('c', v) or ('s', leaves): support of `sig` after substituting env constants and dropping don't-care pins."""
        if sig in CV:
            return ("c", CV[sig])
        if sig in env:
            return ("c", env[sig])
        if sig in cache:
            return cache[sig]
        rr = self.red(sig)
        if rr is None:
            res = ("s", frozenset([sig]))
        else:
            s, tt = rr
            sub = [self.partial(x, env, cache) for x in s]
            vs = [(k, x) for k, x in enumerate(sub) if x[0] == "s"]
            t2 = []
            for idx in range(1 << len(vs)):
                i = sum(x[1] << k for k, x in enumerate(sub) if x[0] == "c")
                for j, (k, _x) in enumerate(vs):
                    i |= ((idx >> j) & 1) << k
                t2.append(tt[i])
            keep = list(range(len(vs)))
            j = 0
            while j < len(keep):
                m = len(keep)
                if all(t2[i] == t2[i ^ (1 << j)] for i in range(1 << m)):
                    t2 = [t2[(i & ((1 << j) - 1)) | ((i >> j) << (j + 1))] for i in range(1 << (m - 1))]
                    keep = keep[:j] + keep[j + 1:]
                    j = 0
                else:
                    j += 1
            res = ("c", t2[0]) if not keep else ("s", frozenset().union(*[vs[j][1][1] for j in keep]))
        cache[sig] = res
        return res


def find_chain(N, pad):
    pad = "pad_" + pad
    f0 = None
    for n, F in N.ff.items():
        d = F["d"]
        r = N.red(d) if d in N.lut else None
        if d == pad or (r and r[0] == [pad] and r[1] == [0, 1]):
            f0 = n
            break
    if f0 is None:
        return None
    shape = collections.Counter()
    for m, F in N.ff.items():
        r = N.red(F["d"]) if F["d"] in N.lut else None
        if F.get("ena") and r and len(r[0]) == 2 and r[1] in ([0, 1, 0, 0], [0, 0, 1, 0]):
            shape[F["ena"]] += 1
    best_en = None   # shift enable = most common (ena, clear gate) of `x AND NOT g` FFs
    chain, gate = [f0], None
    while True:
        prev, nxt = chain[-1], None
        for n in N.cons[prev]:
            if n.endswith(".d") or n not in N.lut:
                continue
            for c in N.cons[n]:
                if not c.endswith(".d"):
                    continue
                m = c[:-2]
                F = N.ff[m]
                if m in chain or not F.get("ena") or (best_en and F["ena"] != best_en):
                    continue
                r = N.red(n)
                if not r or prev not in r[0]:
                    continue
                if len(r[0]) == 1 and r[1] == [0, 1]:
                    g = None
                elif len(r[0]) == 2:
                    pi = r[0].index(prev)
                    gi = 1 - pi
                    g = r[0][gi]
                    t = r[1]      # prev AND NOT g (frame clear)
                    if not (t[1 << pi] == 1 and t[(1 << pi) | (1 << gi)] == 0 and t[1 << gi] == 0 and t[0] == 0):
                        continue
                else:
                    continue
                if gate is not None and g != gate and g is not None:
                    continue
                if nxt is None or shape[F["ena"]] > shape[N.ff[nxt[0]]["ena"]]:
                    nxt = (m, g)
        if nxt is None:
            break
        chain.append(nxt[0])
        gate = gate or nxt[1]
        best_en = N.ff[nxt[0]]["ena"]
    return chain, gate


def taps(N, chain):
    """captures: FFs whose D (buffer / inverter) or asdata is a chain tap -> list of (ff, tap, inv, ena, sload)."""
    idx = {c: i for i, c in enumerate(chain)}
    out = []
    for n, F in N.ff.items():
        if n in idx:
            continue
        d = F["d"]
        if F.get("asdata") in idx and F.get("sload"):
            out.append((n, idx[F["asdata"]], 0, F.get("ena"), F["sload"]))
        elif d in idx:
            out.append((n, idx[d], 0, F.get("ena"), None))
        else:
            r = N.red(d) if d in N.lut else None
            if r and len(r[0]) == 1 and r[0][0] in idx:
                out.append((n, idx[r[0][0]], int(r[1] == [1, 0]), F.get("ena"), None))
    return out


def decode(N, E, addr, aset):
    """{opaque assignment tuple: set(addresses)} for enable net E over the address FFs (`addr`, bit order) + opaque terms."""
    var, seen = [], set()

    def rec(s):
        if s in CV or s in seen:
            return
        seen.add(s)
        if s in aset or not N.has(s, aset):
            var.append(s)
            return
        for x in N.red(s)[0]:
            rec(x)
    rec(E)
    if len(var) > MAX_VARS:
        return None, None
    op = [v for v in var if v not in aset]
    sat = collections.defaultdict(set)
    for bits in itertools.product((0, 1), repeat=len(var)):
        env = dict(zip(var, bits))
        if N.ev(E, env):
            sat[tuple(env[o] for o in op)].add(sum(env.get(a, 0) << i for i, a in enumerate(addr)))
    return op, sat


def parse_show(s, nbits):
    out = []
    for part in s.split(","):
        a, _, b = part.partition("-")
        lo = int(a, 16)
        hi = int(b, 16) if b else lo
        out += [x for x in range(lo, hi + 1) if x < (1 << nbits)]
    return out


def trace(N, pad, tag, nbits, show):
    R = dict(pad=pad)
    ch = find_chain(N, pad)
    if ch is None:
        log.info("no FF on pad_%s", pad)
        return R
    chain, gate = ch
    pad_sig = "pad_" + pad
    en = collections.Counter(N.ff[c].get("ena") for c in chain[1:]).most_common(1)[0][0]
    R["chain"] = dict(ffs=chain, length=len(chain), enable=en, clear_gate=gate)
    log.info("[V] shift chain on %s: %d FFs %s, shift enable %s, clear gate %s", pad_sig, len(chain), " ".join(chain), en, gate)
    # pads
    cg = N.reach(gate, 6) if gate else set()
    ce = N.reach(en, 6)
    R["pads"] = dict(data=pad, frame_cs=sorted(p[4:] for p in cg), bit_clock=sorted(p[4:] for p in ce - cg - {pad_sig}))
    log.info("[V] pads in cone of shift enable: frame/clear %s, bit clock %s (cone depth 6 FF stages)", R["pads"]["frame_cs"], R["pads"]["bit_clock"])
    # captures
    caps = taps(N, chain)
    byload = collections.defaultdict(list)
    for n, t, inv, ena, sl in caps:
        if sl:
            byload[sl].append((n, t, inv, ena))
    addr_group = max(byload.values(), key=len) if byload else []
    addr = [None] * nbits
    for n, t, inv, ena in addr_group:
        if 1 <= t <= nbits:
            addr[t - 1] = n
    if None in addr:
        log.info("address register: %d of %d bits found from sload/asdata taps", sum(a is not None for a in addr), nbits)
        R["address_register"] = None
        return R
    sl = N.ff[addr[0]]["sload"]
    R["address_register"] = dict(ffs=addr, sload=sl, enable=N.ff[addr[0]].get("ena"))
    log.info("[V] address register %d FFs (bit0..): %s, load strobe %s, count enable %s", nbits, " ".join(addr), sl, N.ff[addr[0]].get("ena"))
    aset = set(addr)
    groups = collections.defaultdict(list)
    for n, t, inv, ena, s_ in caps:
        if not s_ and ena:
            groups[ena].append((n, t, inv))
    dec, undec, cmdg = {}, [], []
    for E, mem in groups.items():
        if not N.has(E, aset):
            cmdg.append((E, mem))
            continue
        op, sat = decode(N, E, addr, aset)
        if sat is None:
            undec.append(E)
            continue
        dec[E] = (op, sat, mem)
    R["capture_groups"] = dict(total=len(groups), address_decoded=len(dec), undecoded_wide=len(undec), not_address_decoded=len(cmdg),
                               size_hist=dict(collections.Counter(len(m) for m in groups.values())))
    log.info("[V] capture groups (FFs fed by a chain tap under one enable): %d total; address-decoded %d; wide/undecoded %d; others %d; sizes %s",
             len(groups), len(dec), len(undec), len(cmdg), R["capture_groups"]["size_hist"])
    amap = collections.defaultdict(list)
    phase = collections.Counter()
    nassign = collections.Counter()
    for E, (op, sat, mem) in dec.items():
        nassign[len(sat)] += 1
        for ov, av in sat.items():
            phase[tuple(zip(op, ov))] += 1
            for a in av:
                amap[a].append(E)
    exact = sum(1 for E, (op, sat, m) in dec.items() if sum(len(v) for v in sat.values()) == 1)
    R["write_decode"] = dict(addresses=len(amap), exact_single_address_nets=exact, nets=len(dec), assignments_per_net=dict(nassign),
                             enables_per_address=dict(collections.Counter(len(v) for v in amap.values())),
                             top_phase_terms=[[list(map(list, k)), v] for k, v in phase.most_common(4)])
    srt = sorted(amap)
    rng, st = [], srt[0] if srt else None
    for x, y in zip(srt, srt[1:] + [None]):
        if y != x + 1:
            rng.append((st, x))
            st = y
    R["write_decode"]["ranges"] = [[hex(a), hex(b)] for a, b in rng]
    log.info("[V] write enables: %d nets decode %d addresses, ranges %s; %d nets are one exact address; phase assignments per net %s; enables per address %s",
             len(dec), len(amap), R["write_decode"]["ranges"], exact, dict(nassign), R["write_decode"]["enables_per_address"])
    log.info("[V] common phase terms (opaque signals ANDed into every write enable, value required): %s", R["write_decode"]["top_phase_terms"])
    # register map
    RF = {}
    regmap = {}
    for a in sorted(amap):
        ents = []
        for E in amap[a]:
            mem = dec[E][2]
            for n, t, inv in mem:
                RF[n] = (a, t - 1, inv)
            ents.append(dict(enable=E, ffs=len(mem), bits=sorted(t - 1 for _n, t, _i in mem)))
        regmap[a] = ents
    R["register_map"] = {hex(a): v for a, v in regmap.items()}
    R["rf_ffs"] = {n: [hex(a), b] for n, (a, b, _i) in RF.items()}
    for a in show:
        log.info("[V] reg %02x write: %s", a, "; ".join("%s %d FFs bits %s" % (e["enable"], e["ffs"], e["bits"]) for e in regmap.get(a, [])) or "none")
    # command byte
    for E, mem in cmdg:
        log.info("[V] capture group (not address-decoded) enable %s: %d FFs taps %s", E, len(mem), sorted(t for _n, t, _i in mem))
    R["other_capture_groups"] = [dict(enable=E, ffs=[m[0] for m in mem], taps=sorted(m[1] for m in mem)) for E, mem in cmdg]
    cmd = max(cmdg, key=lambda g: len(g[1]), default=None)
    if cmd and len(cmd[1]) >= 6 and dec:
        cset = {m[0]: m for m in cmd[1]}
        E0 = next(iter(dec))
        best = None
        for leaf_node in _comb_nodes(N, E0):
            sup = N.comb_leaves(leaf_node)
            if len(sup) >= 6 and sup <= set(cset):
                sv = sorted(sup)
                sols = [bits for bits in itertools.product((0, 1), repeat=len(sv)) if N.ev(leaf_node, dict(zip(sv, bits)))]
                if len(sols) == 1 and (best is None or len(sv) > len(best[1])):
                    best = (leaf_node, sv, sols[0])
        if best:
            val = 0
            for f, b in zip(best[1], best[2]):
                val |= (b ^ cset[f][2]) << (cset[f][1] - 1)
            R["command_match"] = dict(node=best[0], bits=len(best[1]), value=val, group_enable=cmd[0],
                                      missing_bits=sorted(set(range(8)) - {cset[f][1] - 1 for f in best[1]}))
            log.info("[V] command match: node %s ANDs %d command-register bits (unique satisfying value 0x%02x, bits not in the match %s) strobed by %s",
                     best[0], len(best[1]), val, R["command_match"]["missing_bits"], cmd[0])
    # phase node description
    ph = [n for n, _ in phase.most_common(4) if n]
    if ph:
        node = [s for s, _v in ph[0] if s in N.lut]
        for pn in node[:1]:
            leaves = sorted(N.comb_leaves(pn))
            if len(leaves) <= 16:
                sols = [dict(zip(leaves, bits)) for bits in itertools.product((0, 1), repeat=len(leaves)) if N.ev(pn, dict(zip(leaves, bits)))]
                grp = collections.defaultdict(list)
                for l in leaves:
                    grp[N.ff[l].get("ena") if l in N.ff else "-"].append(l)
                R["phase_node"] = dict(node=pn, leaves=leaves, satisfying=len(sols), enable_groups={str(k): v for k, v in grp.items()})
                log.info("[V] phase node %s: %d leaves, %d satisfying assignments; leaves by enable group %s", pn, len(leaves), len(sols), dict(grp))
    # MISO
    cand = []
    for io in N.nl.ios:
        if io["dir"] != "input" and io.get("drv"):
            c = N.reach(io["drv"], 4, kinds=("ff_",), edges=("d",))
            k = len(c & aset)
            if k >= nbits - 1:
                cand.append((io["ball"], io["drv"], k))
    R["miso"] = [dict(ball=b, driver=d, address_ffs=k) for b, d, k in cand]
    log.info("[V] output pads whose driver cone (4 FF stages) reaches the address register: %s", [(b, k) for b, _d, k in cand])
    if not cand:
        return R
    # readback slices: address-dependent FFs within 2 FF stages of the MISO driver
    drv = cand[0][1]
    lvl1 = {x for x in N.comb_leaves(drv) if x in N.ff}
    lvl2 = {y for x in lvl1 for y in N.comb_leaves(N.ff[x]["d"]) if y in N.ff}
    slices = []
    for f in sorted(lvl1 | lvl2):
        if f in aset or f in chain:
            continue
        sup = N.comb_leaves(N.ff[f]["d"])
        if len(sup & aset) >= nbits - 1 or sum(1 for x in N.reach(N.ff[f]["d"], 0, ("ff_",), ("d",)) if x in aset) >= nbits - 1:
            slices.append(f)
    R["readback_slices"] = slices
    log.info("[V] readback slices (address-dependent FFs <= 2 stages behind MISO): %d %s", len(slices), slices)
    tabs = {}
    for a in range(1 << nbits):
        env = {x: (a >> i) & 1 for i, x in enumerate(addr)}
        cache = {}
        tabs[a] = {s: N.partial(N.ff[s]["d"], env, cache) for s in slices}
    # bit position of each slice = majority tap of its register-file sources
    pos = {}
    for s in slices:
        c = collections.Counter()
        for a in range(1 << nbits):
            v = tabs[a][s]
            if v[0] == "s":
                for x in v[1]:
                    if x in RF:
                        c[RF[x][1]] += 1
        pos[s] = c.most_common(1)[0][0] if c else None
    R["slice_bit"] = pos

    def label(a, s):
        v = tabs[a][s]
        if v[0] == "c":
            return "const%d" % v[1]
        rf = sorted({"R%02x" % RF[x][0] for x in v[1] if x in RF})
        oth = sorted(x for x in v[1] if x not in RF)
        return "+".join(rf + oth)
    half = 1 << (nbits - 1)
    alias = {}
    for s in slices:
        alias[s] = sum(1 for a in range(half, 1 << nbits)
                       if tabs[a][s][0] == "s" and tabs[a - half][s][0] == "s" and tabs[a][s][1] == tabs[a - half][s][1])
    R["readback_alias_high_half"] = {s: alias[s] for s in slices}
    log.info("[V] slices whose sources at address a equal those at a-%d (address MSB ignored), of %d: %s", half, half, {s: alias[s] for s in slices})
    for a in show:
        row = {pos[s]: label(a, s) for s in slices}
        log.info("[V] read %02x: %s", a, dict(sorted(row.items(), key=lambda kv: -1 if kv[0] is None else kv[0])))
    own = collections.Counter()
    for a in range(1 << nbits):
        for s in slices:
            v = tabs[a][s]
            own["const" if v[0] == "c" else "rf_only" if all(x in RF for x in v[1]) else "has_other"] += 1
    R["readback_leaf_classes"] = dict(own)
    log.info("[V] readback (address, slice) cells: %s", dict(own))
    # non-register-file source FFs
    others = collections.Counter()
    for a in range(1 << nbits):
        for s in slices:
            v = tabs[a][s]
            if v[0] == "s":
                for x in v[1]:
                    if x not in RF:
                        others[x] += 1
    R["readback_other_sources"] = dict(others)
    en_other = collections.Counter(N.ff[x].get("ena") for x in others if x in N.ff)
    log.info("[V] readback leaves outside the register file: %d FFs, by enable %s", len(others), dict(en_other))
    # equality trees
    heq = {}
    for name, L in N.lut.items():
        if L["mode"] == "cin":
            continue
        r = N.red(name)
        s, tt = r
        n = len(s)
        if n not in (2, 4):
            continue
        for pairing in ([(0, 1)],) if n == 2 else ([(0, 1), (2, 3)], [(0, 2), (1, 3)], [(0, 3), (1, 2)]):
            if all(tt[i] == int(all(((i >> a) & 1) == ((i >> b) & 1) for a, b in pairing)) for i in range(1 << n)):
                heq[name] = [(s[a], s[b]) for a, b in pairing]
                break
    memo = {}

    def tree(root):
        if root in memo:
            return memo[root]
        memo[root] = None
        if root in heq:
            r = list(heq[root])
        elif root in N.lut and N.lut[root]["mode"] != "cin":
            s, tt = N.red(root)
            r = None
            if len(s) >= 2 and tt == [0] * (2 ** len(s) - 1) + [1]:
                r = []
                for x in s:
                    t = tree(x)
                    if t is None:
                        r = None
                        break
                    r += t
        else:
            r = None
        memo[root] = r
        return r
    roots = {n: t for n in N.lut if (t := tree(n)) and len(t) >= 3}
    inner = {x for n in roots for x in N.red(n)[0]}
    mx = {n: t for n, t in roots.items() if n not in inner}
    eq = []
    for n, t in mx.items():
        regs, other = collections.Counter(), []
        for a, b in t:
            for x, y in ((a, b), (b, a)):
                if x in RF:
                    regs[RF[x][0]] += 1
                    other.append(y)
                    break
        if regs:
            eq.append(dict(root=n, pairs=len(t), reg_addresses={hex(k): v for k, v in sorted(regs.items())}, other_side=other[:4],
                           consumers=N.cons.get(n, [])[:4]))
    R["equality_trees"] = dict(total_roots=len(mx), with_register_operand=len(eq), trees=eq)
    log.info("[V] equality trees (AND of >=3 pair-XNORs): %d maximal; %d with a register-file operand", len(mx), len(eq))
    for e in eq:
        if len(e["reg_addresses"]) == 1:
            log.info("[V]   %s %d pairs vs reg %s other-side e.g. %s -> %s", e["root"], e["pairs"], list(e["reg_addresses"])[0], e["other_side"][:2], e["consumers"][:2])
    comb = collections.defaultdict(list)
    for e in eq:
        for c in e["consumers"]:
            if c in N.lut:
                comb[c].append(e["root"])
    R["combiners"] = []
    for c, rs in comb.items():
        if len(rs) >= 2:
            s, tt = N.red(c)
            R["combiners"].append(dict(lut=c, roots=rs, inputs=s, tt="%x" % sum(b << i for i, b in enumerate(tt)),
                                       regs=sorted({k for e in eq if e["root"] in rs for k in e["reg_addresses"]}), consumers=N.cons.get(c, [])[:6]))
            log.info("[V] combiner %s over %d comparators (registers %s): inputs %s tt=%x -> %s", c, len(rs), R["combiners"][-1]["regs"], s,
                     sum(b << i for i, b in enumerate(tt)), N.cons.get(c, [])[:6])
    R["master"] = master(N, R, RF, {pad, *R["pads"]["frame_cs"], *R["pads"]["bit_clock"]})
    return R


def back_hops(N, sigs, n):
    """[(FFs first reached at hop h, non-FF leaves)] going back through D / enable / sclr / sload / asdata edges."""
    seen, cur, out = set(), set(sigs), []
    for _ in range(n):
        leaves = set()
        for s in cur:
            leaves |= N.comb_leaves(s)
        ffs = {x for x in leaves if x in N.ff} - seen
        out.append((ffs, {x for x in leaves if x not in N.ff}))
        seen |= ffs
        cur = {N.ff[x][k] for x in ffs for k in ("d", "ena", "sclr", "sload", "asdata") if N.ff[x].get(k)}
    return out


def master(N, R, RF, slave_pads, hops=8):
    """SPI master towards a radio chip: output pads driven by a mode mux (>= 2 select FFs = bits of one write register)."""
    M = {}

    def rfsrc(x):
        """register-file (address, bit) behind x: the FF itself or the FF of a one-stage buffer."""
        if x in RF:
            return RF[x][:2]
        F = N.ff.get(x)
        r = N.red(F["d"]) if F and F["d"] in N.lut else None
        if r and len(r[0]) == 1 and r[0][0] in RF:
            return RF[r[0][0]][:2]
        return None
    sel_by_addr = collections.defaultdict(list)
    for io in N.nl.ios:
        if io["dir"] == "input" or not io.get("drv") or io["drv"] not in N.lut:
            continue
        r = N.red(io["drv"])
        if not r or len(r[0]) < 3:
            continue
        sel = [x for x in r[0] if rfsrc(x)]
        if len(sel) >= 2 and len({rfsrc(x)[0] for x in sel}) == 1:
            sel_by_addr[rfsrc(sel[0])[0]].append((io["ball"], io["drv"], sel, [x for x in r[0] if x not in sel]))
    if not sel_by_addr:
        log.info("no output pad driven by a register-selected mux: no master engine found")
        M["found"] = False
        return M
    mdrv = [io["drv"] for io in N.nl.ios if io["dir"] != "input" and io.get("drv") and io["ball"] in {m["ball"] for m in R.get("miso", [])}]
    mux_sel = {rfsrc(x)[0] for d in mdrv for x in (N.red(d) or ([], 0))[0] if rfsrc(x)}
    addr = next((a for a in sel_by_addr if a in mux_sel), max(sel_by_addr, key=lambda a: len(sel_by_addr[a])))
    muxes = sel_by_addr[addr]
    M["found"] = True
    M["mode_register"] = addr
    M["outputs"] = []
    internal = []
    for ball, drv, sel, oth in muxes:
        s, tt = N.red(drv)
        bit = {x: rfsrc(x)[1] for x in sel}
        modes = {}
        for m in range(1 << len(sel)):
            tab = {}
            for v in range(1 << len(s)):
                env = {x: (v >> i) & 1 for i, x in enumerate(s)}
                if all(env[x] == (m >> k) & 1 for k, x in enumerate(sorted(sel, key=lambda x: bit[x]))):
                    tab[tuple(env[x] for x in oth)] = tt[v]
            dep = [o for k, o in enumerate(oth) if any(tab[a] != tab[tuple(1 - a[j] if j == k else a[j] for j in range(len(oth)))] for a in tab)]
            modes[m] = dep[0] if len(dep) == 1 else ("const%d" % list(tab.values())[0] if not dep else "+".join(dep))
        pas = {}
        for o in oth:
            cone = back_hops(N, [o], 3)
            pads = sorted({x[4:] for _f, non in cone for x in non if x.startswith("pad_")})
            pas[o] = pads
        M["outputs"].append(dict(ball=ball, driver=drv, select_bits=sorted(bit.values()), modes={str(k): v for k, v in modes.items()}, inputs_to_pads_3hops=pas))
        for v in modes.values():
            if isinstance(v, str) and v in N.ff and not pas.get(v):
                internal.append(v)
    log.info("[V] mode register %02x bits %s selects %d output muxes: %s", addr, sorted({b for m in M["outputs"] for b in m["select_bits"]}), len(muxes),
             [(m["ball"], m["modes"], m["inputs_to_pads_3hops"]) for m in M["outputs"]])
    log.info("[V] radio SPI pad-mux members: %s", " ".join(["pad_" + m["ball"] for m in M["outputs"]] + sorted({x for m in muxes for x in m[2]})))
    # input pad that also feeds the slave MISO mux and another LUT
    miso = [io["drv"] for io in N.nl.ios if io["dir"] != "input" and io.get("drv") and io["ball"] in {m["ball"] for m in R.get("miso", [])}]
    M["miso_in"] = []
    for d in miso:
        for x in (N.red(d) or ([], 0))[0]:
            if x.startswith("pad_") and x[4:] not in slave_pads:
                M["miso_in"].append(dict(pad=x[4:], consumers=N.cons[x]))
    log.info("[V] radio MISO input pad(s) (feed the slave MISO mux and the engine): %s", M["miso_in"])
    # engine
    H = back_hops(N, internal, hops)
    eng = set().union(*[f for f, _n in H[:5]])
    byena = collections.defaultdict(list)
    for x in eng:
        byena[N.ff[x].get("ena")].append(x)
    groups = {str(e): len(v) for e, v in byena.items() if len(v) >= 4 and e}
    M["engine"] = dict(outputs_internal=internal, ffs_within_5_hops=len(eng), enable_groups=groups)
    ctr = [(e, v) for e, v in byena.items() if e and len(v) >= 4 and sum(1 for x in v if N.ff[x].get("sclr")) == len(v)]
    for e, v in ctr:
        M["engine"].setdefault("counters", []).append(dict(enable=e, ffs=sorted(v), clear=N.ff[v[0]]["sclr"]))
        leaves = set()
        for x in v:
            leaves |= N.comb_leaves(N.ff[x]["d"])
        vs = sorted(v)
        for node in {c[:-2] if c.endswith(".d") else c for x in v for c in N.cons[x] if c in N.lut}:
            sup = N.comb_leaves(node)
            if sup and sup <= set(v) and len(sup) >= len(v) - 1 and len(sup) > 2:
                sv = sorted(sup)
                sols = [b for b in itertools.product((0, 1), repeat=len(sv)) if N.ev(node, dict(zip(sv, b)))]
                if len(sols) == 1:
                    M["engine"]["counters"][-1].setdefault("terminal_nodes", []).append(dict(node=node, support=sv, unique_state=list(sols[0])))
    log.info("[V] engine: %d FFs within 5 stages of the internal outputs; enable groups (>=4 FFs) %s; counters %s", len(eng), groups, M["engine"].get("counters"))
    log.info("[V] engine start / control enable cone: %s", [(h, sorted({(RF[x][0], RF[x][1]) for x in f if x in RF})) for h, (f, _n) in enumerate(H) if any(x in RF for x in f)][:4])
    rfh = []
    for h, (f, non) in enumerate(H):
        rfh.append(dict(hop=h, ffs=len(f), register_addresses=sorted({RF[x][0] for x in f if x in RF}), pads=sorted(x[4:] for x in non if x.startswith("pad_")),
                        m9k=sorted(x for x in non if x.startswith("m9k_"))))
    M["engine"]["backward_hops"] = rfh
    for e in rfh:
        if e["register_addresses"] or e["pads"] or e["m9k"]:
            log.info("[V]   hop %d: %d FFs, registers %s, pads %s, m9k %s", e["hop"], e["ffs"], e["register_addresses"], e["pads"], e["m9k"])
    # forward reach of registers to pads
    users = collections.defaultdict(set)
    for n, F in N.ff.items():
        for k in ("d", "ena", "sclr", "sload", "asdata"):
            if F.get(k):
                for l in N.comb_leaves(F[k]):
                    users[l].add(n)
    drvleaf = collections.defaultdict(set)
    for io in N.nl.ios:
        if io["dir"] != "input" and io.get("drv"):
            for l in N.comb_leaves(io["drv"]):
                drvleaf[l].add(io["ball"])
    byreg = collections.defaultdict(set)
    for n, (a, b, _i) in RF.items():
        byreg[a].add(n)
    M["register_forward"] = {}
    for a in sorted(byreg):
        cur, seen, pads = set(byreg[a]), set(byreg[a]), set()
        for _ in range(10):
            nx = set()
            for s in cur:
                nx |= users.get(s, set())
            nx -= seen
            seen |= nx
            cur = nx
        for x in seen:
            pads |= drvleaf.get(x, set())
        M["register_forward"][hex(a)] = sorted(pads)
    muxpads = {m["ball"] for m in M["outputs"]}
    ro = {m["ball"] for m in R.get("miso", [])}
    only = sorted(a for a, p in M["register_forward"].items() if p and set(p) <= muxpads | ro and set(p) & (muxpads - ro))
    M["registers_reaching_only_master_pads"] = only
    log.info("[V] write registers whose 10-stage forward cone reaches only the master output pads (+ slave MISO): %d %s", len(only), only[:40])
    return M


def _comb_nodes(N, sig):
    out, seen = [], set()

    def rec(s):
        if s in seen or s in CV:
            return
        seen.add(s)
        if N.red(s):
            out.append(s)
            for x in N.red(s)[0]:
                rec(x)
    rec(sig)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", required=True, help="pickled emit Netlist")
    ap.add_argument("--pad", required=True, help="serial data input pad (ball name, e.g. AB11)")
    ap.add_argument("--tag", default="spi")
    ap.add_argument("--addr-bits", type=int, default=8)
    ap.add_argument("--show", default="0-7,e2-eb", help="addresses (hex ranges) to print")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    nl = pickle.load(open(a.nl, "rb"))
    N = Net(nl)
    R = trace(N, a.pad, a.tag, a.addr_bits, parse_show(a.show, a.addr_bits))
    json.dump(R, open(os.path.join(OUT, a.tag + ".json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
