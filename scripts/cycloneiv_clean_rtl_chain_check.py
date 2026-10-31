#!/usr/bin/env python3.15t
"""Chain-level check of the RTL lift (#165): every recognised carry chain vs the LUT-level chain, random operand assignments.

  python3.15t scripts/cycloneiv_clean_rtl_chain_check.py [--cache tmp/rtl/image_nl.pkl | --hl NAME,...] [--vectors 64] [--negative-control]
Per chain: operand literals (ch["A"], ch["B"], polarity, constant carry-in) give A + B + c0; the LUT-level model (sum = INIT[{d,c,b,a}],
cout = INIT[{0,c,b,a}], carry signal polarity po per stage) must agree on every read sum bit and every carry signal.  Counts only.
--negative-control flips ch["c0"] (the chain's constant carry-in) on a copy of every chain before checking: this must raise the LUT-level
model's expected sum/carry at bit 0 against the (now-wrong) operand reconstruction, so a flipped chain must fail; 0 "bad" under this flag
means the check cannot distinguish a right answer from a wrong one and the real score above is not trustworthy.
Log tmp/logs/cycloneiv_clean_rtl_chain_check.log.
"""
import argparse
import logging
import os
import pickle
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
log = logging.getLogger("cycloneiv_clean_rtl_chain_check")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_rtl_chain_check.log")
CONSTV = {"1'b1": 1, "1'b0": 0}


def check(L, vectors, rnd):
    ok = bad = skipped = mixed = 0
    for ch in L.chain_list:
        if not ch["ok"]:
            continue
        luts, W = ch["luts"], ch["W"]
        sigs = sorted({p for l in luts for p in l["pins"] if p not in CONSTV and not p.startswith("co_")})
        mixed += bool(ch.get("mixed"))
        bad_here = False
        for _ in range(vectors):
            env = {s: rnd.getrandbits(1) for s in sigs}
            val = lambda p: CONSTV[p] if p in CONSTV else env[p]
            c, couts, sums = None, [], []
            for i, l in enumerate(luts):
                a, b, d = val(l["pins"][0]), val(l["pins"][1]), val(l["pins"][3])
                cin = val(l["pins"][2]) if i == 0 else c
                sums.append((l["init"] >> (a | b << 1 | cin << 2 | d << 3)) & 1)
                c = (l["init"] >> (a | b << 1 | cin << 2)) & 1
                couts.append(c)
            tot = ch["c0"]
            for i in range(W):
                for side in ("A", "B"):
                    f, p = ch[side][i]
                    tot += (((val(p) ^ f[1]) if f[0] == "s" else f[1]) << i)
            for i in range(W):
                if i == 0 and ch.get("free_head"):
                    pass
                elif not L.unread(luts[i]["name"]) and sums[i] != (tot >> i) & 1:
                    bad_here = True
                carry = (sum(((ch["A"][j][0][1] ^ 0) if ch["A"][j][0][0] == "c" else (val(ch["A"][j][1]) ^ ch["A"][j][0][1])) << j for j in range(i + 1))
                         + sum(((ch["B"][j][0][1]) if ch["B"][j][0][0] == "c" else (val(ch["B"][j][1]) ^ ch["B"][j][0][1])) << j for j in range(i + 1)) + ch["c0"]) >> (i + 1)
                if i < len(luts) - 1 and couts[i] != (carry & 1) ^ ch["po"][i]:
                    bad_here = True
            if bad_here:
                break
        ok += not bad_here
        bad += bad_here
    return ok, bad, mixed, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=os.path.join(REPO, "tmp", "rtl", "image_nl.pkl"))
    ap.add_argument("--hl")
    ap.add_argument("--vectors", type=int, default=64)
    ap.add_argument("--negative-control", action="store_true", help="flip ch['c0'] on every chain first; every chain must then fail")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    from lifters.cycloneiv_clean import rtl
    rnd = random.Random(1)
    srcs = [os.path.join(REPO, "tmp", "rtl", "hl_nl", n + ".pkl") for n in a.hl.split(",")] if a.hl else [a.cache]
    tot = [0, 0, 0]
    for s in srcs:
        nl = pickle.load(open(s, "rb"))
        nl = nl[0] if isinstance(nl, tuple) else nl
        L = rtl.Lift(nl)
        L.index()
        L.chains()
        if a.negative_control:
            for ch in L.chain_list:
                if ch["ok"]:
                    ch["c0"] ^= 1
        ok, bad, mixed, _ = check(L, a.vectors, rnd)
        tag = " [NEGATIVE CONTROL: c0 flipped, every chain MUST be bad]" if a.negative_control else ""
        log.info("%s chains ok %d bad %d (mixed-polarity %d)%s", os.path.basename(s), ok, bad, mixed, tag)
        for k, v in enumerate((ok, bad, mixed)):
            tot[k] += v
    log.info("TOTAL chains ok %d bad %d mixed %d", *tot)
    if a.negative_control and tot[0]:
        raise SystemExit(f"negative control FAILED: {tot[0]} chains still passed after c0 was flipped -- the check cannot detect wrongness")


if __name__ == "__main__":
    main()
