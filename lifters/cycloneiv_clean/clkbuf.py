"""Global clock buffer input select: which CLKBUF_IN feeds each clock buffer, and the fixed wires into it (#171, #175).  Vendor-derived only.

CLKBUF_IN (x, y, z = 28..33, index I) has an empty asm group (fixed wire); parents by I:
  I = 0, 1 CLK_BUFFER (dedicated clock pad), 2, 3 PLL_BUFFER (two PLLs; PLL_BUFFER index = output counter c0..c4), 4 BLOCK_INPUT_MUX (bim.py), 5 IO_RAWDATAIN.
Which one a clock buffer uses is the arch group CLKBUF_CLK_INPUT_SELECT_CYCLONEII of block type 73 (CLKBUF_GCLK), one 4-bit encoded
site per clock buffer: value = (second_pll_feeds_clock_mux ? 8 : 0) | I of the selected CLKBUF_IN, 7 = none
(source: ASM_CLKBUF_CLK_INPUT_SELECT_CYCLONEII::process_atom@0x2fd9f8 and second_pll_feeds_clock_mux@0x2f9adc).
Core input (index 4): group CLKBUF_INTERFACE_COREIN gi = site, value = LOCAL_INTERCONNECT index of the BIM tile; the edge LI -> BLOCK_INPUT_MUX (the BIM
that feeds the CLKBUF_IN, bim.py) is absent from the routing graph and appended here (ASM_CLKBUF_INTERFACE_COREIN::process_atom@0x2fe19a: RE type 0xbf source
index -> mux_select; 4 of 4 specimens gx150_sp_{017,021,022,267}).
Two PLL parents: bit 3 set = the PLL whose icd equals dirt CLKMUX_PLL_SOURCE[site], clear = the other parent (7 of 7 PLL specimens).
Site -> tile: the dirt gives one icd per run of 6 sites; each run belongs to the tile whose PLL parents include that icd (unique, 5 of 5).
Site -> z: z = 28 + position in the run (specimen: sites 2, 8, 23, 29 and 117 used CLKBUF_IN of the corpus).
"""
import numpy as np

from . import bim, ddb, io_line, names
from . import plane as P

GROUP = "CLKBUF_CLK_INPUT_SELECT_CYCLONEII"      # source: libdb_asmdb arch-group-type table, block type 73
COREIN = "CLKBUF_INTERFACE_COREIN"                # source: same table; 30 groups (gi = site), one site each, value = LOCAL_INTERCONNECT index feeding the core input
BLOCK = 73                                        # source: ASMDB_ARCH_GROUP_BLOCK_TYPE CLKBUF_GCLK (docs/cycloneiv-clean-fields.md)
VALUES = 16                                       # source: group mux = 4 encoded bits (asmdb mux class 15, 4 bits)
NONE = 7                                          # source: ASM_CLKBUF_CLK_INPUT_SELECT_CYCLONEII::process_atom@0x2fd9f8 (tied-off input)
DB_ILLEGAL = 0xFFFFFFFA                           # source: cycloneiv_io.ADDRESS_SPACES comment: 0xfffffffa..e = DB_ILLEGAL_* markers
PER_TILE = 6                                      # source: CLKBUF_IN z = 28..33 per clock buffer tile (routing.ddb element records)
Z0 = 28
# source: DEV_ELEMENT_ENUM names (reference/ghidra/enums.tsv) of the elements with a fan-out edge into CLKBUF_IN (routing.ddb scan)
PARENTS = ("CLK_BUFFER", "IO_RAW_DATAIN", "PLL_BUFFER")
BIT3 = 8                                          # source: process_atom `uVar7 | 8` when second_pll_feeds_clock_mux


def tiles(rt, enum):
    """[(x, y) per site]: site tiles from the dirt runs (see module doc)."""
    from . import pll
    icd_at = {xy: k for k, (_, _, xy) in pll.pll_tiles().items()}
    e_clk = names.enum_of("CLKBUF_IN")
    tile_icds = {}
    for r in np.flatnonzero(enum == names.enum_of("PLL_BUFFER")).tolist():
        for d in rt.fanout(r).tolist():
            if enum[d] == e_clk and Z0 <= rt.element(d)[3] < Z0 + PER_TILE:       # the PLL tiles' own CLKBUF_IN (z 0) are not clock buffer sites
                tile_icds.setdefault((int(rt.x[d]), int(rt.y[d])), set()).add(icd_at[(int(rt.x[r]), int(rt.y[r]))])
    src = pll.clkmux_pll_source()
    runs, gid = [], 0
    while gid < len(src):
        n = 1
        while gid + n < len(src) and src[gid + n] == src[gid]:
            n += 1
        if n != PER_TILE:
            raise SystemExit(f"dirt run of {n} clock buffers at gid {gid}, expected {PER_TILE}")
        runs.append((gid, src[gid]))
        gid += n
    cand = {g0: {xy for xy, ic in tile_icds.items() if icd in ic} for g0, icd in runs}
    while any(len(c) > 1 for c in cand.values()):          # eliminate tiles already claimed by a single-candidate run
        one = {next(iter(c)) for c in cand.values() if len(c) == 1}
        nxt = {g: (c if len(c) == 1 else c - one) for g, c in cand.items()}
        if nxt == cand:
            raise SystemExit(f"clock buffer runs not resolvable to tiles: {cand}")
        cand = nxt
    if len(runs) != len(tile_icds) or len({next(iter(c)) for c in cand.values()}) != len(runs) or any(len(c) != 1 for c in cand.values()):
        raise SystemExit(f"clock buffer runs {runs} vs tiles {sorted(tile_icds)}: no bijection")
    return [next(iter(cand[g0])) for g0, _ in runs for _ in range(PER_TILE)]


class ClkbufIn:
    def __init__(self, st, rt, bim_imp, w, nm, tables=None, pllw=None):
        self.pllw = pllw
        from . import pll
        tab = tables or P.load_tables()
        self.line = io_line.Line(w, nm, BLOCK, GROUP, -1, tab, n_inputs=VALUES)
        find = bim.finder(rt)
        e_clk = names.enum_of("CLKBUF_IN")
        enum = np.where(rt.tpl >= 0, rt.enum[np.maximum(rt.tpl, 0)].astype(np.int32), -1)
        site_tile = tiles(rt, enum)
        if self.line.n_sites != len(site_tile):
            raise SystemExit(f"{GROUP}: {self.line.n_sites} sites, dirt has {len(site_tile)}")
        e_pb = names.enum_of("PLL_BUFFER")
        icd_at = {xy: k for k, (_, _, xy) in pll.pll_tiles().items()}
        src = pll.clkmux_pll_source()
        parents = {}
        for r in np.flatnonzero(np.isin(enum, [names.enum_of(n) for n in PARENTS])).tolist():
            for d in rt.fanout(r).tolist():
                if enum[d] == e_clk:
                    parents.setdefault(d, []).append(r)
        e_li = names.enum_of("LOCAL_INTERCONNECT")
        self.core, esrc, edst, n = [], [], [], len(st.esrc)        # per site: (COREIN line, {LI index: appended edge id})
        self.edge = []                                  # per site: {value: edge id}
        for s in range(self.line.n_sites):
            x, y = site_tile[s]
            z = Z0 + s % PER_TILE
            m = {}
            for i in range(VALUES):
                c = find(ddb.element_key(e_clk, x, y, z, i))
                if c < 0:
                    continue
                if c in bim_imp.into_clkbuf:
                    m[i] = [(bim_imp.into_clkbuf[c], None)]
                    continue
                ps = parents.get(c, [])
                if len(ps) == 2 and all(enum[p] == e_pb for p in ps):
                    # bit 3 set: the parent PLL whose icd is the dirt source of this clock buffer; clear: the other parent(s)
                    # (both when the dirt PLL is no parent of this CLKBUF_IN: resolved by the enabled PLL at apply time)
                    cand = [(p, icd_at[(int(rt.x[p]), int(rt.y[p]))]) for p in ps]
                    for v, sel in ((i | BIT3, [c for c in cand if c[1] == src[s]]), (i, [c for c in cand if c[1] != src[s]])):
                        m[v] = [(int(st.edge_ids([p], [c])[0]), icd) for p, icd in sel]
                elif len(ps) == 1:
                    e = int(st.edge_ids([ps[0]], [c])[0])
                    if e >= 0:
                        m[i] = [(e, None)]
                elif len(ps) > 1:
                    raise SystemExit(f"CLKBUF_IN record {c} has {len(ps)} parents")
            self.edge.append(m)
            b = bim_imp.into_clkbuf.get(find(ddb.element_key(e_clk, x, y, z, 4)), -1)
            if b >= 0:
                brec = int(st.esrc[b])
                line = io_line.Line(w, nm, BLOCK, COREIN, s, tab)
                keep = [i for i, o in enumerate(line.offs[0]) if 0 <= o < DB_ILLEGAL]      # illegal-address markers are not bits (a column of the pattern table)
                line.pat[0], line.offs[0] = line.pat[0][:, keep], [line.offs[0][i] for i in keep]
                lm = {}
                for li in range(line.n_inputs):
                    r = find(ddb.element_key(e_li, int(rt.x[brec]), int(rt.y[brec]), 0, li))
                    if r >= 0:
                        lm[li] = n
                        esrc.append(r)
                        edst.append(brec)
                        n += 1
                self.core.append((line, lm))
        self.esrc, self.edst, self.n_real = np.asarray(esrc, np.int32), np.asarray(edst, np.int32), len(st.esrc)

    def apply(self, bits):
        """-> edge ids into the CLKBUF_IN each clock buffer selects (value NONE / undecoded: nothing).  Several candidate PLL parents: the one
        whose PLL is enabled (CFF), none when that is not exactly one."""
        out, en = [], None
        for line, lm in self.core:
            v = line.select(bits, 0)
            if v in lm:
                out.append(lm[v])
        for s, m in enumerate(self.edge):
            v = self.line.select(bits, s)
            if v == NONE or v not in m:
                continue
            c = [(e, icd) for e, icd in m[v] if e >= 0]
            if len(c) > 1 and self.pllw is not None:
                en = self.pllw.enabled(bits) if en is None else en
                c = [x for x in c if x[1] in en]
            if len(c) == 1:
                out.append(c[0][0])
        return np.asarray(out, np.int64)
