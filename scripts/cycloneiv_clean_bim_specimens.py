#!/usr/bin/env python3.15t
"""BLOCK_INPUT_MUX label specimens for the clean tracer (#165).  Exact labels: each build names, in the Quartus routing.rcf, the BIM an output pad
data pin is routed through (`dest = (pad~output, I)` after `BLOCK_INPUT_MUX:X<x>Y<y>S0I<i>`) and, in postfit.vo, the pad site (IOOBUF_X<x>_Y<y>_N<n>).

Sampling plan (recovery-process.md): VIO rows y = 0 and y = 91; per row the lowest-x tile, the highest-x tile and one seeded interior tile; every
Column I/O pad (SUB_LOC 0..3) of those tiles drives one output pin from its own LUT (distinct 4-input masks, dont_touch).  One build per tile
group (6 builds); pad -> ball from pkgpad (vendor pkg + pad ddb).  Black box: quartus_map / fit / asm / eda / cdb / cpf.

  python3.15t scripts/cycloneiv_clean_bim_specimens.py build [--jobs 3]
  python3.15t scripts/cycloneiv_clean_bim_specimens.py table      # -> tmp/cycloneiv_clean/bim_specimens/labels.json
Log: tmp/logs/cycloneiv_clean_bim_specimens.log
"""
import argparse
import collections
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_lut_specimens as LS  # noqa: E402

OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "bim_specimens")
SEED = 165
# first-run backstops from the reg-pair builds (small designs: map 5 s, fit 7 s, asm 2 s, eda 1 s); cdb unmeasured: 60 s
LS.LIMITS = {"quartus_map": 60, "quartus_fit": 120, "quartus_asm": 30, "quartus_eda": 30, "quartus_cdb": 60, "quartus_cpf": 10}
log = logging.getLogger("bim_specimens")


def groups():
    """[(name, [(ball, x, y, sub_loc)])]: 6 tile groups."""
    from lifters.cycloneiv_clean import io_decode as ID, pkgpad as K
    ch = ID.Chain()
    pads = K.pads()
    site_pad = K.io_site_pads(pads)
    ball = {s: b for b, s in ch.ball_site.items() if s}
    tiles = collections.defaultdict(list)
    for (bt, s), j in site_pad.items():
        if bt == 6 and (bt, s) in ball:
            x, y, k = K.pad_site(pads[j])
            tiles[(x, y)].append((ball[(bt, s)], x, y, k))
    rng = np.random.default_rng(SEED)
    out = []
    for y in (0, 91):
        xs = sorted(x for (x, yy) in tiles if yy == y)
        mid = xs[len(xs) // 4: 3 * len(xs) // 4]
        for tag, x in (("lo", xs[1]), ("hi", xs[-1]), ("mid", int(rng.choice(mid)))):
            out.append((f"y{y}_{tag}_x{x}", sorted(tiles[(x, y)])))
    return out


def verilog(n):
    rng = np.random.default_rng(SEED)
    L = [f"module top(input a, b, c, d, output [{n - 1}:0] o);"]
    for i in range(n):
        m = int(rng.integers(1, 0xFFFF))
        L.append(f"  cycloneive_lcell_comb #(.lut_mask(16'h{m:04X}), .sum_lutc_input(\"datac\"), .dont_touch(\"on\")) u{i} "
                 f"(.dataa(a), .datab(b), .datac(c), .datad(d), .combout(o[{i}]));")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def build_group(g):
    name, pads = g
    qsf = [f"set_location_assignment PIN_{b} -to o[{i}]" for i, (b, *_r) in enumerate(pads)]
    return LS.build_project(os.path.join(OUT, name), name, verilog(len(pads)), qsf, vo=True, rcf=True)


def cmd_build(a):
    gs = groups()
    json.dump(gs, open(os.path.join(OUT, "groups.json"), "w"))
    import heavy_guard
    with heavy_guard.lease(a.jobs * heavy_guard.JOB_GB["quartus_chain_cyc4"], "cyc4_bim_specimens", log), ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(build_group, gs))
    for n, s in res:
        log.info("%s: %s", n, f"FAILED at {s}" if s else "ok")
    if any(s for _, s in res):
        raise SystemExit("failed builds")


def cmd_table(a):
    """labels: (BIM tile dx from the pad tile, BIM index, pad SUB_LOC) -> builds.  Pad site from the vo (IOOBUF N), sub-loc from pkgpad."""
    from lifters.cycloneiv_clean import tracer as T
    gs = json.load(open(os.path.join(OUT, "groups.json")))
    rows, bad = [], []
    for name, pads in gs:
        d = os.path.join(OUT, name)
        vo = open(os.path.join(d, "postfit.vo")).read()
        loc = {}
        for m in re.finditer(r"// Location: IOOBUF_X(\d+)_Y(\d+)_N(\d+)\n\w+ (\S+?)\s*\(", vo):
            loc[m[4].lstrip("\\")] = (int(m[1]), int(m[2]), int(m[3]))
        want = {f"o[{i}]~output": (x, y, k) for i, (b, x, y, k) in enumerate(pads)}
        for net in T.parse_rcf(os.path.join(d, "routing.rcf")):
            for last, cell, port, rp in net["dests"]:
                if cell in want and last:
                    x, y, k = want[cell]
                    rows.append(dict(build=name, pad=(x, y, k), vo_site=loc.get(cell), port=port, last=last))
    json.dump(rows, open(os.path.join(OUT, "labels.json"), "w"))
    tab = collections.defaultdict(set)
    for r in rows:
        x, y, k = r["pad"]
        l = r["last"]
        tab[(k, l[0], l[1] - x, l[2] - y, l[3], l[4], r["port"])].add(r["build"])
    for k, v in sorted(tab.items()):
        log.info("sub_loc %s -> %s dx %s dy %s z %s I %s port %s   builds %s", k[0], k[1], k[2], k[3], k[4], k[5], k[6], sorted(v))
    per = collections.defaultdict(set)
    for k in tab:
        per[k[0]].add(k[1:])
    for k, v in sorted(per.items()):
        if len(v) > 1:
            log.error("CONTRADICTION: sub_loc %s has %d labels", k, len(v))
    log.info("label rows %d (pads %d)", len(rows), sum(len(p) for _, p in gs))


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_bim_specimens.log"), mode="a")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build")
    b.add_argument("--jobs", type=int, default=3)
    b.set_defaults(f=cmd_build)
    sp.add_parser("table").set_defaults(f=cmd_table)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
