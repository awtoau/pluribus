"""Cyclone IV GX (EP4CGX150) M9K (MEAB) content map and control bits (#169).  Vendor groups + specimen-confirmed layouts.

- Instance: MEAB index = column rank * 90 + (Y - 1); column rank = ascending X among the M9K columns of the fitter geometry file.
- Content: arch group RAM_CONTENT_YGR_MEAB (calc, one mux of 9,216 bits).  Mux position p holds mem_init bit
  i = (p mod 256) * 36 + p div 256  (cycloneiv_ram_block mem_init0..4, linear LSB first, 9,216 bits = 8,192 data + 1,024 parity).
  Source: bincode specimens gxm9k_b18_k0..13 (9,216 of 9,216 positions), re-confirmed by gxm9k_hb*_k* for 9 widths.
- Logical (word, bit) -> mem_init index per port width (parity cells are the holes): see `index`.
"""
import json
import os

import numpy as np

from . import fields as F, plane as P

MEAB = 39                       # source: ASMDB_ARCH_GROUP_BLOCK_TYPE MEAB (fields.PLACED)
CONTENT_GROUP = "RAM_CONTENT_YGR_MEAB"      # source: libdb_asmdb arch-group-type table
CONTENT_BITS = 9216             # source: RAM_CONTENT mux length (asmdb walk) = 8192 data + 1024 parity
INDEX_PERIOD = 36               # source: gxm9k_b18 bincode decode: p = (i mod 36) * 256 + i div 36
INDEX_STRIDE = 256
GEOM = os.path.join(P.REPO, "lifters", "data", "cycloneiv_ep4cgx150_geom.json")   # source: fitter probe output (vendor tool)
# source: gxm9k_hb{W}_k* bincode builds, 9 widths, every logical bit located; widths with 8 data bits per parity cell
WIDTHS = (1, 2, 4, 8, 9, 16, 18, 32, 36)


def columns():
    """X coordinates of the M9K columns, ascending."""
    kind = json.load(open(GEOM))["col_kind"]
    return sorted(int(x) for x, k in kind.items() if k == "M9K")


def instance(x, y):
    return columns().index(x) * F.ROWS_PER_COLUMN + (y - 1)


def pos_of_index(i):
    """mem_init bit index -> RAM_CONTENT mux position."""
    i = np.asarray(i, np.int64)
    return (i % INDEX_PERIOD) * INDEX_STRIDE + i // INDEX_PERIOD


def index_of_pos(p):
    p = np.asarray(p, np.int64)
    return (p % INDEX_STRIDE) * INDEX_PERIOD + p // INDEX_STRIDE


def index(width, word, bit):
    """Logical RAM bit (word, bit) at port width `width` -> mem_init index (vectorised)."""
    word, bit = np.asarray(word, np.int64), np.asarray(bit, np.int64)
    lg = word * width + bit
    if width in (1, 2, 4, 8):
        return lg + lg // 8
    if width in (9, 18):
        return lg
    if width == 36:
        return (bit // 18) * 4608 + word * 18 + bit % 18
    if width == 16:
        return word * 18 + bit
    if width == 32:
        return np.where(bit < 14, word * 18 + bit, 4608 + word * 18 + bit - 14)
    raise ValueError(f"width {width} not measured")


# source: hl_rom_2 (x36 atom ROM, 128 x 32 MIF): every MIF bit (word w, bit b) sits at mem_init index 4608 + 36 * w + b (affine search over all 128 words, bits 0 / 1 / 17 / 18 / 31 exact),
#         i.e. a plain stride-36 layout with the unconnected address bit 7 high (words 128..255); the two-lane layout of `index` belongs to the two-x18 single-port x32 / x36 builds
ATOM36_STRIDE = 36


def read_words_atom36(bitvals):
    """bitvals[p] -> uint8 [256, 36] words of an explicit-mode-13 (x36 atom, simple dual port / ROM) block: index = word * 36 + bit."""
    bitvals = np.asarray(bitvals, np.uint8)
    i = np.arange(256)[:, None] * ATOM36_STRIDE + np.arange(ATOM36_STRIDE)[None, :]
    return bitvals[pos_of_index(i)]


def depth(width):
    return {1: 8192, 2: 4096, 4: 2048, 8: 1024, 9: 1024, 16: 512, 18: 512, 32: 256, 36: 256}[width]


def content_offsets(flds):
    f = next(f for f in flds if f.btype == MEAB and f.name == CONTENT_GROUP)
    return np.asarray(f.sites[0][0], np.int64)


def content_cells(base, offsets, tables):
    """plane cell id (r * 800 + j) * 8 + k for each mux position of one instance (base = hi * 6154 + lo)."""
    a = F.absolute(np.asarray([base], np.int64), offsets).ravel()
    r, j, k = P.sof_to_rbf(a, tables)
    return (r * 800 + j) * 8 + k


def read_words(bitvals, width):
    """bitvals[p] (p = mux position, 0/1) -> uint8 [depth, width] logical contents at port width `width`."""
    bitvals = np.asarray(bitvals, np.uint8)
    w = np.repeat(np.arange(depth(width)), width)
    b = np.tile(np.arange(width), depth(width))
    return bitvals[pos_of_index(index(width, w, b))].reshape(depth(width), width)


# source: ASMDB_SIMPLE_MUX::select libdb_asmdb@0x8c4ac + ASM_BITFIELD::silent_set_bits libcomp_asmcc@0x1a240: mux_select(value) writes bit i = (i == value), stored as written (no inversion)
SELECT_RULE = "one-hot"
# source: ASM_RAM_*::process_end_of_phase libcomp_asmram (static decompile, function@vaddr): value written per EAB by each writer
WRITERS = {
    "RAM_USAGE_MODE": ("ASM_RAM_USAGE_MODE::process_end_of_phase@0x1efc6", "port A flags: bit1 -> 0; else bit4 -> 1; else (flags & 0x40000008) or bit31 -> 2"),
    "RAM_USAGE_MODE_B": ("ASM_RAM_USAGE_MODE_B::process_end_of_phase@0x1f106", "same rule on port B flags"),
    "RAM_REG_DATA_OUT": ("ASM_RAM_REG_DATA_OUT::process_end_of_phase@0x7de60", "(port A flags >> 9) & 1 = RAM_REG_DATA_OUT flag (output registered); 1-bit mux, one-hot: value 1 clears the bit, value 0 sets it"),
    "RAM_NEW_DATA_MODE": ("ASM_RAM_NEW_DATA_MODE::process_end_of_phase@0x1f6fe", "1 iff (flags2 & 0x6000) and ((flags & 0x40000010) or (flags1 & 1))"),
    "RAM_IS_ROM_ONLY": ("ASM_RAM_IS_ROM_ONLY::process_end_of_phase@0x1fa72", "1 iff both ports are intrinsic ROM"),
    "RAM_DATA_WRITE_MODE": ("ASM_RAM_WRITE_OPTION::process_end_of_phase@0x1fd68", "flags2: 0x20000 branch; 0x8000 -> 3, 0x10000 -> 2, else 1; 0x40000 -> 2 (family 0x34 only)"),
    "RAM_MS_DATA_INPUT": ("ASM_RAM_MS_DATA_INPUT::process_end_of_phase@0x6663e", "value = RE line index of the port source, + PIA lines per EAB (+ extra lines) by RE type"),
}


# source: CDB_RAM_FLAG_ENUM name table libatm_astr astr_get_debug_string@0xd87034, pointer array @0x185b800 (89 entries, index = flag bit)
RAM_FLAGS = (
    "RAM_READ_DURING_WRITE",
    "RAM_READ_ONLY",
    "RAM_INITIALIZED",
    "RAM_DUAL_PORT",
    "RAM_SINGLE_PORT",
    "RAM_DATA_IN_CLEAR",
    "RAM_WRITE_ADDRESS_CLEAR",
    "RAM_WRITE_ENABLE_CLEAR",
    "RAM_REG_DATA_IN",
    "RAM_REG_DATA_OUT",
    "RAM_REG_WRITE_ADDRESS",
    "RAM_REG_READ_ADDRESS",
    "RAM_REG_WRITE_ENABLE",
    "RAM_REG_READ_ENABLE",
    "RAM_BY1",
    "RAM_BY2",
    "RAM_BY4",
    "RAM_BY8",
    "RAM_BY16",
    "RAM_REG_READ_ENABLE_CLEAR",
    "RAM_REG_READ_ADDRESS_CLEAR",
    "RAM_REG_DATA_OUT_CLEAR",
    "RAM_REG_DATA_OUT_SCLEAR",
    "RAM_READ_ENABLE_CLOCK",
    "RAM_READ_ENABLE_CLEAR",
    "RAM_READ_ADDRESS_CLOCK",
    "RAM_READ_ADDRESS_CLEAR",
    "RAM_DATA_OUT_CLOCK",
    "RAM_DATA_OUT_CLEAR",
    "RAM_DEEP_RAM",
    "RAM_BIDIR_DUAL_PORT",
    "RAM_QUAD_PORT",
    "RAM_PACKED",
    "RAM_READ_BY1",
    "RAM_READ_BY2",
    "RAM_READ_BY4",
    "RAM_READ_BY8",
    "RAM_READ_BY16",
    "RAM_READ_DEEP_RAM",
    "RAM_BY32",
    "RAM_BY9",
    "RAM_BY18",
    "RAM_BY36",
    "RAM_BY72",
    "RAM_BY144",
    "RAM_DATA_IN_CLOCK",
    "RAM_REG_DATA_IN_CLEAR",
    "RAM_WRITE_ENABLE_CLOCK",
    "RAM_REG_WRITE_ENABLE_CLEAR",
    "RAM_REG_BYTE_ENABLE",
    "RAM_BYTE_ENABLE_CLOCK",
    "RAM_REG_BYTE_ENABLE_CLEAR",
    "RAM_BYTE_ENABLE_CLEAR",
    "RAM_PACKED_FLIP_CLOCK",
    "RAM_PACKED_FLIP_CLEAR",
    "RAM_SINGLE_PORT_IMPLEMENTED_IN_SIMPLE_DUAL_PORT",
    "RAM_SAME_PORT_FEED_THROUGH_OLD",
    "RAM_SAME_PORT_FEED_THROUGH_DONT_CARE",
    "RAM_INPUT_REG_BYPASS_CE",
    "RAM_OUTPUT_REG_BYPASS_CE",
    "RAM_CLOCK0_PHYSICAL_PORT",
    "RAM_CLOCK1_PHYSICAL_PORT",
    "RAM_CLEAR_PHYSICAL_PORT",
    "RAM_SCLEAR_PHYSICAL_PORT",
    "RAM_CLEAR0_PHYSICAL_PORT",
    "RAM_CLEAR1_PHYSICAL_PORT",
    "RAM_POWER_UP_UNINITIALIZED",
    "RAM_INPUT_CE_ENA0",
    "RAM_INPUT_CE_ENA1",
    "RAM_INPUT_CE_ENA2",
    "RAM_INPUT_CE_ENA3",
    "RAM_CORE_CE_ENA0",
    "RAM_CORE_CE_ENA1",
    "RAM_CORE_CE_ENA2",
    "RAM_CORE_CE_ENA3",
    "RAM_OUTPUT_CE_ENA0",
    "RAM_OUTPUT_CE_ENA1",
    "RAM_SAME_PORT_FEED_THROUGH_NEW_NO_NBE_READ",
    "RAM_SAME_PORT_FEED_THROUGH_NEW_WITH_NBE_READ",
    "RAM_FAST_WRITE",
    "RAM_DELAY_WRITE",
    "RAM_READ_BEFORE_WRITE",
    "RAM_ENABLE_ECC",
    "RAM_REG_ECC",
    "RAM_NONE",
    "RAM_BY5",
    "RAM_BY10",
    "RAM_BY20",
    "RAM_BY40",
)


def flag_bits(*names):
    """Flag-name set -> integer mask over the 89 CDB_RAM_FLAG_ENUM bits (bit i = RAM_FLAGS[i])."""
    return sum(1 << RAM_FLAGS.index(n) for n in names)


def true_dual_port_value(flags):
    # source: ASM_RAM_USE_TRUE_DUAL_PORT_MODE::process_end_of_phase libcomp_asmram (readable export): 1 if RAM_BIDIR_DUAL_PORT else RAM_PACKED;
    #         forced to 1 when (RAM_READ_ONLY | RAM_SINGLE_PORT) is set and RAM_SINGLE_PORT_IMPLEMENTED_IN_SIMPLE_DUAL_PORT is clear (family / model condition assumed true)
    if flags >> RAM_FLAGS.index("RAM_BIDIR_DUAL_PORT") & 1:
        v = 1
    else:
        v = flags >> RAM_FLAGS.index("RAM_PACKED") & 1
    if flags & flag_bits("RAM_READ_ONLY", "RAM_SINGLE_PORT") and not flags >> RAM_FLAGS.index("RAM_SINGLE_PORT_IMPLEMENTED_IN_SIMPLE_DUAL_PORT") & 1:
        v = 1
    return v


def packed_mode_value(flags):
    # source: ASM_RAM_USE_PACKED_MODE::process_end_of_phase libcomp_asmram: port A flag bit 32 = RAM_PACKED
    return flags >> RAM_FLAGS.index("RAM_PACKED") & 1
