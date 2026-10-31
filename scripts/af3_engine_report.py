#!/usr/bin/env python3.15t
"""AF3 engine report (#165): FF groups, 1-Wire timing, instruction trace, pass / fail run, with a DUMMY secret.

  python3.15t scripts/cycloneiv_clean_af3_engine.py extract && python3.15t scripts/cycloneiv_clean_af3_engine.py build -G OVR=1 --obj obj_ovr
  python3.15t scripts/af3_engine_report.py [--nl NL.pkl]      log tmp/logs/af3_engine_report.log, groups tmp/af3/groups.json
Sections: groups (FF names per role) / bus (timing in board-clock cycles, transcript) / program (executed opcodes by address) / result (pass vs fail run).
"""
import argparse
import collections
import json
import logging
import os
import pickle
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
OUT = os.path.join(REPO, "tmp", "af3")
LOG = os.path.join(REPO, "tmp", "logs", "af3_engine_report.log")
log = logging.getLogger("af3_report")
ENG_CLK = "u_clkbuf_out_57_91_29_0"
OPNAME = {0: "NOP", 1: "LD", 2: "ST", 3: "ALU3", 4: "ALU4", 5: "CMP", 6: "END", 7: "ALU7", 8: "SKIP", 9: "ALU9", 10: "STA", 11: "SELB", 12: "WAIT", 13: "TXB", 14: "RXB", 15: "LOOP"}


def groups(nl):
    ff = {f["name"]: f for f in nl.ffs}
    lut = {l["name"]: l for l in nl.luts}
    eng = sorted(f["name"] for f in nl.ffs if f["clk"] == ENG_CLK)
    g = collections.defaultdict(list)
    for n in eng:
        f = ff[n]
        key = (f.get("ena"), f.get("sclr"), f.get("aclr"))
        g[key].append(n)
    ir = [n for n in g[("lc_9_84_11", None, None)]]
    out = {
        "IR (16, fetched word bits 15..0, ena = phase strobe)": ir,
        "decode (10, one-hot ops 9 F 7 3 2 B A 1 4 8, sclr ff_9_84_12)": g[(None, "ff_9_84_12", None)],
        "phase ring (3 FFs, micro-step = 3 clocks)": ["ff_9_84_8", "ff_9_84_9", "ff_9_84_12"],
        "R32 (32, bitwise/shift accumulator, ena lc_6_89_10)": g[("lc_6_89_10", None, None)],
        "W32 (32, RAM word register, ena lc_6_89_2)": g[("lc_6_89_2", None, None)],
        "timer19 (19, sync clear lc_11_88_9, carry chain)": g[(None, "lc_11_88_9", None)],
        "PC8 (8, ena lc_9_84_5)": g[("lc_9_84_5", None, None)],
        "loop counter (7, ena ff_9_85_8)": g[("ff_9_85_8", None, None)],
        "byte tx register (8, ena ff_9_88_7)": g[("ff_9_88_7", None, None)],
        "byte rx / CRC8-shaped register (8, ena lc_10_88_1)": g[("lc_10_88_1", None, None)],
        "LFSR-shaped group (10, aclr lc_6_90_7)": g[(None, None, "lc_6_90_7")],
        "flag chain (4, ena lc_9_90_1)": g[("lc_9_90_1", None, None)],
    }
    return out, eng


def run(exe_args, trace):
    exe = os.path.join(OUT, "obj_ovr", "Vengine")
    r = subprocess.run([exe, *exe_args, "--trace", trace], capture_output=True, text=True)
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", default=os.path.join(REPO, "tmp", "dji_microcode", "build", "nl.pkl"))
    ap.add_argument("--cycles", type=int, default=1700000)
    ap.add_argument("--mhz", type=float, default=40.0)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, "w"), logging.StreamHandler()])
    nl = pickle.load(open(a.nl, "rb"))
    grp, eng = groups(nl)
    json.dump(grp, open(os.path.join(OUT, "groups.json"), "w"), indent=1)
    for k, v in grp.items():
        log.info("[V] group %s: %d FFs: %s", k, len(v), " ".join(v))
    ungrouped = set(eng) - {n for v in grp.values() for n in v}
    log.info("[V] %d of %d engine FFs are in no named group above", len(ungrouped), len(eng))
    # runs: pass (matching dummy slave, MAC order 3) and fail (one MAC bit flipped); same dummy secret on both sides
    sec = "a0a1a2a3a4a5a6a7"
    res = {}
    for name, extra in (("pass", ["--macord", "3"]), ("fail", ["--macord", "3", "--badmac"])):
        tr = os.path.join(OUT, f"rep_{name}.trace")
        out = run(["--cycles", str(a.cycles), "--slave", "ds", "--secret", sec, "--mhz", str(a.mhz), *extra], tr)
        res[name] = (tr, out)
    # bus transcript (from the slave log)
    slave = [ln for ln in res["pass"][1].splitlines() if ln.startswith("SLAVE")]
    log.info("[V] bus transcript, board clock assumed %.1f MHz for the slave timing windows (cycle, event):", a.mhz)
    for ln in slave:
        log.info("   %s", ln)
    # AF3 timing from the pass trace: master-low durations
    ev = []
    for ln in open(res["pass"][0]):
        m = re.match(r"(\d+) AF3 (\d) oe=(\d) drv=(\d)", ln)
        if m:
            ev.append((int(m[1]), int(m[2]), int(m[3]), int(m[4])))
    lows = []
    last_fall = None
    for c, lv, oe, drv in ev:
        master_low = (oe == 1 and drv == 0)
        if master_low and last_fall is None:
            last_fall = c
        if not master_low and last_fall is not None:
            lows.append((last_fall, c - last_fall)); last_fall = None
    hist = collections.Counter()
    for c, d in lows:
        hist[d] += 1
    log.info("[V] master-low durations (cycles: count), %d pulses: %s", len(lows), dict(sorted(hist.items())))
    starts = [c for c, d in lows]
    gaps = collections.Counter(b - a_ for a_, b in zip(starts, starts[1:]) if b - a_ < 5000)
    log.info("[V] slot period (start to start, cycles: count): %s", dict(sorted(gaps.items())))
    # program trace
    nlm = {t["x"] * 1000 + t["y"]: t for t in nl.m9k}
    t85 = nlm[7 * 1000 + 85]["init"]
    words = [t85[a_] & 0xFFFF for a_ in range(512)]
    pcs = []
    last = None
    for ln in open(res["pass"][0]):
        m = re.match(r"(\d+) RAM a=([0-9a-f]+) we=(\d)", ln)
        if m and int(m[2], 16) >= 0x120:
            ad = int(m[2], 16)
            if ad != last:
                pcs.append((int(m[1]), ad)); last = ad
    cnt = collections.Counter(ad for c, ad in pcs)
    first = {}
    for c, ad in pcs:
        first.setdefault(ad, c)
    log.info("[V] program 0x120..0x1a6 executed once in the pass run; per address: first cycle, executions, opcode class, fields (op[15:12] a[8:4] n[3:0] imm[11:4])")
    for ad in sorted(cnt):
        w = words[ad]
        log.info("   %03x  c=%8d  n=%3d  %-4s  op=%x a=%02x n=%x imm=%02x", ad, first[ad], cnt[ad], OPNAME[w >> 12], w >> 12, (w >> 4) & 0x1F, w & 0xF, (w >> 4) & 0xFF)
    # result
    fin = {}
    for name in ("pass", "fail"):
        m = re.search(r"FINAL-FF ((?:[0-9a-f]{8} ?)+)", res[name][1])
        fin[name] = int("".join(m[1].split()), 16)
    bm = json.load(open(os.path.join(OUT, "engine.json")))["ffvec_bit"]
    diff = [n for n, b in bm.items() if ((fin["pass"] ^ fin["fail"]) >> b) & 1]
    ext_same = open(res["pass"][0]).read() == open(res["fail"][0]).read()
    # events after the last MAC byte was read (the compare and everything after it): AF3 edges and RAM address / write-enable sequence
    last_rx = max(int(l.split()[1]) for l in slave if "TX done" in l)

    def tail(p):
        o = []
        for ln in open(p):
            m = re.match(r"(\d+) (AF3|RAM) (.*?)( rd=.*)?$", ln)
            if m and int(m[1]) > last_rx:
                o.append((m[1], m[2], m[3].strip()))
        return o
    tp, tf_ = tail(res["pass"][0]), tail(res["fail"][0])
    log.info("[V] pass run vs fail run (one MAC bit differs, same dummy secret): FFs with different final value %s; after the MAC read (cycle > %d) AF3 edges + RAM address / write-enable sequence identical: %s (%d events)", diff, last_rx, tp == tf_, len(tp))


if __name__ == "__main__":
    main()
