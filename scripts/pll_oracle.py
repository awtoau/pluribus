#!/usr/bin/env python3.15t
"""Diamond oracle for MachXO2 EHXPLLJ divider words (INT_DIVD feedback).

Each variant changes divider attributes; the native decode of the bitstream gives the
`word:` lines of the GPLL tile.  Result table -> docs/aw2-lift-status.md / pll_decode.py.

    python3.15t scripts/pll_oracle.py [--force]

Work dir tmp/pll_oracle/<variant>/ ; log tmp/logs/pll_oracle.log.
Diamond is single-seat: heavy_guard lock + RAM gate before every build; timeouts and
stall guard are efb_oracle's (measured 5-6 s per PAR+Bitgen of a one-PLL design).
Input is 100 MHz (default).  Variants with output dividers > 1 on OS/OS2/OS3 are rejected by
Diamond map ("cannot obtain FREQUENCY_PIN_*"), so output-divider words rely on the existing
ehxpllj_4out fuzz target (DIV 4/2/16 -> words 3/1/15).
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import efb_oracle as E  # noqa: E402
import heavy_guard  # noqa: E402
import native_config  # noqa: E402
import toolchain  # noqa: E402

WORK = REPO / "tmp" / "pll_oracle"
LOG = REPO / "tmp" / "logs" / "pll_oracle.log"
E.LOG = LOG

VARIANTS = {
    "base":     dict(CLKI_DIV=1, CLKFB_DIV=1, CLKOP_DIV=1, CLKOS_DIV=1, CLKOS2_DIV=1, CLKOS3_DIV=1),
    "i3":       dict(CLKI_DIV=3, CLKFB_DIV=1, CLKOP_DIV=1, CLKOS_DIV=1, CLKOS2_DIV=1, CLKOS3_DIV=1),
    "i3fb7":    dict(CLKI_DIV=3, CLKFB_DIV=7, CLKOP_DIV=5, CLKOS_DIV=1, CLKOS2_DIV=1, CLKOS3_DIV=1),
}


def verilog(p):
    prm = ",\n".join(f".{k}({v})" for k, v in p.items())
    return f"""module fuzz (input wire clk, output wire out0);
wire gnd = 1'b0; wire vcc = 1'b1;
wire clkop_w, clkos_w, clkos2_w, clkos3_w, lock_w;
EHXPLLJ #(
{prm},
.CLKOP_ENABLE("ENABLED"), .CLKOS_ENABLE("ENABLED"), .CLKOS2_ENABLE("ENABLED"),
.CLKOS3_ENABLE("ENABLED"), .FEEDBK_PATH("INT_DIVD")
) u0 (
    .CLKI(clk), .CLKFB(gnd), .RST(gnd), .STDBY(gnd), .PLLWAKESYNC(gnd),
    .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd), .PHASESTEP(gnd), .LOADREG(gnd),
    .RESETM(gnd), .RESETC(gnd), .RESETD(gnd),
    .ENCLKOP(vcc), .ENCLKOS(vcc), .ENCLKOS2(vcc), .ENCLKOS3(vcc),
    .PLLCLK(gnd), .PLLRST(gnd), .PLLSTB(gnd), .PLLWE(gnd),
    .PLLADDR4(gnd), .PLLADDR3(gnd), .PLLADDR2(gnd), .PLLADDR1(gnd), .PLLADDR0(gnd),
    .PLLDATI7(gnd), .PLLDATI6(gnd), .PLLDATI5(gnd), .PLLDATI4(gnd),
    .PLLDATI3(gnd), .PLLDATI2(gnd), .PLLDATI1(gnd), .PLLDATI0(gnd),
    .CLKOP(clkop_w), .CLKOS(clkos_w), .CLKOS2(clkos2_w), .CLKOS3(clkos3_w), .LOCK(lock_w)
);
reg out0_r;
always @(posedge clkop_w) out0_r <= lock_w ^ clkos_w ^ clkos2_w ^ clkos3_w;
assign out0 = out0_r;
endmodule
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    log = E.setup_logging()
    sys.path.insert(0, str(REPO))
    import pll_decode
    results = {}
    ok_all = True
    for name, p in VARIANTS.items():
        d = WORK / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "fuzz.v").write_text(verilog(p))
        (d / "fuzz.lpf").write_text(E.lpf("pll"))
        (d / "fuzz.ldf").write_text(E.LDF % E.STY)
        (d / "run.tcl").write_text(E.TCL)
        bit = d / "impl1" / "fuzz_impl1.bit"
        if a.force or not bit.exists():
            heavy_guard.wait_available(log, f"diamond pll {name}")
            with heavy_guard.heavy_lock(f"pll_oracle {name}", log):
                ok, el, detail = E.run_diamond(d, log)
            log.info("build %s: ok=%s took %.1fs %s", name, ok, el, detail)
            if not ok:
                ok_all = False
                continue
        text, _pb, _b = native_config.config_from_file(
            str(bit), device=E.DEVICE, db_root=toolchain.trellis_dbroot())
        pll = pll_decode.parse_pll(text)
        got = {"I": pll["i_div"], "FB": pll["fb_div"], **{k: v for k, v in pll["out_div"].items()}}
        want = {"I": p["CLKI_DIV"], "FB": p["CLKFB_DIV"], "CLKOP": p["CLKOP_DIV"],
                "CLKOS": p["CLKOS_DIV"], "CLKOS2": p["CLKOS2_DIV"], "CLKOS3": p["CLKOS3_DIV"]}
        match = got == want
        ok_all &= match
        results[name] = {"want": want, "decoded": got, "match": match,
                         "words": {k: v for k, v in pll["words"].items() if k.endswith("_DIV")}}
        log.info("%-8s want %s decoded %s %s", name, want, got, "MATCH" if match else "MISMATCH")
    (WORK / "results.json").write_text(json.dumps(results, indent=1, sort_keys=True))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
