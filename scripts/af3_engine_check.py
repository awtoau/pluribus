#!/usr/bin/env python3.15t
"""AF3 engine vs reference SHA-1 and a virtual 1-Wire slave with a DUMMY secret (#165).  Prints booleans and counts only, never memory words.

  python3.15t scripts/cycloneiv_clean_af3_engine.py extract && python3.15t scripts/cycloneiv_clean_af3_engine.py build -G OVR=1 --obj obj_ovr
  python3.15t scripts/af3_engine_check.py [--nl NL.pkl] [--secret HEX16]     log tmp/logs/af3_engine_check.log
Checks (V = numerically compared here):
  1. block   engine message block W0..W15 (RAM 0x110..0x11f: initial words + engine writes, W0 / W12 = the dummy secret) assembled from the run trace
  2. sha1    engine state words a..e after the 80-round loop (RAM 0x100..0x104) == reference SHA-1 compression of that block (raw a..e, no final addition; and with it)
  3. slave   which slave MAC byte order makes the 5 words the engine stored (0x10b..0x10f, as received) equal its own state words (0x104..0x100)
The dummy secret replaces the engine's own W0 / W12 writes (ovr_w0 / ovr_w12); the engine-written values are never printed.
"""
import argparse
import json
import logging
import os
import pickle
import re
import struct
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
OUT = os.path.join(REPO, "tmp", "af3")
LOG = os.path.join(REPO, "tmp", "logs", "af3_engine_check.log")
log = logging.getLogger("af3_check")
WORD_WIRE = {**{j: (0, j) for j in range(16)}, **{16 + j: (1, j) for j in range(11)}, 27: (0, 16), **{28 + j: (1, 11 + j) for j in range(3)}, 31: (0, 17)}
IV = (0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0)


def rol(x, n):
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def sha1_compress(words16, add_iv):
    w = list(words16)
    for i in range(16, 80):
        w.append(rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1))
    a, b, c, d, e = IV
    for i in range(80):
        if i < 20:
            f, k = (b & c) | (~b & d), 0x5A827999
        elif i < 40:
            f, k = b ^ c ^ d, 0x6ED9EBA1
        elif i < 60:
            f, k = (b & c) | (b & d) | (c & d), 0x8F1BBCDC
        else:
            f, k = b ^ c ^ d, 0xCA62C1D6
        t = (rol(a, 5) + (f & 0xFFFFFFFF) + e + k + w[i]) & 0xFFFFFFFF
        e, d, c, b, a = d, c, rol(b, 30), a, t
    r = [a, b, c, d, e]
    return [(x + y) & 0xFFFFFFFF for x, y in zip(r, IV)] if add_iv else r


def init_words(nl):
    m = {f"{t['x']}_{t['y']}": t for t in nl.m9k}
    ta, tb = m["7_85"]["init"], m["7_86"]["init"]
    tiles = (ta, tb)
    out = []
    for a in range(512):
        w = 0
        for j, (t, p) in WORD_WIRE.items():
            w |= ((tiles[t][a] >> p) & 1) << j
        out.append(w)
    return out


def run(macord, secret_hex, cycles, extra=()):
    exe = os.path.join(OUT, "obj_ovr", "Vengine")
    tr = os.path.join(OUT, f"chk_{macord}.trace")
    r = subprocess.run([exe, "--cycles", str(cycles), "--slave", "ds", "--macord", str(macord), "--secret", secret_hex, "--trace", tr, *extra], capture_output=True, text=True)
    return tr, r.stdout


def parse(tr):
    ev = []
    for ln in open(tr):
        m = re.match(r"(\d+) RAM a=([0-9a-f]+) we=1 rd=(\S+) wd=(\S+)", ln)
        if m and m[4] != "<secret>":
            ev.append((int(m[1]), int(m[2], 16), int(m[4], 16)))
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", default=os.path.join(REPO, "tmp", "dji_microcode", "build", "nl.pkl"))
    ap.add_argument("--secret", default="a0a1a2a3a4a5a6a7", help="DUMMY secret, 16 hex digits")
    ap.add_argument("--cycles", type=int, default=1700000)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.FileHandler(LOG, "w"), logging.StreamHandler()])
    nl = pickle.load(open(a.nl, "rb"))
    mem0 = init_words(nl)
    import af3_engine_report as R
    grp, _ = R.groups(nl)
    for k in ("R32", "W32"):
        names = [n for kk, v in grp.items() if kk.startswith(k) for n in v]
        log.info("[V] datapath register %s members (%d FFs): %s", k, len(names), " ".join(names))
    sec = bytes.fromhex(a.secret)
    w0, w12 = struct.unpack(">I", sec[:4])[0], struct.unpack(">I", sec[4:])[0]
    res = {}
    for mo in range(8):
        tr, out = run(mo, a.secret, a.cycles)
        ev = parse(tr)
        mem = {i: mem0[i] for i in range(0x100, 0x120)}
        # engine writes up to the start of the round loop (first write to 0x104 with the loop running = first write after the last block write)
        start = next(c for c, ad, v in ev if ad == 0x104 and c > 1550000)
        for c, ad, v in ev:
            if c >= start:
                break
            mem[ad] = v
        mem[0x110], mem[0x11c] = w0, w12
        blk = [mem[0x110 + i] for i in range(16)]
        final = {}
        for c, ad, v in ev:
            if 0x100 <= ad <= 0x104 and c >= start:
                final[ad] = v
        rcv = {ad: v for c, ad, v in ev if 0x10b <= ad <= 0x10f and c > 1100000}
        eng_state = [final.get(0x100 + i) for i in range(5)]
        raw = sha1_compress(blk, 0)
        withiv = sha1_compress(blk, 1)
        res[mo] = dict(sha_raw=(eng_state == raw), sha_iv=(eng_state == withiv),
                       mac_words_eq_state=all(rcv.get(0x10b + i) == eng_state[i] for i in range(5)),
                       mac_words_eq_state_rev=all(rcv.get(0x10f - i) == eng_state[i] for i in range(5)))
        log.info("[V] macord %d: engine a..e == reference SHA-1 of its block (raw %s, with IV add %s); received MAC words == state (0x10b+i<->0x100+i) %s, reversed (0x10f-i) %s",
                 mo, res[mo]["sha_raw"], res[mo]["sha_iv"], res[mo]["mac_words_eq_state"], res[mo]["mac_words_eq_state_rev"])
    json.dump(res, open(os.path.join(OUT, "check.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
