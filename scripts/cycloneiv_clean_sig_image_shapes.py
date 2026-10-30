#!/usr/bin/env python3.15t
"""Resource shape per clock domain of a decoded image (emit Netlist pickle, local): FF / M9K / MAC / carry-LUT counts, #165.

  python3.15t scripts/cycloneiv_clean_sig_image_shapes.py tmp/dji_patterns/image_nl.pkl
Counts only (domains are anonymous ranks by FF count).  Input pickle is our own local decode output.
"""
import collections
import pickle
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main():
    nl = pickle.load(open(sys.argv[1], "rb"))
    ff = collections.Counter(F["clk"] for F in nl.ffs if F.get("clk"))
    m9 = collections.Counter(m.get("clk") for m in nl.m9k)
    mc = collections.Counter(m.get("clk") for m in nl.mac)
    # carry LUTs per clock domain: clock of the FF that reads the carry LUT output
    lut_clk = {}
    for F in nl.ffs:
        if F.get("d") and F.get("clk"):
            lut_clk.setdefault(F["d"], F["clk"])
    carry = collections.Counter(lut_clk.get(L["name"]) for L in nl.luts if L["mode"] == "cin")
    doms = [c for c, _ in ff.most_common()]
    print("domain rank | FF | M9K | MAC | carry LUT (registered)")
    for i, c in enumerate(doms):
        print(f"{i + 1} | {ff[c]} | {m9.get(c, 0)} | {mc.get(c, 0)} | {carry.get(c, 0)}")
    print("M9K/MAC with no/unknown clock:", sum(v for k, v in m9.items() if k not in ff), sum(v for k, v in mc.items() if k not in ff))
    print("totals: FF", sum(ff.values()), "M9K", len(nl.m9k), "MAC", len(nl.mac), "carry LUT", sum(1 for L in nl.luts if L["mode"] == "cin"))


if __name__ == "__main__":
    main()
