#!/usr/bin/env python3
"""Structure-only comparison of the third-party EP4CGX150 image against prior-art candidates (#165).

  python3 scripts/cycloneiv_prior_art_compare.py [--dump tmp/m9k_dump] [--out tmp/prior_art/compare.json]

Reads the local per-block M9K word dumps (cycloneiv_clean_m9k_dump.py); prints counts only, never table values.
Tests (each returns numbers, the verdict is the caller's):
  geometry  per populated table: width, populated extent, distinct words, vs depth/width of candidate soft-CPU program stores
            and of Altera IP ROMs measured in reference/signatures.tsv
  fieldspread  18-bit word: distinct values / zero share of the 4-bit field [11:8] (a register-select field in a KCPSM3/Mico8-class
            ISA is spread over many values in real programs) and of the 6-bit field [17:12]
  prbs      the PRBS seeds against the published initialisation vectors; offset of each PRBS11 seed from the all-ones seed
Log: tmp/logs/cycloneiv_prior_art_compare.log.
"""
import argparse
import collections
import json
import logging
import math
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_prior_art_compare.log")
log = logging.getLogger("prior_art")

# block file stem -> (annotation name, width used for the table)
TABLES = {"m9k_i056_x7_y57": ("7_57", 18), "m9k_i057_x7_y58": ("7_58", 18), "m9k_i084_x7_y85": ("7_85", 18),
          "m9k_i085_x7_y86": ("7_86", 18), "m9k_i243_x36_y64": ("36_64", 18), "m9k_i261_x36_y82": ("36_82", 18),
          "m9k_i596_x94_y57": ("94_57", 9), "m9k_i597_x94_y58": ("94_58", 9)}

# candidate program stores: (name, instruction width, max words, source)
SOFT_CPUS = [
    ("PicoBlaze KCPSM3", 18, 1024, "Xilinx UG129"),
    ("PicoBlaze KCPSM6", 18, 4096, "Xilinx UG129 / KCPSM6 manual"),
    ("Lattice Mico8", 18, 1024, "Lattice Mico8 docs"),
    ("PIC12/PIC16C5x class", 12, 2048, "Microchip baseline-core datasheets"),
    ("J1 (Bowman)", 16, 8192, "excamera.com/sphinx/fpga-j1.html"),
    ("ZPU", 8, 1 << 20, "zylin ZPU"),
    ("Nios II/e", 32, 1 << 30, "Altera Nios II handbook"),
]
# Altera IP ROM geometry (words x bits) measured in reference/signatures.tsv, 2026-10-30
ALTERA_ROMS = [("FFT-II twiddle", 17, None), ("FFT-II twiddle", 5, None), ("FFT-II twiddle", 65, None), ("FFT-II streaming twiddle", 16, 16),
               ("NCO small ROM", 512, 11), ("NCO large ROM 12b", 4096, 12), ("NCO large ROM 16b", 65536, 18), ("BCH dec inverse table", 256, 8)]

# published initialisation vectors (stage 1 = feedback input, same convention as seed trace comment)
PRBS15_STD = "100101010000000"  # DVB-T energy dispersal and IEEE 802.16 OFDM randomiser
OBSERVED = {"PRBS15 (x3)": ("15", "100101010000000"), "PRBS11 a (x2)": ("11", "10110101110"), "PRBS11 b (x2)": ("11", "00000101111")}


def read_hex(path):
    with open(path) as f:
        return [int(t, 16) for t in f.read().split()]


def geometry(dump):
    rows = []
    for stem, (name, w) in TABLES.items():
        p = os.path.join(dump, "%s.x%d.hex" % (stem, w))
        if not os.path.exists(p):
            log.warning("missing %s", p)
            continue
        d = read_hex(p)
        nz = [i for i, x in enumerate(d) if x]
        ext = (nz[-1] + 1) if nz else 0
        rows.append(dict(table=name, width=w, words=len(d), populated=len(nz), extent=ext, distinct=len(set(d))))
    return rows


def cpu_fit(rows):
    out = []
    for r in rows:
        fits = [c[0] for c in SOFT_CPUS if c[1] == r["width"] and r["extent"] <= c[2]]
        alt = [a[0] for a in ALTERA_ROMS if a[1] == r["extent"] and (a[2] is None or a[2] == r["width"])]
        out.append(dict(table=r["table"], width=r["width"], extent=r["extent"], width_depth_fits=fits, altera_rom_depth_match=alt))
    return out


def fieldspread(dump):
    out = {}
    for stem in ("m9k_i084_x7_y85", "m9k_i057_x7_y58", "m9k_i056_x7_y57"):
        p = os.path.join(dump, stem + ".x18.hex")
        if not os.path.exists(p):
            continue
        nz = [x for x in read_hex(p) if x]
        if not nz:
            continue
        f8 = collections.Counter((x >> 8) & 15 for x in nz)
        f12 = collections.Counter(x >> 12 for x in nz)
        out[TABLES[stem][0]] = dict(n=len(nz), reg_field_distinct=len(f8), reg_field_zero_share=round(f8[0] / len(nz), 3),
                                    opcode_field_distinct=len(f12), opcode_field_top=round(max(f12.values()) / len(nz), 3))
    return out


def prbs11_offsets():
    """stage-1 = feedback input, feedback = s9 xor s11, shift toward stage 11; offset in steps from the all-ones state."""
    def nxt(s):  # s tuple (s1..s11)
        fb = s[8] ^ s[10]
        return (fb,) + s[:10]
    ones = (1,) * 11
    target = {k: tuple(int(c) for c in v[1]) for k, v in OBSERVED.items() if v[0] == "11"}
    seen, s, k = {}, ones, 0
    while True:
        seen[s] = k
        s = nxt(s)
        k += 1
        if s == ones:
            break
    return dict(period=k, offsets={name: seen.get(t) for name, t in target.items()},
                gap_between=(seen[target["PRBS11 b (x2)"]] - seen[target["PRBS11 a (x2)"]]) % k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=os.path.join(REPO, "tmp", "m9k_dump"))
    ap.add_argument("--out", default=os.path.join(REPO, "tmp", "prior_art", "compare.json"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
    rows = geometry(a.dump)
    res = dict(geometry=rows, fit=cpu_fit(rows), fieldspread=fieldspread(a.dump),
               prbs15=dict(observed=OBSERVED["PRBS15 (x3)"][1], published=PRBS15_STD, equal=OBSERVED["PRBS15 (x3)"][1] == PRBS15_STD),
               prbs11=prbs11_offsets())
    for k, v in res.items():
        log.info("%s: %s", k, json.dumps(v))
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    log.info("wrote %s", a.out)


if __name__ == "__main__":
    main()
