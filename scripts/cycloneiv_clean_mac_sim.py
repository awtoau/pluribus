#!/usr/bin/env python3.15t
"""MAC functional equivalence (#165): emitted `mac_<x>_<y>_r` vs the post-fit `mac_out` DATAOUT bus, every cycle after warm-up.

  python3.15t scripts/cycloneiv_clean_mac_sim.py [--match 'gxhb_mac*']      (needs cycloneiv_clean_emit_sim.py to have run on the designs: reuses its tb.v / emit.v)
The result pads of the MAC specimens have no decoded driver (BIM path), so emit_sim reports `none` for them; this compares the multiplier output directly.
One MAC tile per design (18 x 18, or one / two 9 x 9: each mac_out compared with its 18-bit slice); several tiles are listed as not modelled.  Log tmp/logs/cycloneiv_clean_mac_sim.log.
"""
import argparse
import fnmatch
import logging
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_emit_sim as S  # noqa: E402

log = logging.getLogger("cycloneiv_clean_mac_sim")
RUN_LIMIT_S = 120      # emit_sim: iverilog compile + 300 cycles measured 1-2 s; 3x cold worst case as backstop


def one(name):
    d = os.path.join(REPO, "corpus", "cycloneiv", name)
    wd = os.path.join(S.WORK, name)
    vo = open(os.path.join(d, "postfit.vo")).read()
    outs = re.findall(r"// Location: DSPOUT_X(\d+)_Y(\d+)_N(\d)\ncycloneiv_mac_out (\S+) ", vo)
    mults = re.findall(r"cycloneiv_mac_mult (\S+) ", vo)
    xy = {(o[0], o[1]) for o in outs}
    if not outs or len(xy) != 1:
        return "not_modelled", f"{len(mults)} mult / {len(outs)} out in {len(xy)} tiles"
    x, y = next(iter(xy))
    nine = "dataa_width = 9;" in vo
    cmp = []
    for _, _, n, inst in outs:
        bus = inst.lstrip("\\") + "_DATAOUT_bus"
        ref = f"gt.\\{bus} " if inst.startswith("\\") else f"gt.{bus}"
        lo, w = (18 * (int(n) - 2), 18) if nine else (0, 36)
        cmp.append(f"({ref}[{w - 1}:0] !== dut.mac_{x}_{y}_r[{lo + w - 1}:{lo}])")
    tb = open(os.path.join(wd, "tb.v")).read()
    tb = tb.replace("integer cyc, bad, n;", "integer cyc, bad, n, macbad = 0;")
    tb = re.sub(r"(if \(cyc >= \d+\) begin)", lambda m: m[1] + " if (" + " || ".join(cmp) + ") macbad = macbad + 1;", tb, count=1)
    tb = tb.replace("$finish;", '$display("MACRESULT bad=%0d", macbad); $finish;')
    open(os.path.join(wd, "tb_mac.v"), "w").write(tb)
    vvp = os.path.join(wd, "mac.vvp")
    c = S.run_tool(["iverilog", "-g2012", "-o", vvp, os.path.join(wd, "tb_mac.v"), os.path.join(wd, "emit.v"), os.path.join(d, "postfit.vo"), *S.sim_libs()])
    if c.timed_out:
        return "timeout", "iverilog exceeded the guard"
    if c.returncode:
        return "compile_error", c.stderr[:200]
    r = S.run_tool(["vvp", vvp])
    if r.timed_out:
        return "timeout", "vvp exceeded the guard"
    m = re.search(r"MACRESULT bad=(\d+)", r.stdout)
    return ("pass" if m and int(m[1]) == 0 else "fail" if m else "no_result"), (m[1] if m else r.stdout[-200:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="gxhb_mac*")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_mac_sim.log"))])
    res = {}
    for n in sorted(os.listdir(S.WORK)):
        if fnmatch.fnmatch(n, a.match) and os.path.exists(os.path.join(S.WORK, n, "emit.v")) and os.path.exists(os.path.join(REPO, "corpus", "cycloneiv", n, "postfit.vo")):
            res[n] = one(n)
            log.info("%s %s %s", n, *res[n])
    cnt = {}
    for st, _ in res.values():
        cnt[st] = cnt.get(st, 0) + 1
    log.info("MAC SIM %d designs: %s", len(res), cnt)


if __name__ == "__main__":
    main()
