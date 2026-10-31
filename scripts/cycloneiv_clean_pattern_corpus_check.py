#!/usr/bin/env python3.15t
"""#186: validate rtl.py's pattern recognizer against known-truth specimens, independent of the DJI image.

Each specimen is small behavioral Verilog with a KNOWN construct type (adder, comparator, counter, shift
register, LFSR) built once with Quartus (so the recognizer sees real post-fit LUT structure, not source),
then lifted and checked against rtl.lift()'s report counts for that construct's rule tag.  This is the gap
F-021 exposed: a pattern can regress silently if no corpus specimen exercises it (the DJI image's own
behavioral test was the only thing that ever caught it).  Not a classifier or a sweep -- one check per
known construct, pass/fail against an expected count, per the #186 scoping discipline.

  python3.15t scripts/cycloneiv_clean_pattern_corpus_check.py   # log tmp/logs/cycloneiv_clean_pattern_corpus_check.log
Builds corpus/cycloneiv/pcheck_<name>/ (gitignored like every other cycloneiv fuzz specimen).
"""
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("pattern_corpus_check")
DEVICE = "EP4CGX150DF31C7"
LIMITS = {"quartus_map": 180, "quartus_fit": 600, "quartus_asm": 60, "quartus_cpf": 10}

# Each specimen: known construct, minimal IO, wide enough operands that Quartus must use the carry
# chain / dedicated LUT shapes rtl.py's recognizers target (not absorbed into a handful of LUTs).
SPECIMENS = {
    "adder": dict(
        rtl='''module top(input clk, input [7:0] a, input [7:0] b, output [8:0] sum);
  reg [8:0] r;
  always @(posedge clk) r <= a + b;
  assign sum = r;
endmodule
''',
        expect=lambda rep: rep["adders"] >= 1 and rep["flat_lut_left"] == 0),
    "subtractor": dict(
        rtl='''module top(input clk, input [7:0] a, input [7:0] b, output [8:0] diff);
  reg [8:0] r;
  always @(posedge clk) r <= a - b;
  assign diff = r;
endmodule
''',
        expect=lambda rep: rep["subtractors"] >= 1 and rep["flat_lut_left"] == 0),
    "comparator": dict(
        rtl='''module top(input clk, input [7:0] a, input [7:0] b, output ge);
  reg r;
  always @(posedge clk) r <= (a >= b);
  assign ge = r;
endmodule
''',
        expect=lambda rep: rep["comparators"] >= 1 and rep["flat_lut_left"] == 0),
    "counter": dict(
        rtl='''module top(input clk, input rst, output [7:0] cnt);
  reg [7:0] r;
  always @(posedge clk) if (rst) r <= 8'd0; else r <= r + 8'd1;
  assign cnt = r;
endmodule
''',
        expect=lambda rep: rep["counters"] >= 1 and rep["flat_lut_left"] == 0),
    "shift_register": dict(
        rtl='''module top(input clk, input din, output dout);
  reg [15:0] sr;
  always @(posedge clk) sr <= {sr[14:0], din};
  assign dout = sr[15];
endmodule
''',
        expect=lambda rep: rep["shift_registers"] >= 1 and rep["flat_lut_left"] == 0),
}


def build(name, rtl):
    import cycloneiv_fuzz as fz
    import toolchain
    d = Path(REPO) / "corpus" / "cycloneiv" / f"pcheck_{name}"
    shutil.rmtree(d, ignore_errors=True)
    (d / "src").mkdir(parents=True)
    q = d / "quartus"
    q.mkdir()
    (d / "src" / "top.v").write_text(rtl)
    qsf = ['set_location_assignment PIN_A11 -to clk', 'set_global_assignment -name AUTO_GLOBAL_CLOCK OFF',
           'set_global_assignment -name SEED 1']
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "#186 pattern-recognizer corpus check: known-truth {name}"\n'
        f'exercises = ["pattern_corpus_check"]\nqsf = {json.dumps(qsf)}\ndevice = "{DEVICE}"\n')
    full = ['set_global_assignment -name FAMILY "Cyclone IV GX"', f"set_global_assignment -name DEVICE {DEVICE}",
            "set_global_assignment -name TOP_LEVEL_ENTITY top", "set_global_assignment -name VERILOG_FILE ../src/top.v",
            'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
            "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1"] + qsf
    (q / "build.qsf").write_text("\n".join(full) + "\n")
    (q / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = toolchain.quartus_bin()
    t0 = time.time()
    steps = [("quartus_map", [f"{qb}/quartus_map", "build"]), ("quartus_fit", [f"{qb}/quartus_fit", "build"]),
             ("quartus_asm", [f"{qb}/quartus_asm", "build"]),
             ("quartus_cpf", [f"{qb}/quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    for step, cmd in steps:
        if not fz.run(step, cmd, q, d / "logs", LIMITS):
            raise SystemExit(f"{name}: {step} failed")
    shutil.copyfile(q / "build.rbf", d / "bitstream.rbf")
    json.dump({"status": "ok", "elapsed_s": round(time.time() - t0, 1)}, open(d / "rebuild.json", "w"))
    shutil.rmtree(q)
    log.info("%s build ok %.0fs", name, time.time() - t0)
    return d / "bitstream.rbf"


def lift_report(rbf):
    from lifters.cycloneiv_clean import emit, rtl
    import heavy_guard
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    with heavy_guard.lease(gb, "cyc4_clean_rtl_pcheck", log):
        cx = emit.Ctx()
        nl = emit.Builder(cx, str(rbf), None).run()
    _, rep = rtl.lift(nl)
    return rep


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_pattern_corpus_check.log"))])
    import heavy_guard
    results = {}
    with heavy_guard.lease(6, "cyc4_pattern_corpus_check", log):
        for name, spec in SPECIMENS.items():
            rbf = build(name, spec["rtl"])
            rep = lift_report(rbf)
            ok = spec["expect"](rep)
            results[name] = dict(ok=ok, adders=rep["adders"], subtractors=rep["subtractors"], comparators=rep["comparators"],
                                  counters=rep["counters"], shift_registers=rep["shift_registers"], flat_lut_left=rep["flat_lut_left"])
            log.info("%s: %s %s", name, "PASS" if ok else "FAIL", results[name])
    all_ok = all(r["ok"] for r in results.values())
    out = dict(all_ok=all_ok, results=results)
    log.info("RESULT %s", json.dumps(out, indent=1))
    json.dump(out, open(Path(REPO) / "tmp" / "logs" / "cycloneiv_clean_pattern_corpus_check_result.json", "w"), indent=1)
    print(json.dumps(out, indent=1))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
