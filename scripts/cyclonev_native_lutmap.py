#!/usr/bin/env python3.15t
"""Learn the ALM LUT address function (Quartus input vector -> raw LUT_MASK bit) per (half, mode) from the oracle.

Candidate family: 6 index bits; bit 5 is either a variable letter or the constant given by the mode suffix (E_0/E_1/F_0/F_1);
optionally bits 2 and 3 swap when index bit 5 is 1; B half optionally swaps letters c/d first. A candidate is consistent
when, for every sample and every reachable input vector v, raw[j(v)] == NOT q_mask[v].
Learning uses split A samples only; scoring on B uses the frozen winner (docs/altera/cycloneV/cyclonev-native-decoder.md).
"""
import collections
import itertools

LETTERS = "abcdef"


def vec_letters(v):
    return {p: (v >> k) & 1 for k, p in enumerate(LETTERS)}


def make_candidates(mode):
    """All candidates for a mode. Each candidate: (perm, const, cswap, bswap) where perm maps index position -> letter."""
    cands = []
    const = int(mode[-1]) if mode[-1] in "01" and mode[0] in "EF" else None
    if const is None:
        for perm in itertools.permutations(LETTERS):
            for cswap in (0, 1):
                cands.append((perm, None, cswap))
    else:
        for five in itertools.permutations(LETTERS, 5):
            for cswap in (0, 1):
                cands.append((five, const, cswap))
    return cands


def index_of(cand, bit, half_bswap):
    perm, const, cswap = cand
    b = dict(bit)
    if half_bswap:
        b["c"], b["d"] = b["d"], b["c"]
    idx = [b[perm[i]] for i in range(5 if const is not None else 6)]
    x5 = const if const is not None else idx[5]
    if cswap and x5:
        idx[2], idx[3] = idx[3], idx[2]
    return sum(v << i for i, v in enumerate(idx)) | (x5 << 5)


def consistent(cand, samples, bswap, perm_table=None):
    for used, q_mask, raw in samples:
        for v in range(64):
            bit = vec_letters(v)
            if any(bit[p] for p in LETTERS if p not in used):
                continue
            j = index_of(cand, bit, bswap)
            if perm_table is not None:
                j = perm_table[j]
            if ((q_mask >> v) & 1) == ((raw >> j) & 1):
                return False
    return True


def learn(samples_by_key, perm_table_for=None):
    """samples_by_key: {(half, mode, mlab): [(used, q_mask, raw)]}. Returns {(half, mode, mlab): [winning candidates]}."""
    out = {}
    for (half, mode, mlab), samples in samples_by_key.items():
        bswap = half == "B"
        pt = perm_table_for(mlab) if perm_table_for else None
        # rank samples by information (more used inputs first) and prune early
        samples = sorted(samples, key=lambda s: -len(s[0]))
        wins = [c for c in make_candidates(mode) if consistent(c, samples, bswap, pt)]
        out[(half, mode, mlab)] = wins
    return out
