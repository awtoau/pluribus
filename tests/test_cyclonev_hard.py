"""Cyclone V hard-block decode rules (lifters/cyclonev_hard.py); no Quartus, no corpus files."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lifters"))
import cyclonev_hard as hard  # noqa: E402

ONES = "ff.ffffffff"


def test_m10k_address_pins_x40():
    assert hard.m10k_addr_pins(6, 40) == {b: b + 4 for b in range(6)}      # pins 4..9
    assert hard.m10k_addr_pins(9, 20) == {b: b + 3 for b in range(9)}      # pins 3..11


def test_m10k_dual_port_rule():
    pins = {("ADDRA", p): (f"a{p}", False) for p in range(4, 10)}
    pins |= {("ADDRB", p): (f"b{p}", False) for p in range(4, 10)}
    pins |= {("DATAAIN", 0): ("d0", False), ("DATAAOUT", 0): ("q0", True),
             ("WREN", 1): ("we", False), ("CLKIN", 6): ("clk", False)}
    rec = hard.m10k_cell(("M10K", 3, 4), {("B_DATA_WIDTH", None): "40"}, pins)
    assert rec["unmodelled"] is None
    assert rec["params"]["operation_mode"] == '"dual_port"'
    assert rec["params"]["port_a_address_width"] == 6
    assert rec["pins"]["portawe"] == ["we"] and rec["pins"]["clk0"] == ["clk"]
    assert rec["pins"]["portaaddr"][0] == "a4" and rec["outs"]["portbdataout"] == {0: "q0"}


def test_m10k_init_roundtrip_and_tied_rows():
    # word 0 of a x40, 6-address-bit block lives in row 192; stored inverted and permuted
    perm = hard._PERM
    word = 0b1011
    stored = 0
    for bit in range(40):
        stored |= ((word >> perm[bit]) & 1) << bit
    raw = (~stored) & ((1 << 40) - 1)
    kv = {("RAM", 192): f"{raw >> 32:02x}.{raw & 0xffffffff:08x}"}
    assert hard.m10k_init(kv, 6, 40) == word
    assert hard.m10k_init({("RAM", 0): ONES}, 6, 40) == 0


def test_mlab_contents_complement_address():
    perm = list(range(64))
    raw = (1 << 64) - 1 ^ (1 << 31)             # stored inverted: only raw bit 31 clear -> function bit 31 set
    w = {"out": "o", "rd": ["a"] * 5, "din": "d", "wa": ["w"] * 5, "clk": "c", "clk_inv": False,
         "we": "e", "we_inv": False}
    rec = hard.mlab_cell(("MLAB", 1, 1), 0, "T", raw, {}, w, perm)
    assert rec["init"] == 1                      # word v = f(31 - v): bit 31 lands on address 0


def test_fpll_decode_matches_quartus_defparams():
    kv = {("FPLL_ENABLE", None): "1", ("M_CNT_HI_DIV_SETTING", None): "06", ("M_CNT_LO_DIV_SETTING", None): "06",
          ("C5_COUT_EN", None): "1", ("DPRIO0_CNT_HI_DIV", 5): "02", ("DPRIO0_CNT_ODD_DIV_EVEN_DUTY_EN", 5): "1"}
    rec = hard.fpll_cell(("FPLL", 54, 37), kv)
    d = rec["decode"]
    assert (d["m"], d["n"], d["c"]) == (12, 2, {5: 3})      # 50 MHz * 12 / 2 / 3 = 100 MHz


def test_dsp_unknown_mode_is_reported():
    rec = hard.dsp_cell(("DSP", 1, 1), {("MODE", None): "M18X18P36"}, {})
    assert rec["unmodelled"] and "M18X18P36" in rec["unmodelled"]
