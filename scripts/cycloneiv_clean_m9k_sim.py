#!/usr/bin/env python3.15t
"""M9K functional equivalence (#165): emitted `m9k_<x>_<y>_q` vs the post-fit ram_block port-A data-out bus, every cycle after warm-up.

  python3.15t scripts/cycloneiv_clean_m9k_sim.py [--match 'gxm9k_*']      (reuses the tb.v / emit.v that cycloneiv_clean_emit_sim.py wrote)
Designs with exactly one cycloneiv_ram_block only; the compare covers the emitted width (low bits of the 18 / 36 bit bus).  Log tmp/logs/cycloneiv_clean_m9k_sim.log.
"""
import argparse
import fnmatch
import logging
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_emit_sim as S  # noqa: E402

log = logging.getLogger("cycloneiv_clean_m9k_sim")
RUN_LIMIT_S = 120      # emit_sim: iverilog compile + 300 cycles measured 1-2 s; 3x cold worst case as backstop


def one(name):
    d = os.path.join(REPO, "corpus", "cycloneiv", name)
    wd = os.path.join(S.WORK, name)
    vo = open(os.path.join(d, "postfit.vo")).read()
    blocks = re.findall(r"// Location: M9K_X(\d+)_Y(\d+)_N\d+\ncycloneiv_ram_block (\S+?)\s*\(", vo)
    if len(blocks) != 1:
        return "not_modelled", f"{len(blocks)} blocks"
    x, y, inst = blocks[0]
    em = open(os.path.join(wd, "emit.v")).read()
    m = re.search(r"// M9K m9k_%s_%s: single port, (\d+) bit" % (x, y), em)
    if not m:
        return "not_modelled", "emit does not model the tile"
    W = int(m[1])
    bus = inst.lstrip("\\") + "_PORTADATAOUT_bus"
    tb = open(os.path.join(wd, "tb.v")).read()
    ref = f"gt.\\{bus} " if inst.startswith("\\") else f"gt.{bus}"
    tb = tb.replace("integer cyc, bad, n;", "integer cyc, bad, n, macbad = 0;")
    tb = re.sub(r"(if \(cyc >= \d+\) begin)", r"\1 if (" + ref.replace("\\", "\\\\") + f"[{W - 1}:0] !== dut.m9k_{x}_{y}_q) macbad = macbad + 1;", tb, count=1)
    tb = tb.replace("$finish;", '$display("MACRESULT bad=%0d", macbad); $finish;')
    open(os.path.join(wd, "tb_m9k.v"), "w").write(tb)
    vvp = os.path.join(wd, "m9k.vvp")
    c = subprocess.run(["iverilog", "-g2012", "-o", vvp, os.path.join(wd, "tb_m9k.v"), os.path.join(wd, "emit.v"), os.path.join(d, "postfit.vo"), *S.sim_libs()],
                       capture_output=True, text=True, timeout=RUN_LIMIT_S)
    if c.returncode:
        return "compile_error", c.stderr[:200]
    r = subprocess.run(["vvp", vvp], capture_output=True, text=True, timeout=RUN_LIMIT_S)
    m = re.search(r"MACRESULT bad=(\d+)", r.stdout)
    return ("pass" if m and int(m[1]) == 0 else "fail" if m else "no_result"), (m[1] if m else r.stdout[-200:])


def cfg(name):
    """(matched, wrong) of the decoded word width / address width / output register against the .vo (single-block designs the emit models)."""
    d = os.path.join(REPO, "corpus", "cycloneiv", name)
    vo = open(os.path.join(d, "postfit.vo")).read()
    em = open(os.path.join(S.WORK, name, "emit.v")).read()
    m = re.search(r"// M9K m9k_\d+_\d+: single port, (\d+) bit x (\d+) words, output register = (\w+)", em)
    if not m or vo.count("cycloneiv_ram_block ") != 1:
        return None
    pin = re.search(r"\.portadatain\(\{?([^)]*?)\}?\)", vo)
    dw = sum(1 for t in pin[1].split(",") if t.strip() not in ("gnd", "vcc")) if pin else -1
    aw = re.search(r"port_a_address_width = (\d+)", vo)
    reg = re.search(r"port_a_data_out_clock = \"(\w+)\"", vo)
    return [("width", int(m[1]) == dw), ("address", aw is not None and int(m[2]) == 1 << int(aw[1])),
            ("oreg", (m[3] == "True") == (reg is not None and reg[1] != "none"))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="gxm9k_*")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_m9k_sim.log"))])
    res = {}
    for n in sorted(os.listdir(S.WORK)):
        if fnmatch.fnmatch(n, a.match) and os.path.exists(os.path.join(S.WORK, n, "emit.v")):
            res[n] = one(n)
            log.info("%s %s %s", n, *res[n])
    import zlib
    cf = {"width": [0, 0], "address": [0, 0], "oreg": [0, 0]}
    for n in res:
        c = cfg(n) if os.path.exists(os.path.join(S.WORK, n, "emit.v")) else None
        for k, ok in c or ():
            cf[k][0 if ok else 1] += 1
    log.info("M9K cfg (matched, wrong): %s", cf)
    for tag, sel in (("train", lambda n: zlib.crc32(n.encode()) % 4 != 0), ("holdout", lambda n: zlib.crc32(n.encode()) % 4 == 0), ("all", lambda n: True)):
        cnt = {}
        for n, (st, _) in res.items():
            if sel(n):
                cnt[st] = cnt.get(st, 0) + 1
        log.info("M9K SIM %s %d designs: %s", tag, sum(cnt.values()), cnt)


if __name__ == "__main__":
    main()
