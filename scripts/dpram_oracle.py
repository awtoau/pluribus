#!/usr/bin/env python3.15t
"""Diamond oracle for MachXO2 distributed RAM (DPR16X4C -> RAMW + 2 DPRAM slices), issue #127.

One build with every DPR16X4C input on its own registered net and a non-trivial INITVAL.
Reports (a) which slice input wire carries each primitive pin (ncd2nmc route sinks),
(b) which slice letter / LUT holds each output bit, (c) how INITVAL lands in the K0/K1.INIT words
of the decoded .config.  The table is what lifters/machxo2_dpram.py encodes.

    python3.15t scripts/dpram_oracle.py [--force]
Work dir tmp/dpram_oracle/dpr/ ; log tmp/logs/dpram_oracle.log ; result tmp/dpram_oracle/result.json.
Diamond is single-seat: heavy_guard lock + RAM gate (as efb_oracle).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import efb_oracle as E  # noqa: E402
import heavy_guard  # noqa: E402
import machxo2_diamond_oracle as O  # noqa: E402
import native_config  # noqa: E402
import toolchain  # noqa: E402

WORK = REPO / "tmp" / "dpram_oracle"
LOG = REPO / "tmp" / "logs" / "dpram_oracle.log"
E.LOG = LOG
INITVAL = "0xFEDCBA9876543210"      # distinct nibble per address: MEM[a] = a (or reversed)

SRC = f"""module fuzz (input wire clk, input wire [3:0] di, input wire [3:0] wad, input wire we,
                 input wire [3:0] rad, output wire [3:0] dout);
reg [3:0] di_r, wad_r, rad_r; reg we_r;
always @(posedge clk) begin di_r <= di; wad_r <= wad; rad_r <= rad; we_r <= we; end
wire [3:0] do_w;
DPR16X4C #(.initval("{INITVAL}")) u0 (
    .DI3(di_r[3]), .DI2(di_r[2]), .DI1(di_r[1]), .DI0(di_r[0]),
    .WAD3(wad_r[3]), .WAD2(wad_r[2]), .WAD1(wad_r[1]), .WAD0(wad_r[0]),
    .WRE(we_r), .WCK(clk),
    .RAD3(rad_r[3]), .RAD2(rad_r[2]), .RAD1(rad_r[1]), .RAD0(rad_r[0]),
    .DO3(do_w[3]), .DO2(do_w[2]), .DO1(do_w[1]), .DO0(do_w[0]));
assign dout = do_w;
endmodule
"""

PINS = [("clk", 88)] + [(f"di[{i}]", p) for i, p in enumerate((84, 85, 86, 87))] + \
    [(f"wad[{i}]", p) for i, p in enumerate((89, 90, 91, 92))] + [("we", 93)] + \
    [(f"rad[{i}]", p) for i, p in enumerate((94, 95, 96, 97))] + \
    [(f"dout[{i}]", p) for i, p in enumerate((98, 99, 100, 82))]


def lpf():
    body = "BLOCK RESETPATHS;\nBLOCK ASYNCPATHS;\n\n"
    for name, site in PINS:
        body += f'LOCATE COMP "{name}" SITE "{site}";\nIOBUF PORT "{name}" IO_TYPE=LVCMOS33;\n\n'
    return body + 'FREQUENCY PORT "clk" 100.000000 MHz;\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    log = E.setup_logging()
    d = WORK / "dpr"
    d.mkdir(parents=True, exist_ok=True)
    (d / "fuzz.v").write_text(SRC)
    (d / "fuzz.lpf").write_text(lpf())
    (d / "fuzz.ldf").write_text(E.LDF % E.STY)
    (d / "run.tcl").write_text(E.TCL)
    bit = d / "impl1" / "fuzz_impl1.bit"
    if a.force or not bit.exists():
        heavy_guard.wait_available(log, "diamond dpram oracle")
        with heavy_guard.heavy_lock("dpram_oracle", log):
            ok, el, detail = E.run_diamond(d, log)
        log.info("build: ok=%s took %.1fs %s", ok, el, detail)
        if not ok:
            return 1
    text, _pb, _b = native_config.config_from_file(
        str(bit), device=E.DEVICE, db_root=toolchain.trellis_dbroot())
    (d / "decoded.config").write_text(text)
    # routing + pin nets
    dd, env = O.diamond_env()
    bindir = os.path.join(dd, "ispfpga", "bin", "lin64")
    with heavy_guard.heavy_lock("dpram_oracle_tools", log):
        r = O.process("dpr", str(WORK), str(WORK / "out"), env, bindir, True)
    log.info("oracle: %s", r)
    oj = json.loads((WORK / "out" / "dpr" / "oracle.json").read_text())
    res = {"pins": {}, "slices": {}, "init": {}}
    for c in oj["comps"]:
        if re.search(r"MODE:(DPRAM|RAMW)", c["config"]):
            res["slices"][c["name"]] = {"site": c.get("site"), "mode": re.search(r"MODE:(\w+)", c["config"]).group(1),
                                        "pins": c["pins"]}
    for n in oj["nets"]:
        sinks = [b for a_, b in n["arcs"] if re.search(r"_(?:[A-D][0-7]|M[01]|WD\d|WAD\d|WRE|WCK|CE\d|LSR\d|CLK\d)$", b)]
        res["pins"][n["name"]] = {"pins": n["pins"], "slice_sinks": sinks}
    for m in re.finditer(r"^\.tile (R\d+C\d+):PLC\n(.*?)(?=^\.tile |\Z)", text, re.M | re.S):
        inits = re.findall(r"^word: (SLICE[A-D]\.K[01]\.INIT) (\d+)$", m.group(2), re.M)
        modes = re.findall(r"^enum: (SLICE[A-D]\.MODE) (\w+)$", m.group(2), re.M)
        if modes and any(v in ("DPRAM", "RAMW") for _k, v in modes):
            res["init"][m.group(1)] = {"modes": modes, "words": inits}
    (WORK / "result.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    for k, v in res["pins"].items():
        log.info("net %-14s pins %s sinks %s", k, [f"{p['comp']}.{p['pin']}" for p in v["pins"]], v["slice_sinks"])
    for k, v in res["init"].items():
        log.info("tile %s %s %s", k, v["modes"], v["words"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
