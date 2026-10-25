#!/usr/bin/env python3.15t
"""Cross-check our cyclonev_mac model (lifters/data/cyclonev_mac_model.v) against the ENCRYPTED vendor
atom in Questa (scripts/questa.py, library cyclonev_ver).

- Configs: every cyclonev_mac instance in a corpus build.vo (its exact defparams), plus seeded random
  configs over the modes the model claims (m9x9, m18x18_full, m18x18_sumof2, m27x27): signedness and
  operand / output register clocks random, Quartus port widths per mode, result_a_width 64.
- Each config: vendor atom and our model side by side, same random operands, enables and clock pulses.
- Per resulta bit per sample: ok | wrong (both 0/1, differ) | missing (vendor 0/1, model X) | vx (vendor X).
  Agreement headline = ok / (ok + wrong + missing); PASS = wrong == 0 and missing == 0.
Usage: python3.15t scripts/cyclonev_dsp_vendor_check.py [--random N] [--steps N] [--seed N]
Log: tmp/logs/cyclonev_dsp_vendor_check.log
"""
import argparse
import random
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
import questa  # noqa: E402
from lifters.cyclonev_hard import _DSP_WIDTH  # noqa: E402

CORPUS = REPO / "corpus" / "cyclonev"
WORK = REPO / "tmp" / "dsp_vendor_check"
LOG = REPO / "tmp" / "logs" / "cyclonev_dsp_vendor_check.log"
MODEL = REPO / "lifters" / "data" / "cyclonev_mac_model.v"
MODES = {"m9x9": "m9x9", "m18x18_full": "m18x18_full", "m18x18_sumof2": "m18x18_sumof2", "m27x27": "m27x27"}
CLOCKS = ('"none"', '"0"', '"1"', '"2"')


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


def corpus_configs():
    """(label, {param: verilog value}) per cyclonev_mac instance in the corpus build.vo files."""
    out = []
    for d in sorted(p.name for p in CORPUS.iterdir() if (p / "design.toml").is_file()):
        vo_p = CORPUS / d / "quartus" / "simulation" / "questa" / "build.vo"
        if not vo_p.is_file():
            continue
        vo = vo_p.read_text()
        for m in re.finditer(r"^cyclonev_mac\s+(\\\S+|\w+)\s*\(", vo, re.M):
            name = m.group(1)
            par = dict(re.findall(rf"defparam\s+{re.escape(name)}\s*\.(\w+)\s*=\s*(.+?);", vo))
            out.append((f"{d}:{name.lstrip(chr(92))}", par))
    return out


def random_configs(n, rnd):
    out = []
    for i in range(n):
        mode = rnd.choice(sorted(MODES))
        axw, ayw, bxw, byw = _DSP_WIDTH[mode]
        par = {"operation_mode": f'"{mode}"', "ax_width": axw, "ay_scan_in_width": ayw, "bx_width": bxw,
               "by_width": byw, "result_a_width": 64}
        for s in ("max", "may", "mbx", "mby"):
            par[f"signed_{s}"] = rnd.choice(('"true"', '"false"'))
        for c in ("ax_clock", "ay_scan_in_clock", "bx_clock", "by_clock", "output_clock"):
            par[c] = rnd.choice(CLOCKS)
        out.append((f"random{i}:{mode}", par))
    return out


def testbench(configs, steps, rnd):
    w = lambda par, k, d: int(str(par.get(k, d)).strip())
    tb = ["`timescale 1ps/1ps", "module tb;",
          "  reg [26:0] ax = 0, ay = 0, bx = 0, by = 0; reg [2:0] clk = 0, ena = 3'b111;",
          "  integer ok [0:%d]; integer wrong [0:%d]; integer missing [0:%d]; integer vx [0:%d];"
          % ((len(configs) - 1,) * 4), "  integer i, b;"]
    for i, (_lbl, par) in enumerate(configs):
        ps = ", ".join(f".{k}({v})" for k, v in par.items())
        rw = w(par, "result_a_width", 33)
        con = (f".ax(ax[{w(par, 'ax_width', 16) - 1}:0]), .ay(ay[{w(par, 'ay_scan_in_width', 16) - 1}:0]), "
               f".bx(bx[{w(par, 'bx_width', 16) - 1}:0]), .by(by[{w(par, 'by_width', 16) - 1}:0]), "
               ".az(1'b0), .bz(1'b0), .coefsela(3'b0), .coefselb(3'b0), .scanin(), .chainin(64'b0), "
               ".loadconst(1'b0), .accumulate(1'b0), .negate(1'b0), .sub(1'b0), .clk(clk), .ena(ena), "
               ".aclr(2'b0), .resultb(), .scanout(), .chainout(), .dftout()")
        tb += [f"  wire [{rw - 1}:0] v{i}, m{i};",
               f"  cyclonev_mac #({ps}) uv{i} ({con}, .resulta(v{i}));",
               f"  pluribus_cv_mac_model #({ps}) um{i} ({con}, .resulta(m{i}));"]
    tb.append("  task check; begin")
    for i, (_lbl, par) in enumerate(configs):
        rw = w(par, "result_a_width", 33)
        tb.append(f"    for (b = 0; b < {rw}; b = b + 1)"
                  f" if (v{i}[b] !== 1'b0 && v{i}[b] !== 1'b1) vx[{i}] = vx[{i}] + 1;"
                  f" else if (m{i}[b] !== 1'b0 && m{i}[b] !== 1'b1) missing[{i}] = missing[{i}] + 1;"
                  f" else if (v{i}[b] === m{i}[b]) ok[{i}] = ok[{i}] + 1; else wrong[{i}] = wrong[{i}] + 1;")
    tb.append("  end endtask")
    tb.append("  initial begin")
    tb.append(f"    for (i = 0; i < {len(configs)}; i = i + 1) begin ok[i] = 0; wrong[i] = 0; missing[i] = 0; vx[i] = 0; end")
    for _ in range(steps):
        tb.append(f"    ax = 27'd{rnd.getrandbits(27)}; ay = 27'd{rnd.getrandbits(27)}; "
                  f"bx = 27'd{rnd.getrandbits(27)}; by = 27'd{rnd.getrandbits(27)}; "
                  f"ena = 3'd{rnd.getrandbits(3) | (7 if rnd.random() < 0.75 else 0)};")
        tb.append("    #1000; check;")
        tb.append(f"    clk = 3'd{rnd.getrandbits(3) | (7 if rnd.random() < 0.5 else 0)}; #1000; check; clk = 0; #1000; check;")
    for i, (lbl, _par) in enumerate(configs):
        tb.append(f'    $display("RESULT {i} {lbl} ok=%0d wrong=%0d missing=%0d vx=%0d", ok[{i}], wrong[{i}], missing[{i}], vx[{i}]);')
    tb += ["    $finish;", "  end", "endmodule"]
    return "\n".join(tb) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--random", type=int, default=64, help="random configs (default 64)")
    ap.add_argument("--steps", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if not questa.available():
        log("FAIL: Questa not installed / no licence")
        return 1
    rnd = random.Random(a.seed)
    configs = corpus_configs() + random_configs(a.random, rnd)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "model_r.v").write_text(MODEL.read_text().replace("module cyclonev_mac (", "module pluribus_cv_mac_model (", 1))
    (WORK / "tb.v").write_text(testbench(configs, a.steps, rnd))
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S%z')} configs={len(configs)} steps={a.steps} seed={a.seed}")
    stage, ok, text = questa.compile_and_run(WORK / "q", [WORK / "tb.v", WORK / "model_r.v"], "tb")
    rows = re.findall(r"RESULT (\d+) (\S+) ok=(\d+) wrong=(\d+) missing=(\d+) vx=(\d+)", text)
    if not ok or len(rows) != len(configs):
        log(f"ERROR at {stage}: {text[-1500:]}")
        return 1
    tot = [0, 0, 0, 0]
    bad = 0
    for _i, lbl, *nums in rows:
        o, wr, mi, vx = map(int, nums)
        tot = [t + v for t, v in zip(tot, (o, wr, mi, vx))]
        good = wr == 0 and mi == 0 and o > 0
        bad += not good
        log(f"{'OK  ' if good else 'FAIL'} {lbl:48s} agree {o}/{o + wr + mi} wrong={wr} missing={mi} vendor-x={vx}")
    o, wr, mi, vx = tot
    log(f"total: {len(rows) - bad}/{len(rows)} configs agree; bits agree {o}/{o + wr + mi} "
        f"({100 * o / max(1, o + wr + mi):.2f}%) wrong={wr} missing={mi} vendor-x={vx}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
