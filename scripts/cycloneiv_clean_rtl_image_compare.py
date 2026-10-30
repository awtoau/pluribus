#!/usr/bin/env python3.15t
"""RTL vs flat emit on the third-party EP4CGX150 image, same stimulus, with per-FF probes through the lift's FF name map (#165).

  python3.15t scripts/cycloneiv_clean_rtl_image_compare.py lift  [--out tmp/image_sim_rtl]   lift nl.pkl -> rtl.v + ffmap.json (flat FF name -> RTL register bit)
  python3.15t scripts/cycloneiv_clean_rtl_image_compare.py run   [--out ...] [--cycles 20000] [--spi]   build + run flat and RTL (verilator), compare
Compare = output pads per clock row (differing rows per pad), and with --spi the FF snapshot after each SPI transfer (first differing step, FF names).
Uses the helpers of scripts/cycloneiv_clean_image_sim.py (testbench generator, line splitting, stall-guarded runner).  Counts only in the log
tmp/logs/rtl_image_compare.log; outputs under --out (never committed).
"""
import argparse
import json
import logging
import os
import pickle
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("rtl_image_compare")
LOG = os.path.join(REPO, "tmp", "logs", "rtl_image_compare.log")
BUILD_LIMIT_S = 900       # verilator build of the 99 MB flat netlist measured 167..266 s under load (image sim doc): 3x worst case
RUN_LIMIT_S = 300         # 20,000 clocks with probes measured 2.4..3.0 s plus SPI program: generous backstop


def lift(a):
    from lifters.cycloneiv_clean import rtl
    nl = pickle.load(open(os.path.join(a.out, "nl.pkl"), "rb"))
    fm = {}
    text, rep = rtl.lift(nl, ffmap=fm)
    open(os.path.join(a.out, "rtl.v"), "w").write(text)
    json.dump(fm, open(os.path.join(a.out, "ffmap.json"), "w"))
    log.info("lifted: %d FFs mapped, flat_lut_left %d, lines %d", len(fm), rep["flat_lut_left"], rep["rtl_lines"])


def build_run(S, nl, src, tag, a, ffmap):
    pre = "pad_" if src == "flat" else "io_"
    tb, _half, _rsts, dom = S.gen_tb(nl, "same", a.cycles, [], tag, pre, True)
    if ffmap:
        tb = re.sub(r"dut\.(ff_\d+_\d+_\d+)\b", lambda m: "dut." + ffmap.get(m.group(1), m.group(1)), tb)
    tbp = os.path.join(S.W, f"tb_{tag}.v")
    open(tbp, "w").write(tb)
    srcv = os.path.join(S.W, src + "_s.v")
    md = os.path.join(S.W, f"obj_{tag}")
    if a.reuse and os.path.exists(os.path.join(md, "Vtb")):
        rc, s, rss = 0, 0.0, 0.0
    else:
      rc, s, rss, _l, _o = S.sh(["verilator", "--binary", "--timing", "--threads", str(S.THREADS), "-j", str(S.THREADS), "-O1", "--x-assign", "0", "--x-initial", "0",
                               "--converge-limit", "100000", "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-UNOPTFLAT", "-Wno-WIDTH", "-Wno-MULTIDRIVEN", "-Wno-TIMESCALEMOD",
                               "--top-module", "tb", "--Mdir", md, tbp, srcv], "build_" + tag, BUILD_LIMIT_S)
    log.info("BUILD %s rc=%s %.0fs %.0f MB", tag, rc, s, rss)
    if rc:
        raise SystemExit("build failed " + tag)
    args = [os.path.join(md, "Vtb")] + ([f"+spi", f"+cs_active={a.cs_active}"] if a.spi else []) + [f"+cyc={a.cycles}"]
    rc, s, rss, _l, out = S.sh(args, "run_" + tag, RUN_LIMIT_S)
    log.info("RUN %s rc=%s %.1fs", tag, rc, s)
    return dom


def read_rows(path):
    rows = {}
    for line in open(path):
        k, v = line.split()
        rows[int(k)] = int(v, 16)
    return rows


def run(a):
    import cycloneiv_clean_image_sim as S
    S.W = a.out
    nl = pickle.load(open(os.path.join(a.out, "nl.pkl"), "rb"))
    ffmap = json.load(open(os.path.join(a.out, "ffmap.json")))
    brk, _multi = S.self_loops(nl)
    for k in ("flat", "rtl"):
        S.split_long(os.path.join(a.out, k + ".v"), os.path.join(a.out, k + "_s.v"), brk if k == "flat" else (), k == "flat")
    build_run(S, nl, "flat", "cmp_flat", a, None)
    build_run(S, nl, "rtl", "cmp_rtl", a, ffmap)
    outs = sorted(io["ball"] for io in nl.ios if io["dir"] != "input")
    fa, ra = read_rows(os.path.join(a.out, "trace_cmp_flat_out.txt")), read_rows(os.path.join(a.out, "trace_cmp_rtl_out.txt"))
    per = {}
    rows_diff = 0
    for k in fa:
        if k in ra and fa[k] != ra[k]:
            rows_diff += 1
            x = fa[k] ^ ra[k]
            for i, b in enumerate(reversed(outs)):          # concatenation is MSB first: sorted list, last = bit 0
                if (x >> i) & 1:
                    per[b] = per.get(b, 0) + 1
    res = dict(rows=len(fa), rows_differing=rows_diff, pads_differing=per)
    if a.spi:
        names = json.load(open(os.path.join(a.out, "ffall_cmp_flat.json")))

        def snaps(tag):
            d = {}
            for line in open(os.path.join(a.out, f"snap_{tag}.txt")):
                l, v = line.split()
                d[int(l)] = "".join(v[i:i + 4096][::-1] for i in range(0, len(v), 4096))
            return d
        sf, sr = snaps("cmp_flat"), snaps("cmp_rtl")
        first = None
        for k in sorted(sf):
            diff = [names[i] for i in range(len(names)) if sf[k][i] != sr[k][i]]
            if diff and first is None:
                first = dict(step=k, ffs=len(diff), names=diff[:40], mapped=[ffmap.get(n) for n in diff[:40]])
            res.setdefault("snap_diff_ffs_per_step", {})[k] = len(diff)
        res["first_diff"] = first
    log.info("COMPARE %s", json.dumps(res))
    json.dump(res, open(os.path.join(a.out, "compare.json"), "w"), indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["lift", "run"])
    ap.add_argument("--out", default=os.path.join(REPO, "tmp", "image_sim_rtl"))
    ap.add_argument("--cycles", type=int, default=20000)
    ap.add_argument("--spi", action="store_true")
    ap.add_argument("--cs-active", type=int, default=0, help="frame polarity of the SPI program (0 = active low: the image loads on a low frame)")
    ap.add_argument("--reuse", action="store_true", help="reuse built simulators (stimulus plusargs only)")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    {"lift": lift, "run": run}[a.cmd](a)


if __name__ == "__main__":
    main()
