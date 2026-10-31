#!/usr/bin/env python3.15t
"""Register-feedback + independent-sload specimen on EP4CGX150 (#183): the gap F-020's corpus (#182) never
exercised -- one LE whose comb LUT genuinely reads its own register on DATAC/gi2 (LE_USE_REGISTER_FEEDBACK,
F-010's validated case) while that SAME LE's sload/ASDATA path is separately driven by a different, real
signal (not its own Q).  F-020 wrongly let LE_USE_REGISTER_FEEDBACK short-circuit the ASDATA/sload source to
a self-loop (own D = own Q forever) instead of the real sload signal; this is the DJI AF3 SHA-1 engine's
a..e/W-schedule trigger in miniature, with a Quartus post-fit .vo oracle to score against.

  python3.15t scripts/cycloneiv_clean_regfb_sload_specimen.py     # log tmp/logs/cycloneiv_clean_regfb_sload_specimen.log
Builds corpus/cycloneiv/gxct_e_regfb_sload (src/, design.toml tracked; bitstream.rbf, postfit.vo, routing.rcf,
build.pin local).  Scored automatically by cycloneiv_clean_ffctl_check.py's ff_asdata category (globs corpus/cycloneiv/*).
Black box: quartus only.  Build limits as cycloneiv_clean_carry_specimens.py (map 180 s, fit 600 s, asm 60 s, cpf 10 s).
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
log = logging.getLogger("regfb_sload_specimen")
DEVICE = "EP4CGX150DF31C7"
NAME = "gxct_e_regfb_sload"
LIMITS = {"quartus_map": 180, "quartus_fit": 600, "quartus_asm": 60, "quartus_cpf": 10, "quartus_eda": 120, "quartus_cdb": 120}
# LAB e = X46Y46 (unused by the gxct a/b/c/d family at X10Y10 / X58Y30 / X37Y60 / X100Y75); far FF LAB a (X10Y10).
LX, LY = 46, 46
FX, FY = 10, 10
TOP = '''module top(input D, D2, output y0, output yf1, output yf2);
  wire KA;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    sKA (.dataa(D), .datab(D2), .combout(KA));
  wire L;
  cycloneiv_lcell_comb #(.lut_mask(16'h1111), .sum_lutc_input("datac"), .dont_touch("on"))
    sL (.dataa(D), .datab(D2), .combout(L));
  wire M;
  cycloneiv_lcell_comb #(.lut_mask(16'hCCCC), .sum_lutc_input("datac"), .dont_touch("on"))
    sM (.dataa(D), .datab(D2), .combout(M));
  // l0: comb LUT whose DATAC pin is r0's own Q (LE_USE_REGISTER_FEEDBACK, F-010's validated comb-pin case).
  // r0's sload/ASDATA is separately driven by M (a real, different signal, NOT q0) -- the #183 interaction:
  // one LE where the register-feedback bit is set AND the independent sload mux selects a different source.
  wire l0_o, q0;
  cycloneiv_lcell_comb #(.lut_mask(16'h9688), .sum_lutc_input("datac"), .dont_touch("on"))
    l0 (.dataa(D), .datab(D2), .datac(q0), .datad(M), .combout(l0_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) r0 (.d(l0_o), .q(q0), .clk(KA), .sload(L), .asdata(M));
  wire fl_o, fq1, fq2;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    fl (.dataa(D), .combout(fl_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far1 (.d(fl_o), .q(fq1), .clk(KA), .sload(L), .asdata(M));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far2 (.d(fl_o), .q(fq2), .clk(KA));
  assign y0 = q0;
  assign yf1 = fq1;
  assign yf2 = fq2;
endmodule
'''


def build():
    import cycloneiv_fuzz as fz
    import toolchain
    d = Path(REPO) / "corpus" / "cycloneiv" / NAME
    shutil.rmtree(d, ignore_errors=True)
    (d / "src").mkdir(parents=True)
    q = d / "quartus"
    q.mkdir()
    (d / "src" / "top.v").write_text(TOP)
    qsf = [
        f"set_location_assignment LCCOMB_X{LX}_Y{LY}_N30 -to sKA", f"set_location_assignment LCCOMB_X{LX}_Y{LY}_N28 -to sL",
        f"set_location_assignment LCCOMB_X{LX}_Y{LY}_N26 -to sM", f"set_location_assignment LCCOMB_X{LX}_Y{LY}_N0 -to l0",
        f"set_location_assignment FF_X{LX}_Y{LY}_N1 -to r0", f"set_location_assignment LCCOMB_X{FX}_Y{FY}_N0 -to fl",
        f"set_location_assignment FF_X{FX}_Y{FY}_N1 -to far1", f"set_location_assignment FF_X{FX}_Y{FY + 2}_N1 -to far2",
        "set_location_assignment PIN_A11 -to D", "set_location_assignment PIN_A15 -to D2",
        "set_location_assignment PIN_B9 -to y0", "set_location_assignment PIN_A13 -to yf1",
        "set_location_assignment PIN_A14 -to yf2",
        "set_global_assignment -name AUTO_GLOBAL_CLOCK OFF", "set_global_assignment -name AUTO_GLOBAL_REGISTER_CONTROLS OFF",
        "set_global_assignment -name SEED 1", 'set_global_assignment -name FITTER_EFFORT "FAST FIT"',
    ]
    (d / "design.toml").write_text(
        'top = "top"\npurpose = "register feedback (LE_USE_REGISTER_FEEDBACK) + independent sload/ASDATA source on one LE (#183)"\n'
        'exercises = ["ctrl", "asdata", "register_feedback"]\nqsf = %s\ndevice = "%s"\n' % (json.dumps(qsf), DEVICE))
    full = ['set_global_assignment -name FAMILY "Cyclone IV GX"', f"set_global_assignment -name DEVICE {DEVICE}",
            "set_global_assignment -name TOP_LEVEL_ENTITY top", "set_global_assignment -name VERILOG_FILE ../src/top.v",
            'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
            "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1",
            'set_global_assignment -name EDA_SIMULATION_TOOL "QuestaSim (Verilog)"',
            'set_global_assignment -name EDA_OUTPUT_DATA_FORMAT "VERILOG HDL" -section_id eda_simulation'] + qsf
    (q / "build.qsf").write_text("\n".join(full) + "\n")
    (q / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = toolchain.quartus_bin()
    t0 = time.time()
    steps = [("quartus_map", [f"{qb}/quartus_map", "build"]), ("quartus_fit", [f"{qb}/quartus_fit", "build"]),
             ("quartus_asm", [f"{qb}/quartus_asm", "build"]),
             ("quartus_eda", [f"{qb}/quartus_eda", "build", "--simulation", "--tool=modelsim", "--format=verilog"]),
             ("quartus_cpf", [f"{qb}/quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    for step, cmd in steps:
        if not fz.run(step, cmd, q, d / "logs", LIMITS):
            raise SystemExit(f"{NAME}: {step} failed")
    if not fz.rcf_export(q, d, Path(qb), LIMITS):
        raise SystemExit(f"{NAME}: routing export failed")
    import glob
    shutil.copyfile(next(glob.iglob(str(q / "simulation" / "**" / "*.vo"), recursive=True)), d / "postfit.vo")
    shutil.copyfile(q / "build.rbf", d / "bitstream.rbf")
    shutil.copyfile(q / "build.pin", d / "build.pin")
    json.dump({"status": "ok", "attempts": 1, "elapsed_s": round(time.time() - t0, 1)}, open(d / "rebuild.json", "w"))
    shutil.rmtree(q)
    log.info("%s ok %.0fs", NAME, time.time() - t0)


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_regfb_sload_specimen.log"))])
    import heavy_guard
    with heavy_guard.lease(6, "cyc4_regfb_sload_specimen", log):
        build()


if __name__ == "__main__":
    main()
