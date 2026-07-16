#!/usr/bin/env python3
"""Focused native-vs-oracle parity for the EFB bitstream on 3.15t.

native path : native_bitstream CRAM -> native_tile_decode -> canonical sets
oracle path : pytrellis(build_315) read_bit -> deserialise_chip ->
              ChipConfig.from_chip -> to_string -> canonical sets
Compares order-independently. Verifies decode correctness under 3.15t + GIL off.
"""
import os
import sys

PLURIBUS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(PLURIBUS, "scripts")
BUILD = os.environ.get("TRELLIS_BUILD", os.path.join(PLURIBUS, "tmp/prjtrellis/libtrellis/build"))
DB = os.environ.get("TRELLIS_DBROOT", os.path.join(PLURIBUS, "tmp/prjtrellis/database"))
BIT = os.path.join(PLURIBUS,
    "diamond-fuzz/targets/re_efb_00000_S_nc/impl1/fuzz_impl1.bit")

sys.path.insert(0, SCRIPTS)
sys.path.insert(0, BUILD)
import native_bitstream
import native_tile_decode as ntd
import pytrellis


def parse_config_string(s):
    tiles = {}
    cur = None
    for ln in s.splitlines():
        if ln.startswith(".tile "):
            cur = {"arcs": set(), "words": set(), "enums": set()}
            tiles[ln[len(".tile "):].strip()] = cur
        elif ln.startswith("arc: ") and cur is not None:
            _, sink, src = ln.split(); cur["arcs"].add((sink, src))
        elif ln.startswith("word: ") and cur is not None:
            _, n, v = ln.split(); cur["words"].add((n, v))
        elif ln.startswith("enum: ") and cur is not None:
            _, n, v = ln.split(); cur["enums"].add((n, v))
        elif ln.strip() == "" or ln.startswith("."):
            cur = None
    return {k: v for k, v in tiles.items()
            if v["arcs"] or v["words"] or v["enums"]}


def main():
    print(f"# python {sys.version.split()[0]} gil_enabled={sys._is_gil_enabled()}")
    tilegrid = ntd.load_tilegrid("LCMXO2-1200", DB)
    pb = native_bitstream.parse_file(BIT)
    native = ntd.canonical(ntd.decode_chip(pb.cram, tilegrid, DB, workers=8))

    pytrellis.load_database(DB)
    chip = pytrellis.Bitstream.read_bit(BIT).deserialise_chip()
    oracle = parse_config_string(pytrellis.ChipConfig.from_chip(chip).to_string())

    all_t = set(native) | set(oracle)
    matched = diverged = 0
    divs = []
    for name in sorted(all_t):
        nv = native.get(name, {"arcs": set(), "words": set(), "enums": set()})
        ov = oracle.get(name, {"arcs": set(), "words": set(), "enums": set()})
        na, nw, ne = set(nv["arcs"]), set(nv["words"]), set(nv["enums"])
        oa, ow, oe = set(ov["arcs"]), set(ov["words"]), set(ov["enums"])
        if na == oa and nw == ow and ne == oe:
            matched += 1
        else:
            diverged += 1
            divs.append((name, na ^ oa, nw ^ ow, ne ^ oe))
    print(f"# native tiles={len(native)} oracle tiles={len(oracle)} union={len(all_t)}")
    print(f"# matched={matched} diverged={diverged}")
    for name, a, w, e in divs[:10]:
        print(f"  DIVERGE {name}: arcs^={sorted(a)} words^={sorted(w)} enums^={sorted(e)}")
    print("PARITY", "PASS" if diverged == 0 else "FAIL")
    return 0 if diverged == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
