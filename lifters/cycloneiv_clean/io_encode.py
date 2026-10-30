"""Cyclone IV GX IO group value encoder, derived from the vendor select code (#168).  No pair builds involved.

Source (static decompile, reference/ghidra/functions.tsv):
  - ASM_ARCH_GROUP::mux_select(group, site, value) -> ASMDB_ARCH_GROUP_STD::select(site, value, streams) @ libdb_asmdb 0x7a3ac:
    per m_mux_data_list entry i: mux = m_mux_path_list[site][i]; bits = mux.select(value); if entry.arch_value == 0: every bit inverted;
    next value = entry.next_mux_selection.vcall(value); 0xfffffffb ends the chain.
  - ASMDB_ENCODED_MUX::select @ 0x8c0ba: bit k of the mux (m_mux_bits[k]) = (value >> k) & 1; value >= 2^nbits is an internal error.
  - ASMDB_MAPPED_ENCODED_MUX::select @ 0x8c19a: value = m_map_mux.vcall_0x40(value), then ENCODED select.
  - ASMDB_ARCH_GROUP_DUMB::select @ 0x72100: bit = (value == 0) if arch_value == 0 else (value != 0); value > 1 is an internal error.
Only the groups the IO sites use are supported (single mux per path, ENCODED / DUMB); anything else raises (never guessed).
"""
CFF_TAG = 5                    # top 3 bits of a CFF address (cycloneiv_io.ADDRESS_SPACES)
# source: asmdb IOST mux bit lists (4th bit of 51 sites, all 4 of the pad-less VIO site) = the PDB list terminator value, a bit that does not exist
NO_BIT = 0xFFFFFFFB
ENCODED_CLASS = 15             # ASMDB_ENCODED_MUX in the ddb type table (docs/cycloneiv-clean-io.md)


class Unsupported(ValueError):
    pass


def select(walk, group, site, value):
    """[(address, bit)] the vendor select writes for `value` at `site` of the arch-group object `group` (walk.groups() entry)."""
    if group["cls"] == 7:
        if value > 1:
            raise ValueError(f"DUMB group value {value} > 1")
        bit = int(value == 0) if group["arch"] == 0 else int(value != 0)
        return [(group["bits"][site], bit)]
    if group["cls"] != 6 or len(group["data"]) != 1 or len(group["paths"][site]) != 1:
        raise Unsupported(f"group class {group['cls']} with {len(group['data'])} mux entries")
    mux = walk.mux(group["paths"][site][0])
    if mux["cls"] != ENCODED_CLASS:
        raise Unsupported(f"mux class {mux['cls']}")
    n = len(mux["bits"])
    if value >= 1 << (n - sum(1 for a in mux["bits"] if a == NO_BIT)):
        raise ValueError(f"value {value} needs more than {n} bits")
    inv = int(group["data"][0]["av"] == 0)
    return [(a, ((value >> k) & 1) ^ inv) for k, a in enumerate(mux["bits"]) if a != NO_BIT]


def pattern(walk, group, site, value, space=CFF_TAG):
    """Pattern string (mux element order) of the bits of `space` for `value`; element i = i-th bit address of the group at the site."""
    return "".join(str(b) for a, b in select(walk, group, site, value) if a >> 29 == space)


def value_of(pat, inverted=False):
    """Inverse of the ENCODED select for a full pattern (element k = value bit k)."""
    v = sum((int(c) ^ int(inverted)) << k for k, c in enumerate(pat))
    return v


def width(walk, group, site):
    if group["cls"] == 7:
        return 1
    return sum(1 for a in walk.mux(group["paths"][site][0])["bits"] if a != NO_BIT)


def all_values(walk, group, site):
    """{value: pattern} for every legal value of the group at the site (2^n for ENCODED, 0..1 for DUMB)."""
    n = 2 if group["cls"] == 7 else 1 << width(walk, group, site)
    return {v: pattern(walk, group, site, v) for v in range(n)}

