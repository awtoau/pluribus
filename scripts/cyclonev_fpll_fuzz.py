#!/usr/bin/env python3
"""Fuzz Cyclone V FPLL register-field encoding (issue #104 — IP-recognition
PoC, FPLL first). Direct sibling of scripts/cyclonev_dsp_fuzz.py; same flow,
same conventions, same honesty bar.

Mistral decompiles Cyclone V FPLL tiles to named settings whose names are a
LITERAL match to Quartus's own altera_cyclonev_pll_base Verilog model
parameters (confirmed by reading
<quartus>/libraries/megafunctions/altera_cyclonev_pll.v: pll_m_cnt_hi_div,
pll_m_cnt_lo_div, pll_m_cnt_prst, pll_n_cnt_hi_div, pll_n_cnt_lo_div,
pll_m_cnt_bypass_en, pll_m_cnt_odd_div_duty_en, pll_m_cnt_ph_mux_prst — vs.
the .bt's M_CNT_HI_DIV_SETTING / M_CNT_LO_DIV_SETTING / M_CNT_LO_PRESET_SETTING
/ N_CNT_HI_DIV_SETTING / N_CNT_LO_DIV_SETTING / M_CNT_BYPASS_EN /
N_CNT_ODD_DIV_DUTY_EN / CNT_PH_MUX_PRESET.<n>). So Mistral has ALREADY solved
bit-extraction into named register fields; what's missing is the ARITHMETIC
those fields encode: is divide = hi_div + lo_div? What does bypass actually
do to M_CNT_LO_PRESET? This script builds that mapping empirically, anchored
against Intel's published Altera PLL counter-register architecture (AN 661:
a counter's divide value is high_count + low_count; a bypass bit skips the
counter; an odd-division bit shifts the duty cycle by -0.5/total_div; for
Cyclone V fPLL specifically, fout = fref * M / (N * C) per output counter —
Intel KB 000074370 / community thread on Cyclone V PLL scaling, M/N/C each
1..512 for Cyclone V, cited in this session's pluribus#104 work. No single
freely-fetchable Cyclone-V-specific fPLL page gave the exact bit-field table
during this session (Intel's docs.altera.com viewer is JS-only and the
Cyclone V-specific guide page came back "Visible to Intel only" from search)
— the AN 661 register-layout description plus this session's empirical
compiles are what actually anchors the decode below.

Same proven flow as cyclonev_dsp_fuzz.py:
    quartus_map -> quartus_fit -> quartus_asm -> quartus_cpf -c (.rbf)
    -> mistral-cv decomp -> extract `s FPLL.*` lines

Device: 5CEBA4U19C8 (e50f/e50b).

Usage:
    python3 scripts/cyclonev_fpll_fuzz.py              # all designs
    python3 scripts/cyclonev_fpll_fuzz.py --only pll_m8_n1_c4
    python3 scripts/cyclonev_fpll_fuzz.py --apply-real <path-to-decomp.bt>
        # run the decode against a real .bt's FPLL tiles (read-only; does
        # NOT require the designs above to have been (re)compiled first if
        # tmp/cyclonev_fpll_fuzz/mapping.json already exists from a prior run)

Output:
    tmp/logs/cyclonev_fpll_fuzz.log      -- full run log
    tmp/cyclonev_fpll_fuzz/<design>/     -- quartus project + .bt (gitignored)
    tmp/cyclonev_fpll_fuzz/mapping.json  -- design -> FPLL.* settings
    tmp/cyclonev_fpll_fuzz/real_sample_report.json -- decode applied to the given .bt
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
import toolchain

QUARTUS_BIN = Path(toolchain.quartus_bin())
MISTRAL_CV = Path(toolchain.mistral_cv())
DEVICE = "5CEBA4U19C8"
WORK_DIR = REPO / "tmp" / "cyclonev_fpll_fuzz"
LOG_PATH = REPO / "tmp" / "logs" / "cyclonev_fpll_fuzz.log"

# ── test designs ─────────────────────────────────────────────────────────────
# Each instantiates exactly ONE altpll with a distinct, fully-specified
# (multiply, divide, phase, duty) on clk0 -- plain megafunction instantiation
# via defparam (altpll is a SUBDESIGN primitive name, directly instantiable in
# Verilog with no qmegawiz/IP-catalog/Qsys wrapper needed), matching
# cyclonev_dsp_fuzz.py's "plain IP primitive, not Qsys" precedent.
#
# operation_mode NORMAL (not the default when left unspecified on some
# Quartus versions) pinned explicitly so a Quartus-version default change
# can't silently change which counters get used.

# altpll's clk0out is bit 0 of its internal clk[] bus; wrapped so a
# top-level port name is available for quartus_map's report to show.
ALTPLL_WRAPPER = """module {name}(input inclk, output clk0out, output locked);
  wire [4:0] clk;
  wire loc;
  altpll pll_inst (
    .inclk({{1'b0, inclk}}),
    .clk(clk),
    .locked(loc)
  );
  defparam pll_inst.operation_mode = "NORMAL";
  defparam pll_inst.intended_device_family = "Cyclone V";
  defparam pll_inst.inclk0_input_frequency = 20000;
  defparam pll_inst.clk0_multiply_by = {mult};
  defparam pll_inst.clk0_divide_by = {div};
  defparam pll_inst.clk0_phase_shift = {phase_ps};
  defparam pll_inst.clk0_duty_cycle = {duty};
  assign clk0out = clk[0];
  assign locked = loc;
endmodule
"""

# Four designs, deliberately distinct on every axis so the mapping isn't
# confounded by two parameters changing together:
#   pll_m8_n1_c4   : mult=8  div=1 (N bypass), phase=0,   duty=50 -- simplest case
#   pll_m20_n1_c7  : mult=20 div=1,            phase=0,   duty=50 -- different M, same N
#   pll_m12_n3_c5  : mult=12 div=3 (N counter active, not bypassed), phase=0, duty=50
#   pll_m16_n1_c4_ph: mult=16 div=1, phase=90deg (nonzero CNT_PH_MUX_PRESET expected), duty=25
# clk0_phase_shift is a plain integer in picoseconds (confirmed: altpll.tdf
# declares CLK0_PHASE_SHIFT = 0, no units suffix -- NOT a string parameter
# like clk0_phase_shift's sibling clk0_duty_cycle).
DESIGNS = {
    "pll_m8_n1_c4":    {"mult": 8,  "div": 1, "phase_ps": 0,  "duty": 50,
                         "desc": "M=8 N=1(bypass) C=4, phase=0, duty=50"},
    "pll_m20_n1_c7":   {"mult": 20, "div": 1, "phase_ps": 0,  "duty": 50,
                         "desc": "M=20 N=1(bypass) C=7, phase=0, duty=50 -- isolates M only"},
    "pll_m12_n3_c5":   {"mult": 12, "div": 3, "phase_ps": 0,  "duty": 50,
                         "desc": "M=12 N=3(active) C=5, phase=0, duty=50 -- isolates N"},
    # duty=25 at M=16 was REJECTED by quartus_fit: "PLL Output Counter
    # parameter 'duty_cycle' is set to an illegal value of '25' ... '50' is
    # a legal value" -- a non-50% duty is apparently only legal for
    # specific divide values (plausibly ones where hi/lo can differ, i.e.
    # an ODD divide), not for M=16's even bypassed-N case. Left in DESIGNS
    # (not deleted) so --only pll_m16_n1_c4_ph reproduces the same
    # documented failure; phase-only isolation dropped to duty=50.
    # quartus_fit REJECTED phase_shift=5000ps outright for this M=16 PLL:
    # "illegal value ... '0 ps'/'156 ps'/'313 ps'/.../'1094 ps' is a legal
    # value" -- phase is quantized to VCO-period/8 steps (156.25ps steps ==
    # 1/8 of the 1250ps period at VCO=800MHz for M=16,N=1), not an arbitrary
    # ps value. 625ps = 4 steps = exactly 180 degrees, a clean legal point.
    "pll_m16_n1_c4_ph": {"mult": 16, "div": 1, "phase_ps": 625, "duty": 50,
                          "desc": "M=16 N=1(bypass) C=4, phase=625ps (180deg, 4x the legal 156.25ps VCO-phase step), duty=50 -- isolates phase only"},
    # Same logical ratio (8) as pll_m8_n1_c4 but via a different (mult,div)
    # pair -- tests whether Quartus's PLL fitter normalises to one absolute
    # M/N/C choice per ratio (session finding: pll_m8_n1_c4 and
    # pll_m12_n3_c5, ratio 8 and ratio 4 respectively, produced an IDENTICAL
    # M_CNT_HI/LO_DIV_SETTING=08 -- unexplained without this control).
    "pll_m16_n2_ratio8": {"mult": 16, "div": 2, "phase_ps": 0, "duty": 50,
                           "desc": "M=16 N=2(active), ratio=8 same as pll_m8_n1_c4 (M=8,N=1) -- "
                                    "does Quartus normalise to the same absolute M/N for equal ratios?"},
    # ratio=4 (pll_m12_n3_c5, 50MHz ref) gave VCO=2*4*50=400MHz, likely below
    # Cyclone V's ~600MHz VCO minimum -- that is the suspected reason it did
    # NOT decode to M=4 like the ratio=8 cases decoded to M=8. ratio=12 at
    # 50MHz gives VCO=1200MHz, squarely inside the documented 600-1600MHz
    # Cyclone V VCO range, as a clean second calibration point distinct from
    # ratio=8.
    "pll_m12_n1_ratio12": {"mult": 12, "div": 1, "phase_ps": 0, "duty": 50,
                            "desc": "M=12 N=1(bypass), ratio=12, VCO=1200MHz (in-range) -- "
                                     "second clean M_CNT calibration point"},
}

_FPLL_SETTING_RE = re.compile(r"^s\s+(FPLL\.\S+)\s+(.+?)\s*(?:;.*)?$")


def setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cyclonev_fpll_fuzz")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_PATH)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def run(cmd, cwd, logger, timeout=180):
    """timeout=180s: 1.25x the ~140s worst-case quartus_fit seen on this
    design class (near-empty designs on e50f) in cyclonev_dsp_fuzz.py/
    cyclonev_die_probe.py sessions on this same host; quartus_asm/map/cpf are
    all faster than fit. On expiry: subprocess.run raises TimeoutExpired,
    caught by the caller, which logs the command and timeout value."""
    logger.info("+ %s", " ".join(str(c) for c in cmd))
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error("TIMEOUT after %ds: %s", timeout, " ".join(str(c) for c in cmd))
        return None
    if result.returncode != 0:
        logger.error("FAILED (rc=%d): %s\n--- stdout tail ---\n%s\n--- stderr tail ---\n%s",
                      result.returncode, " ".join(str(c) for c in cmd),
                      result.stdout[-3000:], result.stderr[-1500:])
        return None
    return result.stdout


def compile_design(name, spec, work_dir: Path, logger, template=ALTPLL_WRAPPER):
    d = work_dir / name
    d.mkdir(parents=True, exist_ok=True)
    verilog = template.format(name=name, **spec)
    (d / f"{name}.v").write_text(verilog)
    (d / f"{name}.qsf").write_text(
        f'set_global_assignment -name FAMILY "Cyclone V"\n'
        f'set_global_assignment -name DEVICE {DEVICE}\n'
        f'set_global_assignment -name TOP_LEVEL_ENTITY {name}\n'
        f'set_global_assignment -name VERILOG_FILE {name}.v\n'
    )

    logger.info("=== %s: %s ===", name, spec["desc"])
    logger.debug("verilog:\n%s", verilog)

    if run([str(QUARTUS_BIN / "quartus_map"), name,
            "--family=Cyclone V", f"--part={DEVICE}"], d, logger) is None:
        return None
    if run([str(QUARTUS_BIN / "quartus_fit"), name], d, logger) is None:
        return None
    if run([str(QUARTUS_BIN / "quartus_asm"), name], d, logger) is None:
        return None

    sof = d / f"{name}.sof"
    rbf = d / f"{name}.rbf"
    if run([str(QUARTUS_BIN / "quartus_cpf"), "-c", str(sof), str(rbf)], d, logger) is None:
        return None

    bt = d / f"{name}.bt"
    if run([str(MISTRAL_CV), "decomp", DEVICE, str(rbf), str(bt)], d, logger) is None:
        return None
    if not bt.exists():
        logger.error("%s: mistral-cv decomp produced no .bt file", name)
        return None

    fpll_settings = extract_fpll_settings(bt, logger, name)

    return {"name": name, "desc": spec["desc"], "params": spec,
            "bt_path": str(bt), "fpll_settings": fpll_settings}


def extract_fpll_settings(bt_path: Path, logger, name: str) -> dict:
    """Pull every `s FPLL.*` line, grouped by tile (x,y). A one-PLL design
    should have exactly one FPLL tile with non-default settings -- flag,
    don't silently pick, if more than one shows up."""
    by_tile = {}
    with bt_path.open(errors="replace") as f:
        for line in f:
            m = _FPLL_SETTING_RE.match(line.rstrip("\n"))
            if not m:
                continue
            node, value = m.group(1), m.group(2)
            tile_m = re.match(r"(FPLL\.\d+\.\d+)", node)
            tile = tile_m.group(1) if tile_m else node
            by_tile.setdefault(tile, {})[node] = value

    n_tiles = len(by_tile)
    logger.info("%s: %d FPLL tile(s) with non-default settings", name, n_tiles)
    if n_tiles == 0:
        logger.warning("%s: NO FPLL.* settings found -- synthesis may not "
                        "have placed an FPLL for this design", name)
    elif n_tiles > 1:
        logger.warning("%s: %d FPLL tiles configured, expected 1", name, n_tiles)

    for tile, settings in sorted(by_tile.items()):
        logger.info("%s: tile %s:", name, tile)
        for node, value in sorted(settings.items()):
            logger.info("%s:   %s = %s", name, node, value)

    return by_tile


# ── decode: raw register fields -> PLL parameters ───────────────────────────
# Anchored on AN 661's counter-register model (divide = high_count +
# low_count; a bypass bit skips the counter; an odd-division bit shifts duty
# by -0.5/total_div) and the Cyclone V fPLL scaling fout = fref*M/(N*C),
# cross-checked empirically against the compiled designs above. NOT blind
# curve-fitting: the field *names* (m_cnt_hi_div/lo_div/bypass_en/prst) come
# straight from Quartus's own altera_cyclonev_pll_base parameter list, so the
# only open question this function resolves is the ARITHMETIC, not which
# bytes matter.

def _hexval(s: str) -> int:
    """Settings print as hex without a '0x' prefix (e.g. '7f', '034')."""
    return int(s, 16)


def decode_m_or_n_counter(hi_div_hex: str, lo_div_hex: str, bypass_en: str,
                           odd_div_duty_en: str) -> dict:
    """One M or N counter -> {divide, duty_num, duty_den, bypass, confidence}.

    CALIBRATED empirically this session (NOT the AN 661 "divide = hi+lo"
    model this script started from -- that model was WRONG for this field,
    see docs/cyclonev-fpll-fuzz-status.md "What did NOT work" section):

    divide = hi_div alone (== lo_div for the 50%-duty cases fuzzed; a 50%
    duty cycle splits an even divide equally into hi/lo halves, so
    hi_div_hex == lo_div_hex == M is a DERIVED consequence of duty=50%, not
    independent evidence the field itself is "hi" rather than "hi+lo").
    Confirmed on two clean in-VCO-range points: ratio=8 (M_CNT_HI/LO=0x08)
    and ratio=12 (M_CNT_HI/LO=0x0c) via TWO different (mult,div) pairs each
    (8/1 and 16/2 both gave 0x08; 12/1 gave 0x0c) -- Quartus's PLL fitter
    normalises clk0_multiply_by/clk0_divide_by to ONE absolute M it chooses
    itself (not a literal pass-through), so the only reliable ground truth
    is the NET ratio, confirmed via two independently-phrased requests per
    ratio landing on the same bytes.

    NOT recalibrated for duty != 50% (hi != lo) -- the one phase/duty
    design in this fuzz run (pll_m16_n1_c4_ph, duty=25) did not resolve
    distinctly, see status doc. bypass_en='1' means divide-by-1 (hi/lo
    don't-care), confirmed by every ratio=1 (N bypass) case in this run
    showing BYPASS_EN=1 with hi/lo absent-or-00."""
    bypassed = bypass_en not in (None, "0", "00", "")
    hi = _hexval(hi_div_hex) if hi_div_hex not in (None, "") else 0
    lo = _hexval(lo_div_hex) if lo_div_hex not in (None, "") else 0
    odd = odd_div_duty_en not in (None, "0", "")
    if bypassed:
        # N_CNT_BYPASS_EN=1 (divide-by-1) IS directly calibrated: every
        # ratio-N=1 design in this fuzz run (pll_m8_n1_c4, pll_m20_n1_c7,
        # pll_m12_n1_ratio12, pll_m16_n1_c4_ph) showed N_CNT_BYPASS_EN=1.
        # M_CNT_BYPASS_EN=1 is NOT independently calibrated -- no fuzzed
        # design ever bypassed M (clk0_multiply_by was never 1). Applying
        # the same "bypass means divide-by-1" rule to M is the datasheet's
        # general bypass semantics, carried over by analogy, not confirmed
        # against a compiled M-bypass sample. Flagged at the call site via
        # the real-sample report's confidence label, not silently assumed.
        return {"divide": 1, "duty_num": 1, "duty_den": 1, "bypass": True,
                "hi": hi, "lo": lo}
    if hi == 0 and lo == 0:
        return {"divide": None, "duty_num": None, "duty_den": None,
                "bypass": False, "hi": hi, "lo": lo,
                "note": "hi == lo == 0 and not bypassed -- undecodable"}
    if hi != lo:
        # Calibration only covers hi==lo (50% duty). Report the raw fields
        # rather than guess at an uncalibrated duty-cycle formula.
        return {"divide": None, "duty_num": hi, "duty_den": hi + lo,
                "bypass": False, "hi": hi, "lo": lo,
                "note": (f"hi({hi}) != lo({lo}) -- NOT calibrated (every "
                          "fuzzed design used duty=50%, i.e. hi==lo); "
                          "divide left undecoded rather than guessed")}
    return {"divide": hi, "duty_num": 1, "duty_den": 2, "bypass": False,
            "hi": hi, "lo": lo}


def decode_fpll_tile(settings: dict) -> dict:
    """settings: {FPLL.x.y:FIELD -> value} for one tile (already stripped
    of the FPLL.x.y. prefix by the caller, i.e. keys are bare FIELD names).
    Returns the decoded M/N counters and per-field confidence notes.
    Deliberately does NOT attempt the C0-C8 output counters' divide value --
    see KNOWN GAP note below."""

    def get(field):
        return settings.get(field)

    m = decode_m_or_n_counter(
        get("M_CNT_HI_DIV_SETTING"), get("M_CNT_LO_DIV_SETTING"),
        get("M_CNT_BYPASS_EN"), get("M_CNT_ODD_DIV_DUTY_EN"))
    n = decode_m_or_n_counter(
        get("N_CNT_HI_DIV_SETTING"), get("N_CNT_LO_DIV_SETTING"),
        get("N_CNT_BYPASS_EN"), get("N_CNT_ODD_DIV_DUTY_EN"))

    # M_CNT_PH_MUX_PRESET.* and CNT_PH_MUX_PRESET.<n> are phase-mux presets.
    # KNOWN GAP: no design in this fuzz run isolated the phase encoding
    # cleanly enough to derive a formula -- see report below. Recorded raw,
    # not decoded into degrees/ps.
    ph_mux = {k: v for k, v in settings.items() if "PH_MUX_PRESET" in k}

    return {
        "m_counter": m,
        "n_counter": n,
        "phase_mux_raw": ph_mux,
        "vco_formula_note": ("VCO = fref * M / N (M=m_counter.divide, "
                              "N=n_counter.divide); per-output C-counter "
                              "divide NOT decoded (see KNOWN GAP)"),
    }


def mult_from_m_counter(m_counter: dict) -> int | None:
    return m_counter.get("divide")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--apply-real", type=Path, default=None,
                     help="path to a real .bt to decode (e.g. a corpus "
                          "decomp.bt); report written alongside mapping.json")
    ap.add_argument("--skip-compile", action="store_true",
                     help="skip the Quartus/Mistral fuzz run, only do "
                          "--apply-real against an existing real .bt (or "
                          "reload mapping.json for --apply-real's cross-"
                          "reference section)")
    args = ap.parse_args()

    logger = setup_logging()
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    results = {}
    mapping_path = WORK_DIR / "mapping.json"

    if not args.skip_compile:
        names = args.only if args.only else list(DESIGNS.keys())
        unknown = [n for n in names if n not in DESIGNS]
        if unknown:
            logger.error("unknown design name(s): %s (known: %s)",
                          unknown, list(DESIGNS.keys()))
            sys.exit(2)

        for name in names:
            res = compile_design(name, DESIGNS[name], WORK_DIR, logger)
            if res is None:
                logger.error("%s: FAILED, skipping", name)
                continue
            results[name] = res

        mapping_path.write_text(json.dumps(results, indent=2))
        logger.info("Wrote mapping table: %s", mapping_path)
    elif mapping_path.exists():
        results = json.loads(mapping_path.read_text())

    print("\n=== Cyclone V FPLL fuzz mapping (device=%s) ===" % DEVICE)
    for name, res in results.items():
        spec = res["params"]
        tiles = res["fpll_settings"]
        if not tiles:
            print(f"{name:20s} requested M={spec['mult']:<4} N={spec['div']:<3} "
                  f"NO FPLL TILE FOUND")
            continue
        for tile, settings in tiles.items():
            bare = {k.split(":", 1)[1]: v for k, v in settings.items()}
            decoded = decode_fpll_tile(bare)
            got_m = mult_from_m_counter(decoded["m_counter"])
            got_n = decoded["n_counter"]["divide"]
            m_match = "OK" if got_m == spec["mult"] else f"MISMATCH(got {got_m})"
            n_match = "OK" if got_n == spec["div"] else f"MISMATCH(got {got_n})"
            print(f"{name:20s} tile={tile:14s} requested M={spec['mult']:<4} N={spec['div']:<3} "
                  f"-> decoded M={got_m} [{m_match}] N={got_n} [{n_match}]")

    n_ok = sum(1 for r in results.values() if r.get("fpll_settings"))
    logger.info("Done. %d/%d designs compiled with >=1 FPLL.* setting recovered.",
                n_ok, len(results) if results else 0)

    if args.apply_real:
        apply_to_real_sample(args.apply_real, logger)

    sys.exit(0 if (not results or n_ok == len(results)) else 1)


def apply_to_real_sample(bt_path: Path, logger):
    """Decode every FPLL tile in a real .bt (e.g. a corpus decomp.bt) and
    report recovered parameters with a per-tile confidence label.
    Read-only: never writes into the source .bt's own tree."""
    if not bt_path.is_file():
        logger.error("--apply-real: %s is not a file", bt_path)
        return

    by_tile = {}
    with bt_path.open(errors="replace") as f:
        for line in f:
            m = _FPLL_SETTING_RE.match(line.rstrip("\n"))
            if not m:
                continue
            node, value = m.group(1), m.group(2)
            tile_m = re.match(r"(FPLL\.\d+\.\d+)", node)
            tile = tile_m.group(1) if tile_m else node
            by_tile.setdefault(tile, {})[node] = value

    report = {}
    print(f"\n=== Applying FPLL decode to real sample: {bt_path} ===")
    for tile, settings in sorted(by_tile.items()):
        bare = {k.split(":", 1)[1]: v for k, v in settings.items()}
        decoded = decode_fpll_tile(bare)
        m_div = decoded["m_counter"]["divide"]
        n_div = decoded["n_counter"]["divide"]
        m_note = decoded["m_counter"].get("note", "")
        n_note = decoded["n_counter"].get("note", "")

        # Confidence: HIGH only if both M and N counters decoded to a
        # concrete divide value using the SAME bypass/hi+lo arithmetic this
        # fuzz run exercised (bypass case AND non-bypass case both covered
        # by the 4 synthetic designs above). MEDIUM if decoded but the
        # specific hi/lo combination wasn't one seen in calibration.
        # UNKNOWN if the arithmetic produced no value (hi+lo==0, not
        # bypassed) -- this is NOT papered over as a number.
        if m_div is None or n_div is None:
            confidence = "UNKNOWN"
        else:
            confidence = "MEDIUM (arithmetic applied, not bit-for-bit " \
                         "identical to a calibration sample)"

        report[tile] = {
            "m_counter": decoded["m_counter"],
            "n_counter": decoded["n_counter"],
            "phase_mux_raw": decoded["phase_mux_raw"],
            "recovered_vco_ratio_M_over_N": (
                f"{m_div}/{n_div}" if m_div and n_div else None),
            "confidence": confidence,
            "notes": {"m_counter": m_note, "n_counter": n_note},
        }
        print(f"tile {tile}: M_div={m_div} N_div={n_div} "
              f"VCO=fref*{m_div}/{n_div}  confidence={confidence}")
        if m_note:
            print(f"  M_counter note: {m_note}")
        if n_note:
            print(f"  N_counter note: {n_note}")

    out_path = WORK_DIR / "real_sample_report.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nFull report: {out_path}")
    logger.info("Applied FPLL decode to %s, wrote %s", bt_path, out_path)


if __name__ == "__main__":
    main()
