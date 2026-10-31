"""Cyclone IV GX (EP4CGX150) embedded multiplier (MAC / MUL block) instances and control bits (#169).  Vendor groups + specimen-confirmed.

- Instance: MAC index = column rank * 90 + (Y - 1); column rank = ascending X among the MUL columns of the fitter geometry file.
- Control bits observed by pair builds (gxhb_macp{a,b}_*, one feature per pair, two MAC columns): see docs/altera/cycloneIV/cycloneiv-clean-hardblocks.md.
"""
import json

from . import fields as F
from .m9k import GEOM

MAC = 41                         # source: ASMDB_ARCH_GROUP_BLOCK_TYPE MAC (fields.PLACED)


def columns():
    kind = json.load(open(GEOM))["col_kind"]
    return sorted(int(x) for x, k in kind.items() if k == "MUL")


def instance(x, y):
    return columns().index(x) * F.ROWS_PER_COLUMN + (y - 1)


# source: ASM_MAC_*::process_end_of_phase libcomp_asmmac (static decompile, function@vaddr); value written per MAC model via mux_select
WRITERS = {
    "MAC_IREG_SIGN": ("ASM_MAC_IREG_SIGN::process_end_of_phase@0x2ded6", "signal_reg_stats(signal 4)[0] bit 3 (input-register flag)"),
    "MAC_PREG_SIGN": ("ASM_MAC_PREG_SIGN::process_end_of_phase@0x2e4ee", "signal_reg_stats(signal 4)[0] bit 4 (pipeline-register flag)"),
    "MAC_OREG_SHFTR": ("ASM_MAC_OREG_SHFTR::process_end_of_phase@0x2ed7e", "signal_reg_stats(signal 0xf)[0] bit 5 (output-register flag)"),
    "MAC_IREG_SMODE": ("ASM_MAC_IREG_SMODE::process_end_of_phase@0x501b0", "signal_reg_stats(signal 6)[0] bit 3, per MAC model"),
    "MAC_USAGE_MODE": ("ASM_MAC_USAGE_MODE::process_end_of_phase@0x50d56", "model vtbl+0x70(port) = mode of the MAC, port = 2 * half index (0 when the atom has no half)"),
    "MAC_PIA_TO_CLK": ("ASM_MAC_PIA_TO_CLK::process_end_of_phase@0x55e98", "value = RE index of the clock source (RE type 0xbf LAB line); BLK_CLK_BUF / dedicated types write nothing"),
    "MAC_CLK_INVERT": ("ASM_MAC_CLK_INVERT::process_end_of_phase@0x579e0", "port stats of signal 2 (clock) inversion flag"),
}
