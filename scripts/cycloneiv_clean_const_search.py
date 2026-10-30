#!/usr/bin/env python3.15t
"""Find protocol constants and CRCs in a recovered Cyclone IV netlist (emit.Netlist); the constants come from a spec file, none are built in.

  python3.15t scripts/cycloneiv_clean_const_search.py --nl tmp/x/nl.pkl|--rbf image.rbf --spec spec.json [--out hits.json]
spec.json: {"consts": {name: {"hex": "..", "width": N}}, "counts": {name: int}, "crc": {name: {"width": N, "poly": int}}}
Searches (each reports matches and zero-hit negatives, with FF / M9K ids, clock domain, centroid):
  m9k        const bytes in every M9K block at the 9 widths (byte stream, plain / bit-reversed bytes); exact word equality for width >= 16; CRC byte tables
  comparator LUT cones that AND `width` literals whose polarity count equals popcount(const) (bit order is not recoverable from a cone alone)
  counter    counters (patterns.counters) with a comparator literal set: compared value = bits at literal 1; reported when value in {count-1, count, count+1}
  crc        LFSR / parallel-CRC groups of patterns.detect whose characteristic polynomial equals the spec CRC (or its reciprocal)
Log: tmp/logs/cycloneiv_clean_const_search.log
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
from lifters.cycloneiv_clean import m9k, patterns as P  # noqa: E402

log = logging.getLogger("const_search")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_const_search.log")
MIN_STREAM_BYTES = 2          # shorter byte strings match random ROM content everywhere; counted only
REV8 = np.array([int(f"{i:08b}"[::-1], 2) for i in range(256)], np.uint8)


def crc_table(width, poly, reflected):
    """256-entry table of the CRC register update by one byte (init-independent)."""
    top, mask = 1 << (width - 1), (1 << width) - 1
    out = []
    for b in range(256):
        if reflected:
            r = b
            rp = int(f"{poly:0{width}b}"[::-1], 2)
            for _ in range(8):
                r = (r >> 1) ^ rp if r & 1 else r >> 1
        else:
            r = b << (width - 8)
            for _ in range(8):
                r = ((r << 1) ^ poly) & mask if r & top else (r << 1) & mask
        out.append(r)
    return out


def word_bytes(words):
    """uint8 [depth, w] (bit 0 first) -> little-endian byte stream, ceil(w/8) bytes per word (w < 8: packed bit stream)."""
    d, w = words.shape
    if w < 8:
        flat = np.pad(words.reshape(-1), (0, (-words.size) % 8))
        return np.packbits(flat.reshape(-1, 8), axis=1, bitorder="little").reshape(-1)
    nb = (w + 7) // 8
    pad = np.pad(words, ((0, 0), (0, nb * 8 - w)))
    return np.packbits(pad.reshape(d * nb, 8), axis=1, bitorder="little").reshape(-1)


def find_all(stream, pat):
    s, p = stream.tobytes(), bytes(pat)
    out, i = [], s.find(p)
    while i != -1:
        out.append(i)
        i = s.find(p, i + 1)
    return out


def search_m9k(nl, consts, crcs):
    res = {n: [] for n in list(consts) + [f"crc_table:{c}" for c in crcs]}
    seen_blocks = 0
    tables = {c: [(refl, crc_table(s["width"], s["poly"], refl)[:16]) for refl in (True, False)] for c, s in crcs.items()}
    for i, b in enumerate(nl.m9k):
        bits = np.asarray(b["content"], np.uint8)
        if not bits.any():
            continue
        seen_blocks += 1
        bid = f"m9k_{b['x']}_{b['y']}_{b['inst']}"
        for w in m9k.WIDTHS:
            words = m9k.read_words(bits, w)
            if not words.any():
                continue
            st = word_bytes(words)
            ints = None
            for n, (raw, nbits) in consts.items():
                pats = {"plain": raw, "bitrev": bytes(REV8[list(raw)])}
                if len(raw) >= MIN_STREAM_BYTES:
                    for kind, p in pats.items():
                        for pos in find_all(st, p):
                            res[n].append(dict(block=bid, width=w, kind=f"stream-{kind}", byte_offset=pos))
                if w >= 16 and nbits <= w:
                    if ints is None:
                        ints = (words.astype(object) * (1 << np.arange(w, dtype=object))).sum(axis=1)
                    v = int.from_bytes(raw, "little")
                    for wd in np.nonzero(ints == v)[0].tolist():
                        res[n].append(dict(block=bid, width=w, kind="word-eq", word=int(wd)))
            for c, tl in tables.items():
                for refl, vals in tl:
                    if w < 8:
                        continue
                    ints = ints if ints is not None else (words.astype(object) * (1 << np.arange(w, dtype=object))).sum(axis=1)
                    seq = [int(v) for v in ints[:]]
                    for j in range(len(seq) - 15):
                        if seq[j:j + 16] == vals:
                            res[f"crc_table:{c}"].append(dict(block=bid, width=w, kind="table-" + ("refl" if refl else "norm"), word=j))
    return res, seen_blocks


def search_comparators(D, consts, conj, ctr):
    """Cones of `width` literals with popcount(const) ones.  A cone whose leaves are all bits of one counter is a counter value compare:
    kept as a hit only when its value equals the constant (either byte order), otherwise counted under `counter_compare_other`."""
    owner = {f: (i, p) for i, c in enumerate(ctr) for p, f in enumerate(c["ffs"])}
    res = {n: [] for n in consts}
    res["counter_compare_other"] = []
    for n, (raw, nbits) in consts.items():
        pop = sum(bin(x).count("1") for x in raw)
        want = {int.from_bytes(raw, "little"), int.from_bytes(raw, "big")}
        for s, lit in conj.items():
            if len(lit) != nbits or sum(1 for v in lit.values() if v) != pop:
                continue
            ffs = [k for k in lit if k in D.ff]
            clk = collections.Counter(D.ff[f]["clk"] for f in ffs).most_common(1)
            rec = dict(sig=s, leaves=len(lit), ff_leaves=len(ffs), pad_leaves=sum(1 for k in lit if k.startswith("pad_")),
                       m9k_leaves=sum(1 for k in lit if k.startswith("m9k_")), clk=clk[0][0] if clk else None, xy=D.xy(ffs))
            if all(k in owner for k in lit) and len({owner[k][0] for k in lit}) == 1:
                rec["counter_value"] = sum(1 << owner[k][1] for k, v in lit.items() if v)
                (res[n] if rec["counter_value"] in want else res["counter_compare_other"]).append(rec)
            else:
                res[n].append(rec)
    return res


def search_counters(D, ctr, counts, conj):
    owner = {}
    for i, c in enumerate(ctr):
        for p, f in enumerate(c["ffs"]):
            owner[f] = (i, p)
    res = {n: [] for n in counts}
    for s, lit in conj.items():
        own = {owner[k][0] for k in lit if k in owner}
        if len(own) != 1 or len(lit) < 3 or any(k not in owner for k in lit):
            continue
        i = own.pop()
        val = sum(1 << owner[k][1] for k, v in lit.items() if v)
        for n, cnt in counts.items():
            if val in (cnt - 1, cnt, cnt + 1):
                res[n].append(dict(sig=s, counter=i, width=ctr[i]["width"], literals=len(lit), value=val, rel=val - cnt,
                                   clk=D.ff[ctr[i]["ffs"][0]]["clk"], xy=D.xy(ctr[i]["ffs"])))
    return res


def search_crc(det, crcs):
    res = {c: [] for c in crcs}
    for g in det["lfsr"] + det["parallel"]:
        cp = g.get("charpoly")
        if cp is None:
            continue
        for c, s in crcs.items():
            want = (1 << s["width"]) | s["poly"]
            if g["n"] == s["width"] and cp in (want, P.reciprocal(want)):
                res[c].append(dict(n=g["n"], form=g["form"], kind=g["kind"], clk=g["clk"], xy=g["xy"], reciprocal=cp != want,
                                   serial_ext=g.get("ext"), members=len(g.get("members", []))))
    return res


def load_netlist(args):
    if args.nl:
        return pickle.load(open(args.nl, "rb"))
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    with heavy_guard.lease(gb, "cyc4_const_search", log):
        return emit.Builder(emit.Ctx(), args.rbf, "const_search").run()


def parse_spec(path):
    sp = json.load(open(path))
    consts = {}
    for n, c in sp.get("consts", {}).items():
        raw = bytes.fromhex(c["hex"])
        consts[n] = (raw, c.get("width", 8 * len(raw)))
    crcs = {n: dict(width=c["width"], poly=int(c["poly"])) for n, c in sp.get("crc", {}).items()}
    return consts, sp.get("counts", {}), crcs


def run(nl, consts, counts, crcs):
    D = P.Design(nl).prepare()
    conj = P.conj_literals(D)
    ctr, _cmp = P.counters(D)
    det = P.detect(nl)
    m9, blocks = search_m9k(nl, consts, crcs)
    out = dict(design=dict(luts=len(nl.luts), ffs=len(nl.ffs), m9k=len(nl.m9k), m9k_populated=blocks, conj_cones=len(conj), counters=len(ctr)),
               m9k=m9, comparator=search_comparators(D, consts, conj, ctr), counter=search_counters(D, ctr, counts, conj), crc=search_crc(det, crcs))
    out["counts"] = {sect: {k: len(v) for k, v in out[sect].items()} for sect in ("m9k", "comparator", "counter", "crc")}
    return out


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG, mode="a")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--nl")
    g.add_argument("--rbf")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    consts, counts, crcs = parse_spec(a.spec)
    out = run(load_netlist(a), consts, counts, crcs)
    log.info("design %s", out["design"])
    for sect, d in out["counts"].items():
        log.info("%s hits: %s", sect, d)
    if a.out:
        json.dump(out, open(a.out, "w"), indent=1, default=str)
        log.info("detail -> %s", a.out)


if __name__ == "__main__":
    main()
