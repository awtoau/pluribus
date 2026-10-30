#!/usr/bin/env python3
"""Generic structure classifier for M9K word tables (#165).

  python3 scripts/cycloneiv_clean_m9k_content_classify.py image [--dump tmp/m9k_dump] [--out tmp/dji_m9k_content]
  python3 scripts/cycloneiv_clean_m9k_content_classify.py selftest

image: reads the local per-block candidate hex files written by cycloneiv_clean_m9k_dump.py (x<W>.hex, one word per line) for the widths in
       WIDTHS_PER_BLOCK, runs every test on the whole table, on each address half (256/512) and on each bit lane, writes tmp/dji_m9k_content/*.json.
       Output stays local; docs / issues carry structure-level results only.
Tests (all numeric, each returns a statistic, none returns a verdict):
  sine      best single-tone fit of the signed series: residual rms / amplitude, tone cycles per table, quarter-wave symmetry error
  ramp      piecewise-linear fit of the unwrapped series (wrap modulus 2^W): R^2, step
  perm      nonzero span is a permutation of 0..N-1 / of a stride set
  cmod      two lanes (lo/hi half of the word) as (I, Q): modulus spread (std / mean)
  lfsr      Berlekamp-Massey linear complexity of bit streams (a PRBS of degree n gives n); random of length L gives ~L/2
  decay     ratio constancy of a monotone series (geometric decay)
  consts    run-length structure (distinct values, longest run)
Log: tmp/logs/cycloneiv_clean_m9k_content_classify.log.
"""
import argparse
import json
import logging
import math
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_m9k_content_classify.log")
log = logging.getLogger("m9k_classify")
# block -> candidate widths to analyse (wiring-consistent widths from the dump summary; 8-vs-9 and 16-vs-18 both listed)
WIDTHS_PER_BLOCK = {"i056_x7_y57": (18,), "i057_x7_y58": (18, 16), "i084_x7_y85": (18,), "i085_x7_y86": (18, 16),
                    "i243_x36_y64": (18, 16), "i261_x36_y82": (18,), "i596_x94_y57": (9,), "i597_x94_y58": (9, 8)}


def signed(v, w):
    return v - (1 << w) if v >> (w - 1) else v


def bm_linear_complexity(bits):
    """Berlekamp-Massey over GF(2): length of the shortest LFSR producing `bits`."""
    n = len(bits)
    c = [0] * n
    b = [0] * n
    c[0] = b[0] = 1
    L, m = 0, -1
    for i in range(n):
        d = bits[i]
        for j in range(1, L + 1):
            d ^= c[j] & bits[i - j]
        if d:
            t = c[:]
            for j in range(n - i + m):
                if i - m + j < n:
                    c[i - m + j] ^= b[j]
            if L <= i // 2:
                L, m, b = i + 1 - L, i, t
    return L


def t_lfsr(bits, minlen=64):
    bits = [int(x) for x in bits]
    if len(bits) < minlen or sum(bits) in (0, len(bits)):
        return None
    L = bm_linear_complexity(bits)
    return {"len": len(bits), "linear_complexity": L, "random_expect": len(bits) // 2, "ones_frac": round(sum(bits) / len(bits), 3)}


def t_sine(x, w=None):
    """Single-tone fit by FFT peak refinement; x signed series."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 16 or np.ptp(x) == 0:
        return None
    xc = x - x.mean()
    f = np.abs(np.fft.rfft(xc * np.hanning(n)))
    k0 = int(np.argmax(f[1:])) + 1
    best = None
    t = np.arange(n)
    for cyc in np.linspace(max(k0 - 1, 0.25), k0 + 1, 401):
        a = np.stack([np.sin(2 * np.pi * cyc * t / n), np.cos(2 * np.pi * cyc * t / n), np.ones(n)], 1)
        co, *_ = np.linalg.lstsq(a, x, rcond=None)
        r = x - a @ co
        s = float(np.sqrt((r ** 2).mean()))
        if best is None or s < best[0]:
            best = (s, cyc, float(np.hypot(co[0], co[1])), float(co[2]))
    s, cyc, amp, off = best
    return {"cycles_per_table": round(cyc, 3), "amplitude": round(amp, 1), "offset": round(off, 1), "resid_rms_over_amp": round(s / amp, 4) if amp else None}


def t_ramp(x, w):
    """Unwrap mod 2^w by the smallest-magnitude step; R^2 of a linear and a quadratic fit."""
    m = 1 << w
    x = np.asarray(x, np.int64) % m
    d = np.diff(x)
    d = (d + m // 2) % m - m // 2
    ph = np.concatenate([[x[0]], x[0] + np.cumsum(d)]).astype(float)
    t = np.arange(len(ph))
    out = {}
    for deg in (1, 2):
        c = np.polyfit(t, ph, deg)
        r = ph - np.polyval(c, t)
        out[f"deg{deg}_resid_over_span"] = round(float(np.abs(r).max() / max(np.ptp(ph), 1)), 5)
    out["mean_step"] = round(float(d.mean()), 2)
    out["step_distinct"] = int(len(set(d.tolist())))
    out["total_wraps"] = round(float(ph[-1] - ph[0]) / m, 3)
    return out


def t_perm(x):
    nz = [v for v in x]
    n = len(nz)
    s = set(nz)
    out = {"n": n, "distinct": len(s)}
    out["permutation_of_0_to_n-1"] = bool(len(s) == n and s == set(range(n)))
    out["permutation_of_1_to_n"] = bool(len(s) == n and s == set(range(1, n + 1)))
    out["distinct_frac"] = round(len(s) / n, 3) if n else 0
    return out


def t_cmod(x, w):
    """Lo/hi half split as (I, Q) signed; modulus spread."""
    h = w // 2
    if h < 3:
        return None
    i = np.array([signed(v & ((1 << h) - 1), h) for v in x], float)
    q = np.array([signed((v >> h) & ((1 << h) - 1), h) for v in x], float)
    r = np.hypot(i, q)
    if r.mean() == 0:
        return None
    return {"lane_bits": h, "modulus_std_over_mean": round(float(r.std() / r.mean()), 4), "modulus_mean": round(float(r.mean()), 2)}


def t_decay(x):
    x = np.asarray(x, float)
    x = x[x > 0]
    if len(x) < 6:
        return None
    mono = float((np.diff(x) <= 0).mean()), float((np.diff(x) >= 0).mean())
    lr = np.diff(np.log(x))
    return {"n": len(x), "monotone_down_frac": round(mono[0], 3), "monotone_up_frac": round(mono[1], 3),
            "log_step_std_over_mean": round(float(lr.std() / abs(lr.mean())), 3) if lr.mean() else None}


def t_consts(x):
    runs, last = [], None
    for v in x:
        if v == last:
            runs[-1] += 1
        else:
            runs.append(1)
            last = v
    return {"distinct_values": len(set(x)), "runs": len(runs), "longest_run": max(runs) if runs else 0}


def t_gf2_linear(words, blk=256):
    """CRC / syndrome / bit-reversal tables are GF(2)-linear in the index: t[i ^ j] == t[i] ^ t[j].  Fraction over aligned blocks of `blk` words."""
    out = {}
    for a in range(0, len(words) - blk + 1, blk):
        t = words[a:a + blk]
        if not any(t) or t[0] != 0:
            continue
        ok = sum(1 for i in range(1, blk) for j in range(i + 1, min(blk, i + 9)) if t[i ^ j] == t[i] ^ t[j])
        tot = sum(1 for i in range(1, blk) for j in range(i + 1, min(blk, i + 9)))
        out[str(a)] = round(ok / tot, 3)
    return out or None


def segments(words):
    """Maximal nonzero spans (>= 8 words, gaps up to 2 zero words bridged)."""
    segs, s, gap = [], None, 0
    for i, v in enumerate(list(words) + [0] * 4):
        if v:
            if s is None:
                s = i
            gap = 0
            e = i
        elif s is not None:
            gap += 1
            if gap > 2:
                if e - s + 1 >= 8:
                    segs.append((s, e))
                s = None
    return segs


def classify_table(words, w):
    """All tests on one table: whole, per nonzero segment, per bit lane streams."""
    res = {"width": w, "depth": len(words), "nonzero_words": int(sum(1 for v in words if v)),
           "set_bits": int(sum(bin(v).count("1") for v in words)), "segments": []}
    for a, b in segments(words):
        seg = words[a:b + 1]
        sv = [signed(v, w) for v in seg]
        r = {"start": a, "end": b, "len": len(seg), "consts": t_consts(seg), "sine": t_sine(sv), "ramp": t_ramp(seg, w),
             "perm": t_perm(seg), "cmod": t_cmod(seg, w), "decay": t_decay(seg)}
        r["lfsr_bit0"] = t_lfsr([v & 1 for v in seg])
        r["lfsr_word_stream"] = t_lfsr([(v >> k) & 1 for v in seg for k in range(w)])
        res["segments"].append(r)
    res["gf2_linear_blocks256"] = t_gf2_linear(words)
    res["lane_lfsr"] = {str(k): t_lfsr([(v >> k) & 1 for v in words if True]) for k in range(w)}
    res["lfsr_whole_stream"] = t_lfsr([(v >> k) & 1 for v in words for k in range(w)][:4096])
    return res


def load_hex(path):
    return [int(l, 16) for l in open(path) if l.strip()]


def run_image(dump, out):
    os.makedirs(out, exist_ok=True)
    allres = {}
    for blk, widths in WIDTHS_PER_BLOCK.items():
        for w in widths:
            p = os.path.join(dump, f"m9k_{blk}.x{w}.hex")
            if not os.path.exists(p):
                log.warning("missing %s", p)
                continue
            r = classify_table(load_hex(p), w)
            allres[f"{blk}.x{w}"] = r
            log.info("%s x%d: nonzero=%d segments=%d", blk, w, r["nonzero_words"], len(r["segments"]))
            for s in r["segments"]:
                if s["len"] >= 64:
                    log.info("  seg %d..%d sine=%s ramp=%s perm=%s lfsr=%s", s["start"], s["end"], s["sine"], s["ramp"], s["perm"]["permutation_of_0_to_n-1"], s["lfsr_word_stream"])
            log.info("  whole-stream lfsr=%s", r["lfsr_whole_stream"])
    json.dump(allres, open(os.path.join(out, "classify.json"), "w"), indent=1)
    return allres


def selftest():
    """Synthetic tables: each test must fire on its own structure and not on random data."""
    rng = np.random.default_rng(1)
    n = 512
    k = np.arange(n)
    sin = [int(round(1000 * math.sin(2 * math.pi * 4 * i / n))) for i in k]
    assert t_sine(sin)["resid_rms_over_amp"] < 0.002 and abs(t_sine(sin)["cycles_per_table"] - 4) < 0.05
    rnd = [int(v) for v in rng.integers(-1000, 1000, n)]
    assert t_sine(rnd)["resid_rms_over_amp"] > 0.5
    ramp = [(511 + 1536 * i) % (1 << 18) for i in k]
    assert t_ramp(ramp, 18)["deg1_resid_over_span"] < 1e-3
    perm = [int(v) for v in rng.permutation(768)]
    assert t_perm(perm)["permutation_of_0_to_n-1"] and not t_perm([v % 700 for v in perm])["permutation_of_0_to_n-1"]
    cm = [((int(round(100 * math.cos(a))) & 0x1FF) | ((int(round(100 * math.sin(a))) & 0x1FF) << 9)) for a in rng.uniform(0, 6.28, 200)]
    assert t_cmod(cm, 18)["modulus_std_over_mean"] < 0.02
    assert t_cmod([int(v) for v in rng.integers(1, 1 << 18, 200)], 18)["modulus_std_over_mean"] > 0.2
    st = [1] * 11                                   # PRBS11 x^11 + x^9 + 1
    for i in range(11, 3000):
        st.append(st[i - 11] ^ st[i - 9])
    assert t_lfsr(st[:2000])["linear_complexity"] == 11
    assert t_lfsr([int(v) for v in rng.integers(0, 2, 2000)])["linear_complexity"] > 900
    crc = []                                            # CRC-16-CCITT byte table
    for b in range(256):
        c = b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
        crc.append(c)
    assert min(t_gf2_linear(crc).values()) == 1.0
    assert max(t_gf2_linear([0] + [int(v) for v in rng.integers(1, 65535, 255)]).values()) < 0.1
    dec = [int(4000 * 0.9 ** i) + 1 for i in range(30)]
    assert t_decay(dec)["monotone_down_frac"] == 1.0 and t_decay(dec)["log_step_std_over_mean"] < 0.05
    words = [0] * 100 + list(range(1, 60)) + [0] * 50
    assert segments(words) == [(100, 158)]
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("image", "selftest"))
    ap.add_argument("--dump", default=os.path.join(REPO, "tmp", "m9k_dump"))
    ap.add_argument("--out", default=os.path.join(REPO, "tmp", "dji_m9k_content"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(filename=LOG, level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger().addHandler(logging.StreamHandler(sys.stderr))
    if a.cmd == "selftest":
        selftest()
    else:
        run_image(a.dump, a.out)


if __name__ == "__main__":
    main()
