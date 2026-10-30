#!/usr/bin/env python3.15t
"""Seed / reset cone of a register group (LFSR, CRC, any FF set) in a recovered Cyclone IV clean-pipeline netlist, #165.

  python3.15t scripts/cycloneiv_clean_seed_trace.py --nl NL.pkl --detect lfsr:0 [--hops 2] [--json out.json]
  python3.15t scripts/cycloneiv_clean_seed_trace.py --rbf X.rbf --ffs ff_1_2_3,ff_1_2_4,...
Per FF: dedicated controls (ena / aclr / sclr / sload / asdata) and the D-LUT.  Group level: every assignment of the signals
outside the group (the D-LUT "externals") under which every FF output is constant = a reset / seed state; reported as the
seed bit vector (FF order as given) plus the don't-care externals.  Then the cone of each external, ena and aclr signal
back to pads / FFs / block outputs (`--hops` register stages), FF leaves tagged with their detected counter if any.
Seed meaning: with the async clear (power-up 0) a group with no active seed assignment sits in the all-zero state.
Log: tmp/logs/cycloneiv_clean_seed_trace.log.  Memory: image-size netlist loads under heavy_guard (--rbf only).
"""
import argparse
import itertools
import json
import logging
import os
import pickle
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import patterns as P  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_seed_trace.log")
log = logging.getLogger("seed_trace")
MAX_EXT = 14      # decision: 2^14 assignments x group size is still instant; more externals = not a seed gate


def lut_out(L, val):
    """LUT output for pin values from `val` (signal -> 0/1, constants resolved)."""
    i = 0
    for k, p in enumerate(L["pins"]):
        v = P.CONSTV[p] if p in P.CONSTV else val[p]
        i |= v << k
    return (L["init"] >> i) & 1


def ff_const_under(D, name, ext_val, members):
    """Output of the D-LUT of `name` if constant over all member-pin values given the external assignment, else None."""
    L = D.lut[D.ff[name]["d"]]
    free = sorted({p for p in L["pins"] if p in members})
    outs = set()
    for bits in itertools.product((0, 1), repeat=len(free)):
        val = dict(ext_val)
        val.update(zip(free, bits))
        outs.add(lut_out(L, val))
    return outs.pop() if len(outs) == 1 else None


def seed_assignments(D, ffs):
    """-> (externals, [(assignment dict, seed list)], dontcare list). Group D-cones must be single LUTs (gate-in-LUT form)."""
    members = set(ffs)
    ext = []
    for f in ffs:
        d = D.ff[f]["d"]
        if d not in D.lut:
            return ext, None, "D of %s is not a LUT output (%s)" % (f, d)
        for p in D.lut[d]["pins"]:
            if p not in P.CONSTV and p not in members and p not in ext:
                ext.append(p)
    if len(ext) > MAX_EXT:
        return ext, None, "%d externals > %d" % (len(ext), MAX_EXT)
    found = []
    for bits in itertools.product((0, 1), repeat=len(ext)):
        a = dict(zip(ext, bits))
        seed = [ff_const_under(D, f, a, members) for f in ffs]
        if all(s is not None for s in seed):
            found.append((a, seed))
    return ext, found, None


def reduce_dontcare(ext, found):
    """Merge assignments with the same seed: externals that take both values for the same seed vector are don't-care."""
    by_seed = {}
    for a, seed in found:
        by_seed.setdefault(tuple(seed), []).append(a)
    out = []
    for seed, al in by_seed.items():
        fixed = {}
        for e in ext:
            vals = {a[e] for a in al}
            if len(vals) == 1:
                fixed[e] = vals.pop()
        out.append((list(seed), fixed, len(al)))
    return out


def fixed_point(D, ffs):
    """Lock state m of the group's affine step (gate idle): FF_next = A FF + c, A m + c = m. -> list of bits in `ffs` order, or None.
    Per-stage inversions fold into c, so FF-all-zero is not the lock state of the logical LFSR; logical state = FF ^ m."""
    n, idx = len(ffs), {f: i for i, f in enumerate(ffs)}
    rows = []
    for i, f in enumerate(ffs):
        a = D.faff.get(f)
        if a is None:
            return None
        mask, c = a
        row = 1 << i                                  # (I + A) m = c
        for j in P._bits(mask):
            g = D.leaf_names[j]
            if g in idx:
                row ^= 1 << idx[g]
        rows.append((row, c))
    sol, piv = [], {}
    for row, c in rows:                               # Gauss over GF(2), augmented bit n
        r = row | (c << n)
        for b, pr in piv.items():
            if (r >> b) & 1:
                r ^= pr
        low = r & ((1 << n) - 1)
        if not low:
            if r >> n:
                return None
            continue
        b = low.bit_length() - 1
        for k in list(piv):
            if (piv[k] >> b) & 1:
                piv[k] ^= r
        piv[b] = r
    if len(piv) < n:
        return None
    return [(piv[b] >> n) & 1 for b in range(n)]


def cone(D, sig, hops, counters):
    """{hop: [(kind, name, tag)]} register-stage layers of the support of `sig`."""
    layers, cur, seen = {}, {sig}, set()
    for h in range(hops + 1):
        leaves = set()
        for s in cur:
            leaves |= D.support(s, 0)
        layers[h] = sorted((D.kind(x), x, counters.get(x, "")) for x in leaves)
        nxt = {x for x in leaves if x in D.ff and x not in seen and D.ff[x]["d"]}
        seen |= nxt
        cur = {D.ff[x]["d"] for x in nxt}
        if not cur:
            break
    return layers


def literal_form(D, sig):
    """AND-of-literals description of a LUT cone, or None."""
    memo = P.conj_literals(D) if not hasattr(D, "_conj") else D._conj
    D._conj = memo
    return memo.get(sig)


def trace(D, ffs, hops, counters, out):
    res = dict(ffs=ffs, n=len(ffs))
    members = set(ffs)
    per_ff = []
    for f in ffs:
        F = D.ff[f]
        per_ff.append({k: F.get(k) for k in ("clk", "ena", "aclr", "sclr", "sload", "asdata", "d")})
    res["per_ff"] = per_ff
    ctl = {k: sorted({str(F[k]) for F in per_ff if F[k]}) for k in ("ena", "aclr", "sclr", "sload", "asdata", "clk")}
    res["controls"] = ctl
    ext, found, why = seed_assignments(D, ffs)
    res["externals"] = ext
    if found is None:
        res["seed"] = None
        res["seed_note"] = why
    else:
        merged = reduce_dontcare(ext, found)
        res["seed"] = [dict(bits="".join(str(b) for b in s), ones=sum(s), fixed=fx, assignments=n) for s, fx, n in merged]
        res["seed_note"] = "no assignment makes every FF constant" if not found else ""
        m = fixed_point(D, ffs)
        res["lock_state"] = None if m is None else "".join(map(str, m))
        for s in res["seed"]:
            if m is not None:
                lg = [int(b) ^ x for b, x in zip(s["bits"], m)]
                s["logical"] = "".join(map(str, lg))
                s["locked"] = not any(lg)
    sig_cones = {}
    for name in sorted(set(ext) | {s for k in ("ena", "aclr") for s in ctl[k]}):
        if name in P.CONSTV or name in members:
            continue
        lay = cone(D, name, hops, counters)
        lit = literal_form(D, name) if name in D.lut else None
        sig_cones[name] = dict(layers={h: l for h, l in lay.items()}, literals=lit)
    res["cones"] = sig_cones
    return res


def render(res):
    L = [f"group n={res['n']}  FFs: {' '.join(res['ffs'])}", "controls: " + json.dumps(res["controls"])]
    L.append("externals of the D-LUTs: " + " ".join(res["externals"]))
    if res["seed"] is None:
        L.append("seed: not derived: " + res["seed_note"])
    elif not res["seed"]:
        L.append("seed: " + res["seed_note"])
    L.append("lock state (FF coords): %s" % res.get("lock_state"))
    for s in res["seed"] or []:
        L.append("logical seed (FF^lock) %s locked=%s" % (s.get("logical"), s.get("locked")))
        L.append(f"seed bits (FF order above) {s['bits']}  ones={s['ones']}  forced when {s['fixed']} ({s['assignments']} assignments)")
    for name, c in res["cones"].items():
        L.append(f"cone {name}: literals={c['literals']}")
        for h, lay in c["layers"].items():
            kinds = {}
            for k, _n, _t in lay:
                kinds[k] = kinds.get(k, 0) + 1
            L.append(f"   hop {h}: {kinds}  " + " ".join(f"{n}{'[' + t + ']' if t else ''}" for _k, n, t in lay[:16]) + (" ..." if len(lay) > 16 else ""))
    return "\n".join(L)


def counter_tags(res):
    tags = {}
    for i, c in enumerate(res["counters"]):
        for k, f in enumerate(c["ffs"]):
            tags[f] = f"ctr{i}w{c['width']}b{k}"
    return tags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", help="pickled emit Netlist")
    ap.add_argument("--rbf", help="bitstream plane (.rbf) to emit from")
    ap.add_argument("--detect", help="kind:index into patterns.detect result (lfsr / parallel / ring)")
    ap.add_argument("--ffs", help="comma separated FF names")
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--json")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    if a.nl:
        nl = pickle.load(open(a.nl, "rb"))
    else:
        import heavy_guard
        from lifters.cycloneiv_clean import emit
        gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
        with heavy_guard.lease(gb, "cyc4_seed_trace", log):
            nl = emit.Builder(emit.Ctx(), a.rbf, "seed").run()
    D = P.Design(nl).prepare()
    det = P.detect(nl)
    if a.ffs:
        ffs = a.ffs.split(",")
    else:
        kind, idx = a.detect.split(":")
        ffs = det[kind][int(idx)]["members"]
    r = trace(D, ffs, a.hops, counter_tags(det), None)
    log.info(render(r))
    if a.json:
        json.dump(r, open(a.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
