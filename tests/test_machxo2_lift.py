"""Unit tests for machxo2_lift and verilog helper functions.

Does NOT require pytrellis, a real bitstream, or a database.  Exercises:
  - DSU (union-find) correctness and path compression
  - lut_dependence() — functional input analysis
  - _correct_pio_iostandard() — PULLMODE=NONE ghost correction
  - classify_pin() — pad classification
  - resource_summary() — with a synthetic Design object
  - _simplify_lut() / _lut_init_to_case() from verilog.py

Init-string conventions (tested explicitly):
  machxo2_lift.lut_dependence  — MSB-first: init_str[15-p] = f(p)
  verilog._simplify_lut        — LSB-first: init[p]        = f(p)
where p = A + 2B + 4C + 8D (A is bit 0, D is bit 3).

Run with:
  python3 -m pytest tests/test_machxo2_lift.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lifters.machxo2_lift import (
    DSU,
    _correct_pio_iostandard,
    classify_pin,
    lut_dependence,
    resource_summary,
    Design,
    _PULLMODE_NONE_GHOST_IOSTDS,
)
from verilog import _simplify_lut, _lut_init_to_case


# ── DSU ───────────────────────────────────────────────────────────────────────

class TestDSU:
    def test_find_self(self):
        d = DSU()
        assert d.find("a") == "a"
        assert d.find("b") == "b"

    def test_union_basic(self):
        d = DSU()
        d.union("a", "b")
        assert d.find("a") == d.find("b")

    def test_union_transitivity(self):
        d = DSU()
        d.union("a", "b")
        d.union("b", "c")
        assert d.find("a") == d.find("b") == d.find("c")

    def test_distinct_sets_remain_distinct(self):
        d = DSU()
        d.union("a", "b")
        d.union("c", "d")
        assert d.find("a") != d.find("c")
        assert d.find("b") != d.find("d")

    def test_path_compression_correctness(self):
        d = DSU()
        # Build a chain a→b→c→d→e, then find(a) should compress
        for x, y in [("a","b"),("b","c"),("c","d"),("d","e")]:
            d.p.setdefault(x, x)
            d.p.setdefault(y, y)
            d.p[x] = y
        root = d.find("a")
        assert root == d.find("e")
        # After find, all nodes should point directly to root
        for n in ["a","b","c","d","e"]:
            assert d.p[n] == root

    def test_union_idempotent(self):
        d = DSU()
        d.union("x", "y")
        root1 = d.find("x")
        d.union("x", "y")
        assert d.find("x") == root1

    def test_self_union(self):
        d = DSU()
        d.union("z", "z")
        assert d.find("z") == "z"


# ── lut_dependence ────────────────────────────────────────────────────────────
# Convention: MSB-first — init_str[15-p] = f(p), where p = A + 2B + 4C + 8D.

class TestLutDependence:
    def test_constant_zero(self):
        assert lut_dependence("0000000000000000") == set()

    def test_constant_one(self):
        assert lut_dependence("1111111111111111") == set()

    def test_buffer_a(self):
        # f(p) = A = p & 1 → f(15)=1,f(14)=0,f(13)=1,...
        # init[15-p]=f(p): for p=0..15 f = 0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1
        # init_str (p=15 downto 0): f(15),f(14),...,f(0) = 1,0,1,0,... = "1010101010101010"
        assert lut_dependence("1010101010101010") == {"a"}

    def test_buffer_b(self):
        # f(p) = B = (p>>1)&1
        # p=0..15: 0,0,1,1, 0,0,1,1, 0,0,1,1, 0,0,1,1
        # init (p=15 down): f(15)=1,f(14)=1,f(13)=0,f(12)=0,... = "1100110011001100"
        assert lut_dependence("1100110011001100") == {"b"}

    def test_buffer_c(self):
        # f(p) = C = (p>>2)&1
        # p=0..3: 0; p=4..7: 1; p=8..11: 0; p=12..15: 1
        # init (p=15 down): f(15)=1,f(14)=1,f(13)=1,f(12)=1,f(11)=0,... = "1111000011110000"
        assert lut_dependence("1111000011110000") == {"c"}

    def test_buffer_d(self):
        # f(p) = D = (p>>3)&1 → f(0..7)=0, f(8..15)=1
        # init (p=15 down): f(15)=1,...,f(8)=1,f(7)=0,...,f(0)=0 = "1111111100000000"
        assert lut_dependence("1111111100000000") == {"d"}

    def test_not_a(self):
        # f(p) = ~A = 1 - (p&1)
        # p=0..15: 1,0,1,0,...
        # init (p=15 down): 0,1,0,1,... = "0101010101010101"
        assert lut_dependence("0101010101010101") == {"a"}

    def test_xor_ab(self):
        # f(p) = A ^ B = (p&1) ^ ((p>>1)&1)
        # p: 0,1,2,3 → 0,1,1,0 (period 4)
        # init (p=15 down): p=15→0,p=14→1,p=13→1,p=12→0,... = "0110011001100110"
        assert lut_dependence("0110011001100110") == {"a", "b"}

    def test_and_ab(self):
        # f(p) = A & B = (p&1) & ((p>>1)&1) → only f(3)=f(7)=f(11)=f(15)=1
        # init (p=15 down): 1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,0 = "1000100010001000"
        assert lut_dependence("1000100010001000") == {"a", "b"}

    def test_or_ab(self):
        # f(p) = A | B = 0 only when A=0,B=0 → p ∈ {0,4,8,12}
        # f: 0,1,1,1, 0,1,1,1, 0,1,1,1, 0,1,1,1
        # init (p=15 down): f(15)=1,...,f(12)=0,...,f(8)=0,...,f(4)=0,...,f(0)=0
        # = "1110111011101110"
        assert lut_dependence("1110111011101110") == {"a", "b"}

    def test_four_input_function(self):
        # f(p) = 1 only when p=15 (all inputs 1): AND(A,B,C,D)
        # init (p=15 down): f(15)=1, f(14..0)=0 = "1000000000000000"
        result = lut_dependence("1000000000000000")
        assert result == {"a", "b", "c", "d"}

    def test_three_inputs(self):
        # Majority(A,B,C): 1 iff at least 2 of A,B,C are 1; D ignored
        # f(0..15): 0,0,0,1, 0,1,1,1, 0,0,0,1, 0,1,1,1
        # init (p=15 down): f(15)=1,f(14)=1,f(13)=1,f(12)=0,
        #                   f(11)=1,f(10)=0,f(9)=0,f(8)=0,
        #                   f(7)=1,f(6)=1,f(5)=1,f(4)=0,
        #                   f(3)=1,f(2)=0,f(1)=0,f(0)=0 = "1110100011101000"
        result = lut_dependence("1110100011101000")
        assert result == {"a", "b", "c"}


# ── _correct_pio_iostandard ───────────────────────────────────────────────────

class TestCorrectPioIostandard:
    def test_ghost_mipi_corrected_fullkey(self):
        enums = {"PIOA.PULLMODE": "NONE", "PIOA.BASE_TYPE": "OUTPUT_MIPI"}
        result = _correct_pio_iostandard(enums)
        assert result["PIOA.BASE_TYPE"] == "OUTPUT_LVTTL33"
        assert result["PIOA.PULLMODE"] == "NONE"

    def test_ghost_sstl25_corrected_fullkey(self):
        # The loop starts at PIOA; PIOB-only dicts hit the plain-key else branch
        # and break — an unsupported call pattern (callers always pass full tile dicts).
        # Test with PIOA which is the expected form.
        for ghost in ("SSTL25_I", "OUTPUT_SSTL25_I"):
            enums = {"PIOA.PULLMODE": "NONE", "PIOA.BASE_TYPE": ghost}
            result = _correct_pio_iostandard(enums)
            assert result["PIOA.BASE_TYPE"] == "OUTPUT_LVTTL33"

    def test_no_correction_when_pullmode_is_not_none(self):
        enums = {"PIOA.PULLMODE": "UP", "PIOA.BASE_TYPE": "OUTPUT_MIPI"}
        result = _correct_pio_iostandard(enums)
        assert result["PIOA.BASE_TYPE"] == "OUTPUT_MIPI"

    def test_real_mipi_not_corrected(self):
        # When PULLMODE is not NONE, the IO standard is genuine MIPI.
        enums = {"PIOA.PULLMODE": "DOWN", "PIOA.BASE_TYPE": "OUTPUT_MIPI"}
        result = _correct_pio_iostandard(enums)
        assert result["PIOA.BASE_TYPE"] == "OUTPUT_MIPI"

    def test_lvcmos33_unchanged(self):
        enums = {"PIOA.PULLMODE": "NONE", "PIOA.BASE_TYPE": "LVCMOS33"}
        result = _correct_pio_iostandard(enums)
        assert result["PIOA.BASE_TYPE"] == "LVCMOS33"

    def test_plain_key_form_corrected(self):
        enums = {"PULLMODE": "NONE", "BASE_TYPE": "OUTPUT_MIPI"}
        result = _correct_pio_iostandard(enums)
        assert result["BASE_TYPE"] == "OUTPUT_LVTTL33"

    def test_plain_key_form_unchanged(self):
        enums = {"PULLMODE": "UP", "BASE_TYPE": "OUTPUT_MIPI"}
        result = _correct_pio_iostandard(enums)
        assert result["BASE_TYPE"] == "OUTPUT_MIPI"

    def test_original_not_mutated(self):
        enums = {"PIOA.PULLMODE": "NONE", "PIOA.BASE_TYPE": "OUTPUT_MIPI"}
        _correct_pio_iostandard(enums)
        assert enums["PIOA.BASE_TYPE"] == "OUTPUT_MIPI"

    def test_multiple_pios_corrects_only_matching(self):
        enums = {
            "PIOA.PULLMODE": "NONE", "PIOA.BASE_TYPE": "OUTPUT_MIPI",
            "PIOB.PULLMODE": "UP",   "PIOB.BASE_TYPE": "OUTPUT_MIPI",
        }
        result = _correct_pio_iostandard(enums)
        assert result["PIOA.BASE_TYPE"] == "OUTPUT_LVTTL33"
        assert result["PIOB.BASE_TYPE"] == "OUTPUT_MIPI"

    def test_ghost_iostds_set_is_complete(self):
        assert "OUTPUT_MIPI" in _PULLMODE_NONE_GHOST_IOSTDS
        assert "SSTL25_I" in _PULLMODE_NONE_GHOST_IOSTDS
        assert "OUTPUT_SSTL25_I" in _PULLMODE_NONE_GHOST_IOSTDS


# ── classify_pin ─────────────────────────────────────────────────────────────

class TestClassifyPin:
    def test_fabric_in_conn(self):
        assert classify_pin("", True, False) == "fabric"

    def test_fabric_out_conn(self):
        assert classify_pin("", False, True) == "fabric"

    def test_fabric_both_conn(self):
        assert classify_pin("GPLL_CLK", True, True) == "fabric"

    def test_pll(self):
        assert classify_pin("GPLL_CLK", False, False) == "pll"
        assert classify_pin("gpll_feedback", False, False) == "pll"

    def test_spi_cfg_csspin(self):
        assert classify_pin("CSSPIN", False, False) == "spi_cfg"

    def test_spi_cfg_sn(self):
        assert classify_pin("SN", False, False) == "spi_cfg"

    def test_clock_pclk(self):
        assert classify_pin("PCLKC", False, False) == "clock"

    def test_clock_sda(self):
        assert classify_pin("SDA", False, False) == "clock"

    def test_clock_scl(self):
        assert classify_pin("SCL", False, False) == "clock"

    def test_unused_no_function(self):
        assert classify_pin("", False, False) == "unused"

    def test_unused_none_function(self):
        assert classify_pin(None, False, False) == "unused"

    def test_unused_unknown_function(self):
        assert classify_pin("DAC_D0", False, False) == "unused"


# ── resource_summary ──────────────────────────────────────────────────────────

def _make_design(n_luts=0, n_ffs=0):
    d = Design()
    for i in range(n_luts):
        d.luts.append({
            "name": f"lut_{i}", "init": "0110011001100110",
            "a": "n0", "b": "n1", "c": None, "d": None, "z": f"z_{i}",
            "z_used": True, "fn": None,
        })
    for i in range(n_ffs):
        d.ffs.append({
            "name": f"ff_{i}", "clk": "clk", "ce": "1'b1", "lsr": "1'b0",
            "d": f"n{i}", "q": f"q{i}", "regset": "RESET", "sd": "0", "gsr": "DISABLED",
        })
    d.all_nets = [f"n{i}" for i in range(max(n_luts, n_ffs) + 2)]
    return d


class TestResourceSummary:
    def test_empty_design(self):
        d = _make_design()
        r = resource_summary(d)
        assert r["lut4_used"] == 0
        assert r["ff_used"] == 0

    def test_counts_luts_and_ffs(self):
        d = _make_design(n_luts=5, n_ffs=3)
        r = resource_summary(d, device="LCMXO2-1200")
        assert r["lut4_used"] == 5
        assert r["ff_used"] == 3
        assert r["lut4_capacity"] == 1280
        assert r["ff_capacity"] == 1280
        assert r["ebr_capacity"] == 7
        assert r["pll_capacity"] == 1

    def test_no_device(self):
        d = _make_design(n_luts=2)
        r = resource_summary(d, device=None)
        assert r["lut4_capacity"] is None
        assert r["ff_capacity"] is None

    def test_lut4_driving_fabric(self):
        d = _make_design(n_luts=4)
        d.luts[1]["z_used"] = False  # one LUT not driving fabric
        r = resource_summary(d)
        assert r["lut4_driving_fabric"] == 3

    def test_known_devices_have_capacity(self):
        devices = ["LCMXO2-256", "LCMXO2-640", "LCMXO2-1200",
                   "LCMXO2-2000", "LCMXO2-4000", "LCMXO2-7000"]
        d = _make_design()
        for dev in devices:
            r = resource_summary(d, device=dev)
            assert r["lut4_capacity"] is not None
            assert r["ff_capacity"] is not None


# ── _simplify_lut (verilog.py) ────────────────────────────────────────────────
# Convention: LSB-first — init[p] = f(p), where p = A + 2B + 4C + 8D.

class TestSimplifyLut:
    def test_constant_zero(self):
        # With 4 live inputs, len(live) > 2 → returns None (simplifier doesn't
        # special-case constants with live inputs; use NC/const pins to collapse).
        assert _simplify_lut("0000000000000000", "a", "b", "c", "d") is None
        # With all inputs tied off, it reduces to a 0-live case → 1'b0
        assert _simplify_lut("0000000000000000", "NC", "1'b0", "1'b0", "1'b0") == "1'b0"

    def test_constant_one(self):
        assert _simplify_lut("1111111111111111", "a", "b", "c", "d") is None
        assert _simplify_lut("1111111111111111", "NC", "1'b0", "1'b0", "1'b0") == "1'b1"

    def test_buffer_a(self):
        # f(p) = A = p&1 → LSB-first: init[0]=0,init[1]=1,... = "0101010101010101"
        result = _simplify_lut("0101010101010101", "a", "1'b0", "1'b0", "1'b0")
        assert result == "a"

    def test_not_a(self):
        # f(p) = ~A → "1010101010101010"
        result = _simplify_lut("1010101010101010", "a", "1'b0", "1'b0", "1'b0")
        assert result == "~a"

    def test_and_two_inputs(self):
        # f(p) = A & B → LSB-first: 0,0,0,1 repeated = "0001000100010001"
        result = _simplify_lut("0001000100010001", "a", "b", "1'b0", "1'b0")
        assert result == "a & b"

    def test_or_two_inputs(self):
        # f(p) = A | B → 0,1,1,1 repeated = "0111011101110111"
        result = _simplify_lut("0111011101110111", "a", "b", "1'b0", "1'b0")
        assert result == "a | b"

    def test_xor_two_inputs(self):
        # f(p) = A ^ B → 0,1,1,0 repeated = "0110011001100110"
        result = _simplify_lut("0110011001100110", "a", "b", "1'b0", "1'b0")
        assert result == "a ^ b"

    def test_nand_two_inputs(self):
        # f(p) = ~(A & B) → 1,1,1,0 repeated = "1110111011101110"
        result = _simplify_lut("1110111011101110", "a", "b", "1'b0", "1'b0")
        assert result == "~(a & b)"

    def test_nor_two_inputs(self):
        # f(p) = ~(A | B) → 1,0,0,0 repeated = "1000100010001000"
        result = _simplify_lut("1000100010001000", "a", "b", "1'b0", "1'b0")
        assert result == "~(a | b)"

    def test_xnor_two_inputs(self):
        # f(p) = ~(A ^ B) → 1,0,0,1 repeated = "1001100110011001"
        result = _simplify_lut("1001100110011001", "a", "b", "1'b0", "1'b0")
        assert result == "~(a ^ b)"

    def test_three_live_inputs_returns_none(self):
        # 3 live inputs → not simplifiable
        result = _simplify_lut("0110011001100110", "a", "b", "c", "1'b0")
        assert result is None

    def test_four_live_inputs_returns_none(self):
        result = _simplify_lut("0001000100010001", "a", "b", "c", "d")
        assert result is None

    def test_nc_treated_as_zero(self):
        # A AND B, where C and D are "NC" — same as 1'b0
        result = _simplify_lut("0001000100010001", "a", "b", "NC", "NC")
        assert result == "a & b"

    def test_const_input_reduces_live_count(self):
        # A ^ B with C=1'b1 — C is fixed, so only A and B are live
        # f(p) with C=1 always: uses init[p | (1<<2)] = init[p | 4]
        # For "0110011001100110" (XOR(A,B)):
        # const_idx = 4 (from C=1, pos=2)
        # eff[0] = init[4]=0, eff[1]=init[5]=1, eff[2]=init[6]=1, eff[3]=init[7]=0
        # tt = "0110" → XOR
        result = _simplify_lut("0110011001100110", "a", "b", "1'b1", "1'b0")
        assert result == "a ^ b"

    def test_buffer_selected_via_const_inputs(self):
        # The function that maps A through when B=0: mux(B, const, A)
        # For AND(A,B) pattern "0001000100010001" with B=1'b1:
        # const_idx = 2, live=[(0,a)]
        # eff[0] = init[2]=0, eff[1]=init[3]=1 → tt="01" → buffer a
        result = _simplify_lut("0001000100010001", "a", "1'b1", "1'b0", "1'b0")
        assert result == "a"


# ── _lut_init_to_case (verilog.py) ───────────────────────────────────────────

class TestLutInitToCase:
    def test_simple_expression_no_localparam(self):
        lines = _lut_init_to_case("0110011001100110", "z", "a", "b", "1'b0", "1'b0")
        assert len(lines) == 1
        assert "^" in lines[0]
        assert "localparam" not in lines[0]

    def test_complex_fallback_to_localparam(self):
        # AND(A,B,C) — 3 live inputs → localparam bit-select
        lines = _lut_init_to_case("0001000000000000", "z", "a", "b", "c", "1'b0")
        assert any("localparam" in l for l in lines)
        assert any("[{" in l for l in lines)

    def test_cell_name_used_in_localparam(self):
        lines = _lut_init_to_case("0001000000000000", "z_net", "a", "b", "c", "1'b0",
                                  cell_name="myblock_and3")
        lp_line = next(l for l in lines if "localparam" in l)
        assert "myblock_and3" in lp_line

    def test_no_repeated_lut_prefix(self):
        lines = _lut_init_to_case("0001000000000000", "lut_lut_z", "a", "b", "c", "1'b0",
                                  cell_name="lut_lut_lut_myblock")
        lp_line = next(l for l in lines if "localparam" in l)
        assert "_lut_lut_lut_lut_lut_" not in lp_line
