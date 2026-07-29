#!/usr/bin/env python3
"""
gen_sedga_targets.py — generate ECP5 SEDGA fuzz targets for Lattice Diamond.

SEDGA is the ECP5 soft-error-detection block: it runs a CRC over the
*configuration* memory and asserts SEDERR when a configuration bit has
flipped.  With CHECKALWAYS=ENABLED it re-runs continuously in the
background, which is what makes it valuable for long-run hardware soak
testing -- it distinguishes "the run failed" from "the run failed *and*
the loaded bitstream was corrupt at the time".

Sweep policy (docs/fuzzing-coverage.md): sweep the FULL parameter space,
never prune.  Targets build in seconds and run_all_fuzz.py skips unchanged
results on re-run, so there is no cost to going bigger.  Accordingly this
generates the full cross-product

    SED_CLK_FREQ  x  CHECKALWAYS  x  DEV_DENSITY  x  tie-off variant

rather than sweeping each axis separately with the others held at default.
DEV_DENSITY is swept across all four legal values even though none of them
names the Cynthion's 12F part -- what Diamond does with a density that does
not match the device is exactly the sort of thing an assumption skips and a
sweep catches.  Input tie-off variants are included because two useful
MachXO2 findings (pluribus#29 EBR.MODE bit address, pluribus#11
PULLMODE/BASE_TYPE overlap) only surfaced from a full cross-product.

Combinations that look pointless are deliberately included.  Targets that
fail to build are results too and are recorded rather than dropped.

Usage:
    python3 diamond-fuzz/scripts/gen_sedga_targets.py [--clean]
"""

import argparse
import itertools
import logging
import shutil
import sys
from pathlib import Path

FUZZ_DIR = Path(__file__).resolve().parents[1]      # <repo>/diamond-fuzz
ROOT = FUZZ_DIR.parent                              # pluribus repo root
TARGETS_DIR = FUZZ_DIR / "targets"
LOG_DIR = ROOT / "tmp" / "logs"

# Device list.  "BG256" is Diamond's spelling of the CABGA256 package; the
# full part string form (LFE5U-<density>-<speed>BG<pins><temp>) was
# established empirically by asking Diamond to open a project for each
# candidate -- the installed .ptd part tables are obfuscated and the
# grep-able strings under data/ list only placeholder XX speed grades.
#
# LFE5U-12F-8BG256C is EXACTLY the Cynthion r1.4 part, and Diamond accepts
# it, so the primary sweep runs on the real target device -- no
# extrapolation from a neighbouring part is required.
#
# The 25F/45F/85F are swept alongside so that device-independence of the
# encoding is TESTED rather than assumed: if the SED bits land at identical
# frame/bit offsets on all four densities, the encoding is family-wide.
DEVICES = {
    "12f": ("LFE5U-12F-8BG256C", "CABGA256"),   # Cynthion r1.4
    "25f": ("LFE5U-25F-8BG256C", "CABGA256"),
    "45f": ("LFE5U-45F-8BG256C", "CABGA256"),
    "85f": ("LFE5U-85F-8BG381C", "CABGA381"),   # 85F has no BG256
}

# Full legal parameter space per Diamond's own SEDGA.v.
CLK_FREQS = ["2.4", "4.8", "9.7", "19.4", "38.8", "77.5", "155.0"]
CHECKALWAYS = ["DISABLED", "ENABLED"]

# DEV_DENSITY is NOT free: Diamond's map stage rejects any value that does
# not match the device --
#   ERROR - map: The DEV_DENSITY value of <X> on SED component '<inst>'
#           should be consistent with the device '<dev>' used.
# probe_sedga_density.py swept all 4 devices x 8 density spellings (32
# builds) and found exactly ONE accepted value per device, and that the
# "...KUM" spellings used throughout SEDGA.v's own comments and default
# (DEV_DENSITY = "85KUM") are rejected by map for every device.  The
# simulation model and the mapper disagree; the mapper wins.
#
#   12F -> 12KU    25F -> 25KU    45F -> 45KU    85F -> 85KU
#
# So DEV_DENSITY is a function of the device rather than a swept axis; it
# is pinned per device below.  Recorded as a finding in its own right.
DEV_DENSITY_FOR = {
    "12f": "12KU",
    "25f": "25KU",
    "45f": "45KU",
    "85f": "85KU",
}

# Input tie-off variants.  "pins" drives every SEDGA input from a real pad;
# the constant variants tie inputs to fixed levels.  Constant tie-offs are
# the case most likely to make Diamond fold or re-encode the block, which is
# exactly why they are swept rather than avoided.
TIEOFFS = {
    "pins":  None,                     # all inputs from pads
    "en1":   ("1'b1", "1'b0", "1'b0"),  # SEDENABLE tied high
    "en0":   ("1'b0", "1'b0", "1'b0"),  # everything tied low
    "start": ("1'b1", "1'b1", "1'b0"),  # enable+start high
    "frcerr": ("1'b1", "1'b0", "1'b1"), # enable high, force-error high
}


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("gen_sedga")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "gen_sedga_targets.log", mode="w")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    return log


VERILOG_BASELINE = """\
// Baseline: no SEDGA instance.  Reference for all SED bit diffs.
module fuzz (
    input  wire clk,
    input  wire d0,
    output wire out0
);

reg out0_r;
always @(posedge clk) out0_r <= d0;
assign out0 = out0_r;

endmodule
"""


def sedga_verilog(clk_freq: str, checkalways: str, density: str,
                  tie: tuple[str, str, str] | None) -> tuple[str, list[str]]:
    """Return (verilog_source, port_list) for one SEDGA variant.

    Every SEDGA output is registered out to a pad so nothing is optimised
    away.  Inputs either come from pads or are tied to constants depending
    on the tie-off variant under test.
    """
    if tie is None:
        in_ports = ["sedenable", "sedstart", "sedfrcerr"]
        decls = "".join(f"    input  wire {p},\n" for p in in_ports)
        conn_en, conn_st, conn_fe = in_ports
    else:
        in_ports = []
        decls = ""
        conn_en, conn_st, conn_fe = tie

    ports = ["clk", "d0"] + in_ports + [
        "sedclkout", "seddone", "sedinprog", "sederr", "out0"]

    src = f"""\
// SEDGA: SED_CLK_FREQ={clk_freq} CHECKALWAYS={checkalways} DEV_DENSITY={density}
module fuzz (
    input  wire clk,
    input  wire d0,
{decls}    output wire sedclkout,
    output wire seddone,
    output wire sedinprog,
    output wire sederr,
    output wire out0
);

SEDGA #(
    .SED_CLK_FREQ("{clk_freq}"),
    .CHECKALWAYS("{checkalways}"),
    .DEV_DENSITY("{density}")
) u_sedga (
    .SEDENABLE ({conn_en}),
    .SEDSTART  ({conn_st}),
    .SEDFRCERR ({conn_fe}),
    .SEDCLKOUT (sedclkout),
    .SEDDONE   (seddone),
    .SEDINPROG (sedinprog),
    .SEDERR    (sederr)
);

reg out0_r;
always @(posedge clk) out0_r <= d0;
assign out0 = out0_r;

endmodule
"""
    return src, ports


def make_lpf(ports: list[str]) -> str:
    """LPF with IO standards but no LOCATE.

    Pin sites are deliberately left to Diamond.  SEDGA sits in the EFB
    config tiles and its bits do not depend on where the harness IO lands,
    so pinning would only risk package-specific PAR failures across the
    three devices swept here.
    """
    lines = ["BLOCK RESETPATHS;", "BLOCK ASYNCPATHS;", ""]
    for port in ports:
        lines.append(f'IOBUF PORT "{port}" IO_TYPE=LVCMOS33;')
    lines.append("")
    lines.append('FREQUENCY PORT "clk" 50.000000 MHz;')
    return "\n".join(lines) + "\n"


LDF = """\
<?xml version="1.0" encoding="UTF-8"?>
<BaliProject version="3.2" title="fuzz" device="{device}" default_implementation="impl1">
    <Options/>
    <Implementation title="impl1" dir="impl1" description="impl1" synthesis="lse" default_strategy="Strategy1">
        <Options/>
        <Source name="fuzz.v" type="Verilog" type_short="Verilog"><Options/></Source>
        <Source name="fuzz.lpf" type="Logic Preference" type_short="LPF"><Options/></Source>
    </Implementation>
    <Strategy name="Strategy1" file="../../aw21.sty"/>
</BaliProject>
"""

RUN_TCL = """\
prj_project open "[file normalize [file join [file dirname [info script]] fuzz.ldf]]"
prj_run PAR    -impl impl1
prj_run Export -impl impl1 -task Bitgen
prj_project close
"""


def write_target(name: str, device: str, verilog: str, ports: list[str],
                 log: logging.Logger) -> None:
    d = TARGETS_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "fuzz.v").write_text(verilog)
    (d / "fuzz.lpf").write_text(make_lpf(ports))
    (d / "fuzz.ldf").write_text(LDF.format(device=device))
    (d / "run.tcl").write_text(RUN_TCL)
    log.debug("wrote %s (%s)", name, device)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", action="store_true",
                    help="remove existing sedga_* targets first")
    ap.add_argument("--devices", default=None,
                    help="comma-separated subset of %s" % ",".join(DEVICES))
    args = ap.parse_args()

    log = setup_logging()

    if args.clean:
        for d in sorted(TARGETS_DIR.glob("sedga_*")):
            shutil.rmtree(d)
        log.info("cleaned existing sedga_* targets")

    devices = DEVICES
    if args.devices:
        want = {d.strip() for d in args.devices.split(",")}
        devices = {k: v for k, v in DEVICES.items() if k in want}
        if not devices:
            sys.exit(f"no devices matched {args.devices!r}")

    TARGETS_DIR.mkdir(parents=True, exist_ok=True)
    count = 0

    for tag, (device, _pkg) in devices.items():
        density = DEV_DENSITY_FOR[tag]

        # Baseline with no SEDGA at all -- the diff reference.
        write_target(f"sedga_{tag}_baseline", device,
                     VERILOG_BASELINE, ["clk", "d0", "out0"], log)
        count += 1

        # Full cross-product.  No pruning.
        for freq, ca, tie_name in itertools.product(
                CLK_FREQS, CHECKALWAYS, TIEOFFS):
            src, ports = sedga_verilog(freq, ca, density, TIEOFFS[tie_name])
            safe_f = freq.replace(".", "p")
            name = (f"sedga_{tag}_f{safe_f}_ca{ca[:3].lower()}"
                    f"_d{density.lower()}_{tie_name}")
            write_target(name, device, src, ports, log)
            count += 1

    per_dev = len(CLK_FREQS) * len(CHECKALWAYS) * len(TIEOFFS)
    log.info("cross-product per device: %d freq x %d checkalways x %d tie-off "
             "= %d (DEV_DENSITY pinned per device by Diamond's map rule)",
             len(CLK_FREQS), len(CHECKALWAYS), len(TIEOFFS), per_dev)
    log.info("generated %d SEDGA targets across %d device(s) under %s",
             count, len(devices), TARGETS_DIR)
    log.info("build with: python3 diamond-fuzz/scripts/run_all_fuzz.py "
             "--targets 'sedga_*' --jobs 4 --no-pluribus")


if __name__ == "__main__":
    main()
