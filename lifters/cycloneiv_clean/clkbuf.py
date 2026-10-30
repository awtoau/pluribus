"""Global clock buffer input select: which CLKBUF_IN feeds each clock buffer, and the fixed wires into it (#171).  Vendor-derived only.

CLKBUF_IN (x, y, z = 28..33, index I) has exactly one parent in the routing graph and an empty asm group (fixed wire):
  I = 0, 1 CLK_BUFFER (dedicated clock pad), 2 PLL_BUFFER, 4 BLOCK_INPUT_MUX (bim.py: core signal), 5 IO_RAWDATAIN (pad).
Which one a clock buffer uses is the arch group CLKBUF_CLK_INPUT_SELECT_CYCLONEII of block type 73 (CLKBUF_GCLK), one 4-bit encoded
site per clock buffer; value = I of the selected CLKBUF_IN, 7 = none (source: ASM_CLKBUF_CLK_INPUT_SELECT_CYCLONEII::process_atom@0x2fd9f8:
`uVar7 = ASM_RE_PROXY::get_index(CLKBUF_IN)`, tied-off input 7, mux_select(group, clkbuf index, value)).
The edge from the unique parent into the selected CLKBUF_IN conducts.  Site -> (tile, z): see CLKBUF_TILES.
"""
import numpy as np

from . import bim, blockiface, ddb, io_line, names
from . import plane as P

GROUP = "CLKBUF_CLK_INPUT_SELECT_CYCLONEII"      # source: libdb_asmdb arch-group-type table, block type 73
BLOCK = 73                                        # source: ASMDB_ARCH_GROUP_BLOCK_TYPE CLKBUF_GCLK (docs/cycloneiv-clean-fields.md)
VALUES = 16                                       # source: group mux = 4 encoded bits (asmdb mux class 15, 4 bits)
NONE = 7                                          # source: ASM_CLKBUF_CLK_INPUT_SELECT_CYCLONEII::process_atom@0x2fd9f8 (tied-off input)
PER_TILE = 6                                      # source: CLKBUF_IN z = 28..33 per clock buffer tile (routing.ddb element records)
Z0 = 28
# source: corpus fit, 117 used CLKBUF_IN of 40 designs gx150_sp_*: site // 6 -> tile; the order of the clockspine model's buffer list (resolve_clock_buffer_index_for_blk_type) is not read
# source: DEV_ELEMENT_ENUM names (reference/ghidra/enums.tsv) of the elements with a fan-out edge into CLKBUF_IN (routing.ddb scan: CLK_BUFFER, IO_RAWDATAIN, PLL_BUFFER_*)
PARENTS = ("CLK_BUFFER", "IO_RAWDATAIN", "PLL_BUFFER_K", "PLL_BUFFER_P", "PLL_BUFFER_Q")
CLKBUF_TILES = ((0, 45), (0, 46), (117, 46), (57, 91), (57, 0))


class ClkbufIn:
    def __init__(self, st, rt, bim_imp, w, nm, tables=None):
        tab = tables or P.load_tables()
        self.line = io_line.Line(w, nm, BLOCK, GROUP, -1, tab, n_inputs=VALUES)
        if self.line.n_sites != PER_TILE * len(CLKBUF_TILES):
            raise SystemExit(f"{GROUP}: {self.line.n_sites} sites, expected {PER_TILE * len(CLKBUF_TILES)}")
        find = bim.finder(rt)
        e_clk = names.enum_of("CLKBUF_IN")
        enum = np.where(rt.tpl >= 0, rt.enum[np.maximum(rt.tpl, 0)].astype(np.int32), -1)
        de = blockiface.dev_enums()
        srcs = np.flatnonzero(np.isin(enum, [de[n] for n in PARENTS]))
        parent = {}
        for r in srcs.tolist():
            for d in rt.fanout(r).tolist():
                if enum[d] == e_clk:
                    if d in parent:
                        raise SystemExit(f"CLKBUF_IN record {d} has two parents")
                    parent[d] = r
        self.edge = []                                  # per site: {value: edge id}
        for s in range(self.line.n_sites):
            x, y = CLKBUF_TILES[s // PER_TILE]
            z = Z0 + s % PER_TILE
            m = {}
            for i in range(VALUES):
                c = find(ddb.element_key(e_clk, x, y, z, i))
                if c < 0:
                    continue
                if c in bim_imp.into_clkbuf:
                    m[i] = bim_imp.into_clkbuf[c]
                elif c in parent:
                    e = int(st.edge_ids([parent[c]], [c])[0])
                    if e >= 0:
                        m[i] = e
            self.edge.append(m)

    def apply(self, bits):
        """-> edge ids into the CLKBUF_IN each clock buffer selects (value NONE / undecoded: nothing)."""
        out = []
        for s, m in enumerate(self.edge):
            v = self.line.select(bits, s)
            if v != NONE and v in m:
                out.append(m[v])
        return np.asarray(out, np.int64)
