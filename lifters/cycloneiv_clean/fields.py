"""Cyclone IV GX (EP4CGX150) CRAM fields of the LAB / M9K (MEAB) / MAC blocks from the vendor asmdb (#169).  Vendor-derived only.

Every entry carries a `source` tag.  No constant is fitted:
  - absolute address = base + offset; base = hi * 6154 + lo of the block's instance cell (BLOCK_INFO m_block_lists[1],
    `hi << 16 | lo`), offset = the group mux bit as stored (signed, 31-bit CRAM space).  The oracle (LUT specimens, 1,023 sites,
    16,368 cells) agrees with no added constant: tests/cycloneiv_clean/test_fields.py.
  - instance index = column * 90 + row (column-major, hi steps -70 per row, lo constant per column); the 90 rows / 104, 8, 4 columns
    are the BLOCK_INFO list lengths (9,360 / 720 / 360 over 104 / 8 / 4 columns).
  - names: libdb_asmdb ASMDB_TRANSLATOR::m_asmdb_arch_group_type_debug_string_table (reference/ghidra/globals.tsv).
Groups of the other 4,664-name block types (IO, PLL, clock, transceiver, ...) have no BLOCK_INFO instance list in this asmdb except
HIO / VIO (CFF handled in io.py) and the two clock blocks, so their CRAM offsets stay relative: counted, not placed.
"""
import collections

import numpy as np

from . import plane as P

W = P.FRAMES                         # source: A4 (address = v * 6154 + s)
# source: libdb_asmdb ASMDB_ARCH_GROUP_BLOCK_TYPE enum (reference/ghidra/globals.tsv, #168)
PLACED = {18: "LAB", 39: "MEAB", 41: "MAC"}
BASE_LIST = 1                        # source: BLOCK_INFO m_block_lists key 1 = instance cell list for LAB / MEAB / MAC (asmdb walk)
ROWS_PER_COLUMN = 90                 # source: 9,360 / 104 = 720 / 8 = 360 / 4; hi steps -70 per row in every list
DB_ILLEGAL = {0xFFFFFFFD, 0xFFFFFFFC, 0xFFFFFFFE, 0xFFFFFFFA, 0xFFFFFFFB}     # source: silent_set_bits markers (docs/cycloneiv-address-spaces.md 2.1)
CLASS = {5: "calc", 6: "std", 7: "dumb", 8: "stlmap"}   # source: ddb type table class ids (docs/cycloneiv-clean-io.md)

# name-pattern -> role; patterns are the vendor type names, the role words are ours
ROLES = (
    ("LE_LUT_FUNCTION", "lut_init"),
    ("LE_LUT_INPUT", "le_input_mux"),
    ("LAB_PIA_TO_INPUT", "lab_input_mux"),
    ("LE_USE_CARRY", "carry"),
    ("LE_REG_OUT", "register_output"),
    ("LE_CLOCK_SELECT", "register_clock"),
    ("LE_CLEAR_SELECT", "register_clear"),
    ("LE_USE_SYNC", "register_sync"),
    ("LE_USE_REG", "register_mode"),
    ("LAB_CLOCK", "lab_clock"), ("LAB_CLEAR", "lab_clear"), ("LAB_CE", "lab_ce"), ("LAB_ENABLE_CE", "lab_ce"),
    ("LAB_SYNC", "lab_sync"), ("LAB_ENABLE_SYNC", "lab_sync"), ("LAB_INVERT", "lab_invert"), ("LAB_CLR_INVERT", "lab_invert"),
    ("RAM_CONTENT", "ram_init"),
    ("RAM_USAGE_MODE", "ram_mode"), ("RAM_USE_TRUE", "ram_mode"), ("RAM_USE_PACKED", "ram_mode"),
    ("RAM_DATA_WRITE_MODE", "ram_mode"), ("RAM_NEW_DATA", "ram_mode"),
    ("RAM_MS_", "ram_port_input_mux"), ("RAM_PIA_TO_INPUT", "ram_port_input_mux"),
    ("RAM_CE_", "ram_ce"), ("RAM_CLEAR_", "ram_clear"), ("RAM_CLOCK_", "ram_clock"), ("RAM_USE_CLR", "ram_clear"),
    ("RAM_SELECT_CL", "ram_clock_clear"), ("RAM_REG_", "ram_output_register"),
    ("RAM_WRITE_ENABLE", "ram_we"), ("RAM_READ_ENABLE", "ram_re"), ("RAM_RE_", "ram_re"), ("RAM_WE_", "ram_we"),
    ("MAC_ROW_DATA_INPUT", "mac_input_mux"), ("MAC_PIA_TO", "mac_input_mux"), ("MAC_", "mac_mode"),
)


def role_of(name):
    for pat, role in ROLES:
        if name.startswith(pat):
            return role
    return "other"


class Field:
    """One arch-group of a placed block: per site, the mux paths (list of offset lists)."""
    __slots__ = ("btype", "block", "gi", "gtype", "name", "cls", "role", "sites", "aux", "values", "source")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _site_offsets(w, g):
    """per site -> list of offset arrays (one per mux path); DUMB groups: one bit per site."""
    if g["cls"] == 7:
        return [[np.array([b], np.int64)] for b in g["bits"]]
    return [[np.array(w.mux(r)["bits"], np.int64) for r in p if r] for p in g["paths"]]


def _aux_offsets(w, g):
    out = []
    for d in g.get("data", ()):
        for key in ("aux", "nxt"):
            m = d[key]
            if m and m[0] == "MUX":
                out.append(np.array(w.mux(m)["bits"], np.int64))
    return out


def fields(w, names, block_types=None):
    """All arch-group Fields of the walk (names = enum tables 'arch_group_type', 'block_type' joined as names[...])."""
    gt, bt = names["arch_group_type"], names["block_type"]
    out = []
    for g in w.groups():
        if block_types and g["btype"] not in block_types:
            continue
        nm = gt.get(g["type"], str(g["type"]))
        out.append(Field(
            btype=g["btype"], block=bt.get(g["btype"], str(g["btype"])), gi=g["gi"], gtype=g["type"], name=nm, cls=CLASS[g["cls"]],
            role=role_of(nm), sites=_site_offsets(w, g), aux=_aux_offsets(w, g), values=[d["av"] for d in g.get("data", ())],
            source=f"asmdb {CLASS[g['cls']]} group type {g['type']} gi {g['gi']}; name libdb_asmdb arch_group_type table"))
    return out


def bases(w, btype):
    """Absolute base (hi * 6154 + lo) of every instance of a placed block type, instance order = list order."""
    cells = np.array(next(b for b in w.block_infos() if b["btype"] == btype)["lists"][BASE_LIST], np.int64)
    return (cells >> 16) * W + (cells & 0xFFFF)


def valid_offsets(a):
    a = np.asarray(a, np.int64)
    return a[(a >= 0) & (a < 0x80000000)]


def absolute(base, offsets):
    """base [n] + offsets [m] -> [n, m] absolute CRAM bit addresses (all within the die, else ValueError)."""
    a = base[:, None] + valid_offsets(offsets)[None, :]
    if a.size and (a.min() < 0 or a.max() >= P.N_BITS):
        raise ValueError("address outside CRAM")
    return a


def claim_masks(w, flds, btype):
    """{'path': bool[N_BITS], 'aux': bool[N_BITS]} of one placed block type; path = bits of the group's own mux paths,
    aux = bits of the aux / next-selection muxes of the same group (written with a selection)."""
    bs = bases(w, btype)
    m = {"path": np.zeros(P.N_BITS, bool), "aux": np.zeros(P.N_BITS, bool)}
    for f in flds:
        if f.btype != btype:
            continue
        for site in f.sites:
            for off in site:
                m["path"][absolute(bs, off).ravel()] = True
        for off in f.aux:
            m["aux"][absolute(bs, off).ravel()] = True
    return m


def summary(flds):
    """{(block, name): dict(groups, sites, offsets)} over relative offsets (per instance)."""
    t = collections.OrderedDict()
    for f in flds:
        e = t.setdefault((f.block, f.name), dict(groups=0, sites=0, offsets=0, aux=0, role=f.role))
        e["groups"] += 1
        e["sites"] += len(f.sites)
        e["offsets"] += sum(len(o) for s in f.sites for o in s)
        e["aux"] += sum(len(o) for o in f.aux)
    return t
