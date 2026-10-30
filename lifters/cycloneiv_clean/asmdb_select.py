"""Value -> bit writes of an asmdb mux, from the vendor `ASMDB_*_MUX::select` code (libdb_asmdb, static decompile) (#169).

Walk mux class ids (docs: ddb type table): 14 MAPPED_SIMPLE, 15 ENCODED, 17 SIMPLE, 18 MAPPED_ENCODED, 19 DECISION, 20 HETEROGENEOUS_ENCODED; others raise (not decoded).
select(walk, ref, value) -> [(mux bit offset, 0/1)] (the DB_BIT_SETTING list a `mux_select(group, value)` produces for that mux).
"""
DUMMY = 0xFFFFFFFE      # source: ASMDB_SIMPLE_MUX::select@0x8c4ac: DUMMY_BIT_ADDRESS (-2) entries are skipped; selecting one is an internal error
SIMPLE, MAPPED_SIMPLE, ENCODED, MAPPED_ENCODED, DECISION, HETERO_ENCODED = 17, 14, 15, 18, 19, 20      # source: ASMDB ddb type table (cycloneiv_io.ddb_types)


def _simple(bits, value):
    # source: ASMDB_SIMPLE_MUX::select@0x8c4ac: bit i = (i == value); value >= len is an internal error
    if value >= len(bits):
        raise ValueError(f"SIMPLE_MUX value {value} >= {len(bits)}")
    return [(b, int(i == value)) for i, b in enumerate(bits) if b != DUMMY]


def _encoded(bits, value):
    # source: ASMDB_ENCODED_MUX::select@0x8c0ba: bit k = (value >> k) & 1; value >= 2^n is an internal error
    if len(bits) != 32 and value >= 1 << len(bits):
        raise ValueError(f"ENCODED_MUX value {value} >= 2^{len(bits)}")
    return [(b, (value >> k) & 1) for k, b in enumerate(bits)]


def _map(walk, m, value):
    # source: ASMDB_MAPPED_*_MUX::select@0x8c5b8 / 0x8c19a: value = m_map_mux.get_bit_value(value) (SIMPLE mux bits used as a lookup table), then the base select
    table = walk.mux(m["map"])["bits"]
    if value >= len(table) or table[value] == DUMMY:
        raise ValueError(f"map entry {value} illegal")
    return table[value]


def select(walk, ref, value):
    m = walk.mux(ref)
    c = m["cls"]
    if c == SIMPLE:
        return _simple(m["bits"], value)
    if c == ENCODED:
        return _encoded(m["bits"], value)
    if c == MAPPED_SIMPLE:
        return _simple(m["bits"], _map(walk, m, value))
    if c == MAPPED_ENCODED:
        return _encoded(m["bits"], _map(walk, m, value))
    if c == DECISION:
        # source: ASMDB_DECISION_MUX::select@0x8c36e: value 0 writes the lower half with m_lower_setting, value 1 the upper half with m_upper_setting
        n = len(m["bits"])
        lo, hi = m["bits"][:n // 2], m["bits"][n // 2:]
        return [(b, m["lo"]) for b in lo] if value == 0 else [(b, m["hi"]) for b in hi]
    if c == HETERO_ENCODED:
        # source: ASMDB_HETEROGENEOUS_ENCODED_MUX::select@0x8c334: value = ASMDB_MUX::get_bit_value(m_map_mux, value) (@0x868e8: m_mux_bits[value],
        #         value >= size is an internal error), then ASMDB_ENCODED_MUX::select on the base bits
        table = m["bits2"]
        if value >= len(table):
            raise ValueError(f"HETEROGENEOUS_ENCODED_MUX value {value} >= {len(table)}")
        return _encoded(m["bits"], table[value])
    raise NotImplementedError(f"mux class {c}")


NEXT_END = 0xFFFFFFFB       # source: ASMDB_ARCH_GROUP_STD::select@0x7a3ac: a next value of 0xfffffffb ends the chain


def std_select(walk, g, site, value):
    """[(bit offset, 0/1)] a STD arch group (class 6) writes for `value` at `site` (source: ASMDB_ARCH_GROUP_STD::select@0x7a3ac).

    Entry i: bits = mux_i.select(value_i); arch_value 0 inverts every bit of the entry; value_{i+1} = nxt_i.get_bit_value(value_i)
    (ASMDB_MUX::get_bit_value@0x868e8 = m_mux_bits[value_i]); 0xfffffffb or the last entry ends the chain.
    """
    out = []
    for i, d in enumerate(g["data"]):
        w = select(walk, g["paths"][site][i], value)
        out += [(b, v ^ 1) for b, v in w] if d["av"] == 0 else w
        if i == len(g["data"]) - 1 or d["nxt"] is None:
            break
        t = walk.mux(d["nxt"])["bits"]
        if value >= len(t):
            raise ValueError(f"next-mux value {value} >= {len(t)}")
        value = t[value]
        if value == NEXT_END:
            break
    return out
