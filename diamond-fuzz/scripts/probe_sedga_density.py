#!/usr/bin/env python3
"""
probe_sedga_density.py — determine which SEDGA DEV_DENSITY values Diamond
accepts for each ECP5 device.

Diamond's map stage enforces:

    ERROR - map: The DEV_DENSITY value of <X> on SED component '<inst>'
            should be consistent with the device '<dev>' used.

The rule is not documented in the simulation model (SEDGA.v lists
25KUM/45KU/45KUM/85KUM for every part) and the mapping from device to
accepted density is not in any grep-able table, so it is established here
by trying every (device, density) pair and recording which map cleanly.

This is a sweep, not a guess: failures are recorded as results.

Usage:
    python3 diamond-fuzz/scripts/probe_sedga_density.py
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

FUZZ_DIR = Path(__file__).resolve().parents[1]
ROOT = FUZZ_DIR.parent
WORK = ROOT / "tmp" / "sedga_density"
LOG_DIR = ROOT / "tmp" / "logs"

DIAMOND = Path(os.environ.get(
    "DIAMONDDIR", str(Path.home() / "lscc" / "diamond" / "3.14")))
DIAMONDC = DIAMOND / "bin" / "lin64" / "diamondc"
LICENSE = Path(os.environ.get("LM_LICENSE_FILE",
                              str(DIAMOND / "license" / "license.dat")))

DEVICES = {
    "12f": "LFE5U-12F-8BG256C",
    "25f": "LFE5U-25F-8BG256C",
    "45f": "LFE5U-45F-8BG256C",
    "85f": "LFE5U-85F-8BG381C",
}

# Every density string the simulation model mentions, plus the bare-density
# spellings, since the model's own comments use both "45KU" and "45KUM".
DENSITIES = ["12KU", "12KUM", "25KU", "25KUM",
             "45KU", "45KUM", "85KU", "85KUM"]

VERILOG = """\
module fuzz (
    input  wire clk, input wire d0,
    input  wire sedenable, input wire sedstart, input wire sedfrcerr,
    output wire sedclkout, output wire seddone,
    output wire sedinprog, output wire sederr, output wire out0
);
SEDGA #(.SED_CLK_FREQ("2.4"), .CHECKALWAYS("DISABLED"),
        .DEV_DENSITY("{density}")) u_sedga (
    .SEDENABLE(sedenable), .SEDSTART(sedstart), .SEDFRCERR(sedfrcerr),
    .SEDCLKOUT(sedclkout), .SEDDONE(seddone),
    .SEDINPROG(sedinprog), .SEDERR(sederr));
reg out0_r;
always @(posedge clk) out0_r <= d0;
assign out0 = out0_r;
endmodule
"""

LPF = """\
BLOCK RESETPATHS;
BLOCK ASYNCPATHS;
IOBUF PORT "clk" IO_TYPE=LVCMOS33;
IOBUF PORT "d0" IO_TYPE=LVCMOS33;
IOBUF PORT "sedenable" IO_TYPE=LVCMOS33;
IOBUF PORT "sedstart" IO_TYPE=LVCMOS33;
IOBUF PORT "sedfrcerr" IO_TYPE=LVCMOS33;
IOBUF PORT "sedclkout" IO_TYPE=LVCMOS33;
IOBUF PORT "seddone" IO_TYPE=LVCMOS33;
IOBUF PORT "sedinprog" IO_TYPE=LVCMOS33;
IOBUF PORT "sederr" IO_TYPE=LVCMOS33;
IOBUF PORT "out0" IO_TYPE=LVCMOS33;
FREQUENCY PORT "clk" 50.000000 MHz;
"""

LDF = """\
<?xml version="1.0" encoding="UTF-8"?>
<BaliProject version="3.2" title="fuzz" device="{device}" default_implementation="impl1">
    <Options/>
    <Implementation title="impl1" dir="impl1" description="impl1" synthesis="lse" default_strategy="Strategy1">
        <Options/>
        <Source name="fuzz.v" type="Verilog" type_short="Verilog"><Options/></Source>
        <Source name="fuzz.lpf" type="Logic Preference" type_short="LPF"><Options/></Source>
    </Implementation>
    <Strategy name="Strategy1" file="{sty}"/>
</BaliProject>
"""

RUN_TCL = """\
prj_project open "[file normalize [file join [file dirname [info script]] fuzz.ldf]]"
prj_run PAR    -impl impl1
prj_run Export -impl impl1 -task Bitgen
prj_project close
"""


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("probe_density")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "probe_sedga_density.log", mode="w")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    return log


def try_one(dev_tag: str, device: str, density: str,
            log: logging.Logger) -> tuple[bool, str]:
    d = WORK / f"{dev_tag}_{density}"
    (d / "impl1").mkdir(parents=True, exist_ok=True)
    (d / "fuzz.v").write_text(VERILOG.format(density=density))
    (d / "fuzz.lpf").write_text(LPF)
    (d / "fuzz.ldf").write_text(
        LDF.format(device=device, sty=str(FUZZ_DIR / "aw21.sty")))
    (d / "run.tcl").write_text(RUN_TCL)

    env = dict(os.environ)
    env["LM_LICENSE_FILE"] = str(LICENSE)
    logfile = d / "diamond.log"
    with open(logfile, "w") as fh:
        proc = subprocess.run([str(DIAMONDC), "run.tcl"],
                              stdout=fh, stderr=subprocess.STDOUT,
                              cwd=str(d), env=env)
    text = logfile.read_text(errors="replace")

    if (d / "impl1" / "fuzz_impl1.bit").exists() and proc.returncode == 0:
        return True, "ok"
    for line in text.splitlines():
        if "DEV_DENSITY" in line and "ERROR" in line:
            return False, "density rejected"
    for line in text.splitlines():
        if line.strip().startswith("ERROR"):
            return False, line.strip()[:120]
    return False, f"exit {proc.returncode}"


def main() -> None:
    log = setup_logging()
    if not DIAMONDC.exists():
        sys.exit(f"diamondc not found at {DIAMONDC}")
    WORK.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, str]] = {}
    for tag, device in DEVICES.items():
        results[tag] = {}
        for density in DENSITIES:
            ok, detail = try_one(tag, device, density, log)
            results[tag][density] = "accepted" if ok else detail
            log.info("%-4s %-6s %-8s %s", tag, density,
                     "ACCEPT" if ok else "REJECT", detail)

    out = ROOT / "tmp" / "sedga_density_matrix.json"
    out.write_text(json.dumps(results, indent=2, sort_keys=True))
    log.info("wrote %s", out)

    log.info("")
    log.info("=== accepted DEV_DENSITY per device ===")
    for tag in DEVICES:
        good = [d for d, v in results[tag].items() if v == "accepted"]
        log.info("  %-4s -> %s", tag, ", ".join(good) if good else "(none)")


if __name__ == "__main__":
    main()
