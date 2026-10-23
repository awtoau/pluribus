#!/usr/bin/env python3
"""Real Quartus compiles targeting the option-RAM (ORAM) `o OPTION value`
anomalies flagged comparing DJI's real air-side m1900 sample against the
known-good ground-side m2001 sample (both confirmed e50f/5CEFA4U19I7-class,
awto-dji#3): m1900 alone shows EXTERNAL_CLK_SPI=-1 (m2001: 12), OPT_A/OPT_B
differ, JTAG_ID=fffffffd (one bit off mistral's ffffffff RAM-default), and
IOCSR_READY_FROM_CSR_DONE_EN=0.

Question: is m1900's ORAM pattern reachable by real Quartus output at all
(supports "genuine build, decode pipeline is wrong elsewhere"), or is it
unreachable (supports "wrong die/misdecoded")?  Reasoning from the two
samples alone (done earlier this session) proved nothing -- this generates
real compiles and compares.

VERDICT (after ~20 real compiles, see tmp/cyclonev_option_ram_probe/results.json):
no variant tried reproduces m1900's exact pattern (best: 1/12-13 fields
match, every variant except "default"-adjacent ones). But the single most
diagnostic anomaly -- JTAG_ID=fffffffd, one bit off mistral's ffffffff
RAM-default -- turns out NOT to need an explicit override at all: a bare
DEFAULT Quartus compile with zero option assignments already produces a
non-default, checksum-derived JTAG_ID (e.g. 004dd620) because
USE_CHECKSUM_AS_USERCODE is On by default for every Cyclone V build
(assignment_defaults.qdf). So JTAG_ID being non-default is NOT itself
anomalous -- it is what every real build does. What IS unexplained: getting
the SPECIFIC value fffffffd (one bit off all-1s) requires either a wildly
coincidental checksum collision, or an explicit JTAG_USER_CODE override --
and this investigation could NOT get an explicit JTAG_USER_CODE override to
reach the decoded ORAM field at all (see JTAG_ID rows below). Net effect:
this narrows, but does not resolve, the original question -- it rules out
"non-default JTAG_ID proves something's wrong" (false: expected on every
build) while leaving "why THIS specific value" and five other fields
(CRC_DIVIDE_ORDER/CVPCIE_MODE/DRIVE_STRENGTH/IDCODE/START_UP_CLOCK, all
non-default in BOTH real samples but in NONE of this script's compiles)
unexplained by anything tried here.

QSF assignment names verified by direct Tcl probe against quartus_sh
(`set_global_assignment`; REJECT means "Illegal assignment", not a design
failure) before use here -- see tmp/logs/cyclonev_option_ram_probe.log for
the accept/reject record. Mapping used:

  ORAM option                      QSF assignment                  verified
  --------------------------------------------------------------------------
  COMPRESSION_DIS                  quartus_cpf -o bitstream_compression=on
                                    (not a QSF assignment -- set at the .sof
                                    ->.rbf conversion step, same as
                                    cyclonev_die_probe.py)                yes
  EXTERNAL_CLK_SPI                 CONFIGURATION_CLOCK_FREQUENCY         NO --
                                    accepted by quartus_sh (arbitrary int
                                    2/12/25/50/100, matching the doc'd
                                    12/25/50/100 choice set) but confirmed by
                                    real compile NOT to move the ORAM field:
                                    ext_clk_12/25/50/100 all produced NO
                                    `o EXTERNAL_CLK_SPI` line at all (stayed
                                    at mistral's own default for every
                                    value). Like JTAG_USER_CODE, likely
                                    controls a different artifact (maybe only
                                    relevant to Active Serial programming
                                    files, not a bare quartus_cpf -c .rbf).
                                    CONCRETE LIMITATION, not silently
                                    skipped.
  JTAG_ID usercode-vs-checksum     USE_CHECKSUM_AS_USERCODE              yes (default
                                    On in assignment_defaults.qdf/_pro.qdf --
                                    *every* real Quartus build computes a
                                    checksum-derived JTAG_ID by default,
                                    confirmed empirically below: a bare
                                    default compile with NO option
                                    assignments at all already produces
                                    JTAG_ID=004dd620, never ffffffff. Setting
                                    it Off DOES make the ORAM JTAG_ID field
                                    vanish back to mistral's ffffffff
                                    default -- Off is a real, working knob.)
  JTAG_ID explicit fixed value     JTAG_USER_CODE                        NO --
                                    accepted by quartus_sh as a legal
                                    assignment (confirmed), and setting it
                                    DOES change .sof/.rbf bytes (confirmed:
                                    cmp -l shows 24 differing bytes vs a
                                    build without it), but the decoded ORAM
                                    `o JTAG_ID` line is UNCHANGED by it in
                                    every form tried: bare hex
                                    (jtag_usercode_fixed), 0x-prefixed
                                    (jtag_usercode_fixed_0x), and decimal
                                    (jtag_usercode_fixed_dec) -- all three
                                    gave the SAME result as leaving
                                    USE_CHECKSUM_AS_USERCODE Off alone (field
                                    absent = mistral default ffffffff).
                                    JTAG_USER_CODE writes to a bitstream
                                    region other than the one mistral decodes
                                    as `o JTAG_ID` (most likely a separate
                                    IEEE1149.1 JTAG TAP USERCODE register
                                    location, not the ORAM copy). CONCRETE
                                    LIMITATION: no QSF path found in this
                                    investigation that makes mistral's
                                    decoded JTAG_ID show an arbitrary
                                    explicit value -- only "default
                                    (ffffffff)" or "design-content checksum"
                                    were ever observed.
  CRC_ERROR_DETECTION_EN           CRC_ERROR_CHECKING                    NO --
                                    accepted, had no effect in real compile
                                    (never appears in any variant's decode,
                                    including crc_error_checking_on/off)
  NCEO_DIS                         ENABLE_NCEO_OUTPUT                    yes --
                                    confirmed moves the ORAM bit
                                    (nceo_output_on -> NCEO_DIS 0)
  OCT_DONE_DIS                     ENABLE_OCT_DONE                       yes --
                                    confirmed (oct_done_on -> OCT_DONE_DIS 0)
  CVP_CONF_DONE_EN                 RELEASE_CLEARS_BEFORE_TRI_STATES       yes, but
                                    CROSS-MAPPED: this QSF name moved
                                    CVP_CONF_DONE_EN, not the
                                    RELEASE_CLEARS_BEFORE_TRISTATES_DIS field
                                    the name suggests (release_clears_on ->
                                    CVP_CONF_DONE_EN 0, no
                                    RELEASE_CLEARS_BEFORE_TRISTATES_DIS line
                                    at all). ENABLE_CVP_CONFDONE/
                                    USE_CVP_CONFDONE (tried separately) did
                                    NOT move CVP_CONF_DONE_EN.
  DEVICE_WIDE_RESET_EN             ENABLE_DEVICE_WIDE_RESET              NO --
                                    accepted, no observed effect
                                    (device_wide_reset_off decode identical
                                    to default)
  RETRY_CONFIG_ON_ERROR_EN         AUTO_RESTART_CONFIGURATION            yes --
                                    confirmed (auto_restart_config_off ->
                                    RETRY_CONFIG_ON_ERROR_EN 0)
  START_UP_CLOCK                   USER_START_UP_CLOCK                   NO --
                                    accepted (On/Off only, no direct numeric
                                    match to the doc'd 00-ff byte range
                                    anyway), no observed effect
                                    (user_startup_clock_on decode identical
                                    to default)
  IOCSR_READY_FROM_CSR_DONE_EN     NO QSF MATCH FOUND -- tried
                                    IOCSR_READY_FROM_CSR_DONE,
                                    IO_CSR_READY_FROM_CSR_DONE,
                                    CYCLONEV_IOCSR_READY_FROM_CSR_DONE,
                                    ENABLE_IOCSR -- all REJECTed by
                                    quartus_sh as illegal assignment names.
                                    Reported as a concrete limitation, not
                                    silently skipped.
  OPT_A / OPT_B                    NO QSF MATCH FOUND -- these are multi-bit
                                    Ram-type ORAM fields with mistral doc
                                    "TODO"; no candidate QSF name tried was
                                    accepted. Tracked as pass-through content
                                    (see probe results: both fields carry
                                    non-default bits even on a zero-option
                                    default compile, so they are NOT pure
                                    "chip option" fields -- likely checksum/
                                    CVP/other content-derived storage,
                                    consistent with their own "TODO"
                                    unknown-purpose status in mistral's docs).
  CRC_DIVIDE_ORDER / CVPCIE_MODE /
  DRIVE_STRENGTH / IDCODE /
  START_UP_CLOCK                   UNRESOLVED -- m2001 (the confirmed-good
                                    reference) shows ALL FIVE as non-default,
                                    but NONE of this script's compiles
                                    (minimal 4-line QSF, any variant) ever
                                    produced a non-default value for ANY of
                                    them. CRC_ERROR_CHECKING On/Off (the
                                    guessed QSF name) did not move
                                    CRC_ERROR_DETECTION_EN either. These five
                                    fields are evidently set by SOMETHING in
                                    DJI's real Quartus project configuration
                                    that a bare FAMILY/DEVICE/TOP_LEVEL/
                                    VERILOG_FILE QSF does not reproduce --
                                    not identified in this investigation
                                    (CVP_MODE is a legal assignment name,
                                    confirmed, but no value tried for it was
                                    accepted; not pursued further given time
                                    budget). m1900 and m2001 agree on all
                                    five of these fields' exact values,
                                    consistent with both using the same DJI
                                    Quartus project template/device settings
                                    page rather than per-chip tuning.

Device: 5CEFA4U19I7 (the real physically-marked m1900 part), cross-checked
against 5CEBA4U19C8 first (same e50f die family; confirmed byte-identical
decode of the real m1900.depack.bin against both parts, matching the
already-established cross-die finding this session).

Flow (same proven chain as cyclonev_die_probe.py / cyclonev_dsp_fuzz.py):
    quartus_map -> quartus_fit -> quartus_asm -> quartus_cpf -c [-o ...] (.rbf)
    -> mistral-cv decomp -> read `o OPTION value` lines

Usage:
    python3 scripts/cyclonev_option_ram_probe.py --sanity-check-dies
    python3 scripts/cyclonev_option_ram_probe.py --run all
    python3 scripts/cyclonev_option_ram_probe.py --run m1900_match_attempt
    python3 scripts/cyclonev_option_ram_probe.py --compare-real

Output:
    tmp/logs/cyclonev_option_ram_probe.log   -- full run log
    tmp/cyclonev_option_ram_probe/<variant>/ -- qsf/v/rbf/bt per variant
    tmp/cyclonev_option_ram_probe/results.json -- ORAM dump per variant (merged)
"""
import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

QUARTUS_BIN = Path(toolchain.quartus_bin())
MISTRAL_CV = Path(toolchain.mistral_cv())

DEVICE = "5CEFA4U19I7"       # real physically-marked m1900 part (this script's primary target)
DEVICE_CROSSCHECK = "5CEBA4U19C8"  # same e50f die family, already-established cross-die match
WORK_DIR = REPO / "tmp" / "cyclonev_option_ram_probe"
LOG_PATH = REPO / "tmp" / "logs" / "cyclonev_option_ram_probe.log"
RESULTS_PATH = WORK_DIR / "results.json"

# Real samples (read-only reference, awto-dji -- never modified).
M1900 = Path("/mnt/2tb/git/awto-dji/firmware/unpacked/P3X_m1900/m1900.depack.bin")
M1900_P3S = Path("/mnt/2tb/git/awto-dji/firmware/unpacked/P3S_FW_V01.01.0008/m1900_p3s.depack.bin")
M2001 = Path("/mnt/2tb/git/awto-dji/firmware/unpacked/C1_FW_V01.06.0000/m2001.depack.bin")

# Overall limits = 3x the measured worst case of a one-pin/few-LE design on
# this host (quartus_fit ~10s, quartus_asm ~5s, quartus_map ~5s, cpf <1s,
# mistral-cv decomp of a small design ~2s; of the real 2MB m1900/m2001
# samples ~40s -- see tmp/logs/cyclonev_option_ram_probe.log for this run's
# actual timings). Expiry is logged with the limit and the command.
TIMEOUT_QUARTUS_FAST = 60
TIMEOUT_QUARTUS_FIT = 120
TIMEOUT_MISTRAL_SMALL = 30
TIMEOUT_MISTRAL_REAL = 180

OPT_LINE_RE = re.compile(r"^o (\S+) (\S+)\s*$")


def setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cyclonev_option_ram_probe")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_PATH)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def run(cmd, cwd, logger, timeout):
    logger.info("+ %s", " ".join(str(c) for c in cmd))
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error("TIMEOUT after %ds (limit): %s", timeout, " ".join(str(c) for c in cmd))
        return False, f"TIMEOUT after {timeout}s"
    text = res.stdout + res.stderr
    if res.returncode != 0:
        logger.error("FAILED rc=%d: %s\n%s", res.returncode, " ".join(str(c) for c in cmd), text[-2000:])
        return False, text
    return True, text


def read_opt_lines(bt: Path) -> dict:
    """{OPTION_NAME: value_string} for every non-default `o ` line."""
    out = {}
    with bt.open(errors="replace") as f:
        for line in f:
            m = OPT_LINE_RE.match(line.rstrip("\n"))
            if m:
                out[m.group(1)] = m.group(2)
    return out


def decode_rbf(model: str, rbf: Path, bt: Path, logger, timeout) -> dict:
    ok, txt = run([str(MISTRAL_CV), "decomp", model, str(rbf), str(bt)], rbf.parent, logger, timeout)
    if not bt.exists():
        return {"error": f"mistral-cv decomp produced no .bt ({txt[-500:]})"}
    return {"opt": read_opt_lines(bt)}


# ── part A: sanity check -- 5CEFA4U19I7 vs 5CEBA4U19C8 decode of the real
# samples must be byte-identical (apart from the `m <model>` header line),
# per the already-established cross-die finding this session. ──────────────

def sanity_check_dies(logger):
    results = {}
    for label, path in [("m1900", M1900), ("m1900_p3s", M1900_P3S), ("m2001", M2001)]:
        if not path.exists():
            logger.warning("%s: missing (%s), skipping", label, path)
            continue
        bts = {}
        for dev in (DEVICE, DEVICE_CROSSCHECK):
            bt = WORK_DIR / f"sanity_{label}_{dev}.bt"
            bt.parent.mkdir(parents=True, exist_ok=True)
            decode_rbf(dev, path, bt, logger, TIMEOUT_MISTRAL_REAL)
            bts[dev] = bt
        a = bts[DEVICE].read_bytes().split(b"\n", 1)[1] if bts[DEVICE].exists() else b""
        b = bts[DEVICE_CROSSCHECK].read_bytes().split(b"\n", 1)[1] if bts[DEVICE_CROSSCHECK].exists() else b""
        identical = (a == b) and a != b""
        logger.info("%s: %s vs %s body-identical = %s (len %d vs %d)",
                     label, DEVICE, DEVICE_CROSSCHECK, identical, len(a), len(b))
        results[label] = {"identical_body": identical, "len_a": len(a), "len_b": len(b)}
    return results


# ── part B: real sample ORAM dumps (reference) ──────────────────────────────

def dump_real_samples(logger):
    results = {}
    for label, path in [("m1900", M1900), ("m1900_p3s", M1900_P3S), ("m2001", M2001)]:
        if not path.exists():
            logger.warning("%s: missing (%s), skipping", label, path)
            continue
        bt = WORK_DIR / f"real_{label}.bt"
        bt.parent.mkdir(parents=True, exist_ok=True)
        r = decode_rbf(DEVICE, path, bt, logger, TIMEOUT_MISTRAL_REAL)
        logger.info("%s opt dump: %s", label, r.get("opt"))
        results[label] = r
    return results


# ── part C: synthetic variants -- vary QSF options + cpf flags, decode,
# extract `o ` lines, no design-correctness claim needed (these are "does
# this knob move this ORAM bit", not functional designs). ──────────────────

PROBE_VERILOG = """module probe(input clk, input rst, output reg q);
  always @(posedge clk or posedge rst)
    if (rst) q <= 1'b0;
    else q <= ~q;
endmodule
"""

# A slightly bigger design (counter + small RAM-like shift chain) for the
# "vary design scale too" requirement -- still trivial compared to m2001's
# real scale (a full SoC image), but exercises more LEs/registers than the
# single-FF PROBE_VERILOG, for the part-3 size variation.
MEDIUM_VERILOG = """module medium_design(input clk, input rst, input [7:0] d, output reg [31:0] acc,
  output reg [7:0] shr);
  integer i;
  always @(posedge clk or posedge rst)
    if (rst) begin
      acc <= 32'b0;
      shr <= 8'b0;
    end else begin
      acc <= acc + d;
      shr <= {shr[6:0], d[0]};
    end
endmodule
"""

# Each variant: qsf_lines (global assignments, no -to pin needed -- these
# are all chip-wide options) + cpf_extra (quartus_cpf -o args) + verilog.
# "default" has none -- baseline for comparison.
VARIANTS = {
    "default": {"qsf": [], "cpf": []},
    "compression_on": {"qsf": [], "cpf": ["bitstream_compression=on"]},
    "compression_off_explicit": {"qsf": ["set_global_assignment -name COMPRESSION_MODE Off"], "cpf": []},
    "ext_clk_12": {"qsf": ["set_global_assignment -name CONFIGURATION_CLOCK_FREQUENCY 12"], "cpf": []},
    "ext_clk_25": {"qsf": ["set_global_assignment -name CONFIGURATION_CLOCK_FREQUENCY 25"], "cpf": []},
    "ext_clk_50": {"qsf": ["set_global_assignment -name CONFIGURATION_CLOCK_FREQUENCY 50"], "cpf": []},
    "ext_clk_100": {"qsf": ["set_global_assignment -name CONFIGURATION_CLOCK_FREQUENCY 100"], "cpf": []},
    "jtag_usercode_off": {"qsf": ["set_global_assignment -name USE_CHECKSUM_AS_USERCODE Off"], "cpf": []},
    "jtag_usercode_fixed": {
        "qsf": [
            "set_global_assignment -name USE_CHECKSUM_AS_USERCODE Off",
            "set_global_assignment -name JTAG_USER_CODE FFFFFFFD",
        ],
        "cpf": [],
    },
    "crc_error_checking_on": {"qsf": ["set_global_assignment -name CRC_ERROR_CHECKING On"], "cpf": []},
    "crc_error_checking_off": {"qsf": ["set_global_assignment -name CRC_ERROR_CHECKING Off"], "cpf": []},
    "cvp_confdone_on": {"qsf": ["set_global_assignment -name ENABLE_CVP_CONFDONE On"], "cpf": []},
    "device_wide_reset_off": {"qsf": ["set_global_assignment -name ENABLE_DEVICE_WIDE_RESET Off"], "cpf": []},
    "nceo_output_on": {"qsf": ["set_global_assignment -name ENABLE_NCEO_OUTPUT On"], "cpf": []},
    "oct_done_on": {"qsf": ["set_global_assignment -name ENABLE_OCT_DONE On"], "cpf": []},
    "release_clears_on": {"qsf": ["set_global_assignment -name RELEASE_CLEARS_BEFORE_TRI_STATES On"], "cpf": []},
    "auto_restart_config_off": {"qsf": ["set_global_assignment -name AUTO_RESTART_CONFIGURATION Off"], "cpf": []},
    "user_startup_clock_on": {"qsf": ["set_global_assignment -name USER_START_UP_CLOCK On"], "cpf": []},
    # Combined attempt: every single-knob change that moved toward m1900's
    # real pattern, stacked together, to see how close a REAL compile gets.
    "m1900_match_attempt": {
        "qsf": [
            "set_global_assignment -name COMPRESSION_MODE Off",
            "set_global_assignment -name CONFIGURATION_CLOCK_FREQUENCY 2",
            "set_global_assignment -name USE_CHECKSUM_AS_USERCODE Off",
            "set_global_assignment -name JTAG_USER_CODE FFFFFFFD",
            "set_global_assignment -name CRC_ERROR_CHECKING On",
        ],
        "cpf": [],
    },
    "medium_default": {"qsf": [], "cpf": [], "verilog": "medium"},
    "medium_compression_on": {"qsf": [], "cpf": ["bitstream_compression=on"], "verilog": "medium"},
    # Follow-up: jtag_usercode_fixed changed .sof/.rbf bytes (confirmed by cmp)
    # but did NOT produce o JTAG_ID fffffffd in the decode -- try 0x-prefixed
    # hex and decimal forms in case Quartus parses the value differently.
    "jtag_usercode_fixed_0x": {
        "qsf": [
            "set_global_assignment -name USE_CHECKSUM_AS_USERCODE Off",
            "set_global_assignment -name JTAG_USER_CODE 0xFFFFFFFD",
        ],
        "cpf": [],
    },
    "jtag_usercode_fixed_dec": {
        "qsf": [
            "set_global_assignment -name USE_CHECKSUM_AS_USERCODE Off",
            "set_global_assignment -name JTAG_USER_CODE 4294967293",
        ],
        "cpf": [],
    },
}


def write_design(d: Path, top: str, qsf_lines: list, verilog: str):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{top}.v").write_text(verilog)
    lines = [
        'set_global_assignment -name FAMILY "Cyclone V"',
        f"set_global_assignment -name DEVICE {DEVICE}",
        f"set_global_assignment -name TOP_LEVEL_ENTITY {top}",
        f"set_global_assignment -name VERILOG_FILE {top}.v",
    ] + qsf_lines
    (d / f"{top}.qsf").write_text("\n".join(lines) + "\n")


def compile_variant(name: str, spec: dict, logger) -> dict:
    is_medium = spec.get("verilog") == "medium"
    top = "medium_design" if is_medium else "probe"
    verilog = MEDIUM_VERILOG if is_medium else PROBE_VERILOG
    d = WORK_DIR / name
    write_design(d, top, spec["qsf"], verilog)
    heavy_guard.wait_available(logger, name)
    logger.info("=== variant %s: qsf=%s cpf=%s ===", name, spec["qsf"], spec["cpf"])

    ok, txt = run([str(QUARTUS_BIN / "quartus_map"), top, "--family=Cyclone V",
                   f"--part={DEVICE}"], d, logger, TIMEOUT_QUARTUS_FAST)
    if not ok:
        return {"error": f"quartus_map failed: {txt[-500:]}"}
    ok, txt = run([str(QUARTUS_BIN / "quartus_fit"), top], d, logger, TIMEOUT_QUARTUS_FIT)
    if not ok:
        return {"error": f"quartus_fit rejected: {txt[-500:]}"}
    ok, txt = run([str(QUARTUS_BIN / "quartus_asm"), top], d, logger, TIMEOUT_QUARTUS_FAST)
    if not ok:
        return {"error": f"quartus_asm failed: {txt[-500:]}"}
    cpf_args = []
    for kv in spec["cpf"]:
        cpf_args += ["-o", kv]
    rbf = d / f"{top}.rbf"
    ok, txt = run([str(QUARTUS_BIN / "quartus_cpf"), "-c", *cpf_args, f"{top}.sof", f"{top}.rbf"],
                  d, logger, TIMEOUT_QUARTUS_FAST)
    if not ok:
        return {"error": f"quartus_cpf failed: {txt[-500:]}"}

    bt = d / f"{top}.bt"
    r = decode_rbf(DEVICE, rbf, bt, logger, TIMEOUT_MISTRAL_SMALL)
    return r


def merge_results(key: str, new: dict):
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    old = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
    old[key] = new
    RESULTS_PATH.write_text(json.dumps(old, indent=2, sort_keys=True))


REAL_M1900_OPT = {
    "COMPRESSION_DIS": "1", "CRC_DIVIDE_ORDER": "-1", "CRC_ERROR_DETECTION_EN": "1",
    "CVPCIE_MODE": "3", "DRIVE_STRENGTH": "3", "EXTERNAL_CLK_SPI": "-1", "IDCODE": "ff",
    "IOCSR_READY_FROM_CSR_DONE_EN": "0", "JTAG_ID": "fffffffd", "OPT_A": "fd89",
    "OPT_B": "fffffeff.ffffffff", "START_UP_CLOCK": "7f",
}


def compare_to_real(opt: dict) -> dict:
    """field-by-field match/mismatch of a variant's opt dump against the
    real m1900 pattern. Fields present in one but not the other count as
    mismatches too (absent = at mistral's own default for that field)."""
    all_fields = sorted(set(REAL_M1900_OPT) | set(opt))
    out = {}
    n_match = 0
    for f in all_fields:
        real_v = REAL_M1900_OPT.get(f, "(default)")
        got_v = opt.get(f, "(default)")
        match = real_v == got_v
        n_match += match
        out[f] = {"real": real_v, "got": got_v, "match": match}
    return {"fields": out, "n_match": n_match, "n_total": len(all_fields)}


def main():
    with heavy_guard.heavy_lock("cyclonev_option_ram_probe", heavy_guard.stdout_log()):
        _main()


def _main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sanity-check-dies", action="store_true",
                     help="decode real samples against both 5CEFA4U19I7 and 5CEBA4U19C8, confirm byte-identical")
    ap.add_argument("--dump-real", action="store_true", help="dump ORAM opt lines for the real m1900/m2001 samples")
    ap.add_argument("--run", nargs="*", default=[],
                     help="variant name(s) to compile, or 'all'")
    ap.add_argument("--compare-real", action="store_true",
                     help="print field-by-field comparison of every run variant against the real m1900 pattern")
    ap.add_argument("--list", action="store_true", help="list variant names")
    args = ap.parse_args()

    if args.list:
        for name in VARIANTS:
            print(name)
        return

    logger = setup_logging()
    logger.info("cyclonev_option_ram_probe: device=%s crosscheck=%s", DEVICE, DEVICE_CROSSCHECK)

    if args.sanity_check_dies:
        r = sanity_check_dies(logger)
        merge_results("sanity_check_dies", r)
        print(json.dumps(r, indent=2))

    if args.dump_real:
        r = dump_real_samples(logger)
        merge_results("real_samples", r)
        for label, rr in r.items():
            print(f"\n=== {label} ===")
            for k, v in sorted(rr.get("opt", {}).items()):
                print(f"  {k:36s} {v}")

    names = list(VARIANTS) if args.run == ["all"] else args.run
    for name in names:
        if name not in VARIANTS:
            logger.error("unknown variant %s (see --list)", name)
            continue
        r = compile_variant(name, VARIANTS[name], logger)
        merge_results(name, r)
        print(f"\n=== {name} ===")
        if "error" in r:
            print(f"  ERROR: {r['error']}")
        else:
            for k, v in sorted(r.get("opt", {}).items()):
                print(f"  {k:36s} {v}")

    if args.compare_real:
        old = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
        print(f"\n{'variant':28s} {'match':>7s}/{'total':<7s}  mismatched fields")
        for name, r in old.items():
            if name in ("sanity_check_dies", "real_samples") or "opt" not in r:
                continue
            cmp = compare_to_real(r["opt"])
            mism = [f for f, v in cmp["fields"].items() if not v["match"]]
            print(f"{name:28s} {cmp['n_match']:>7d}/{cmp['n_total']:<7d}  {mism}")

    print(f"\nresults: {RESULTS_PATH}")
    print(f"log: {LOG_PATH}")


if __name__ == "__main__":
    main()
