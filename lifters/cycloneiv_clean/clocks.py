"""Clock network and register-clock decode, Cyclone IV GX EP4CGX150 (#165).  Vendor-derived only.

Network (routing.ddb fan-in, A1): CLKBUF_OUT -> GLOBAL_CLK_H -> GLOBAL_CLK_V -> SCLK_TO_ROWCLK_BUF -> LAB_CLK -> BLK_CLK_BUF -> FF CLK.
Every node has fan-in 1 except LAB_CLK (30, the SCLK mux) and CLKBUF_OUT (0, root).  Bits:
  - SCLK_TO_ROWCLK_BUF -> LAB_CLK: 12-entry groups, literal flag rule (already in the tracer).
  - GLOBAL_CLK_H -> GLOBAL_CLK_V: 1-entry group, flags 0 / 0, address in the asmdb DEFAULT-BIT list (blank device = 1): the edge is
    programmed iff the bit is CLEARED.  All 120 such edges of the device are these (st.size == 1, no literal entry, default cell).
  - other 1-entry groups (flags 0 / 0, not in the default list: BLK_CLK_LIM -> LI, GEN_CORE_BUF -> C4 / C16 / R24 ...): programmed iff the bit is SET.
  - structural edges (empty group, fan-in 1) conduct when their destination is used downstream: demand propagates up the unique parent.
  - LAB side: LAB_CLOCK_FAST_MUX gi 0 / gi 1 pick one of 6 LAB clock lines (first-level bit j = BLK_CLK_BUF index j, input map in
    asmdb); LE_CLOCK_SELECT bit of the LE: 1 = mux gi 0, 0 = mux gi 1.
"""
import numpy as np

from . import ddb, muxsel, names, plane as P
from . import fields as F

CLOCK_MUX = "LAB_CLOCK_FAST_MUX"        # source: libdb_asmdb arch-group-type table (gi 0 and gi 1)
CLEAR_MUX = "LAB_CLEAR_FAST_MUX"        # source: libdb_asmdb arch-group-type table (gi 0 / 1); second-level mux = the same 6 line bits (a clock can drive CLRN)
CLOCK_SELECT = "LE_CLOCK_SELECT"        # source: libdb_asmdb arch-group-type table (one bit per LE)
LAB_BLOCK = 18                          # source: ASMDB_ARCH_GROUP_BLOCK_TYPE LAB (fields.PLACED)
LINES = 6                               # source: LAB_CLOCK_FAST_MUX first-level mux has 7 bits: 6 lines + 1 other-source bit; BLK_CLK_BUF index 0..5


def group_cells(w, names_, block, name, bases, site=0):
    """{gi: MapSelect} of every group `name` of a placed block type."""
    gt = names_["arch_group_type"]
    return {g["gi"]: muxsel.MapSelect(w, g, bases, site) for g in w.groups() if g["btype"] == block and gt.get(g["type"]) == name}


class Clocks:
    def __init__(self, st, lut, rt=None, names_=None):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        self.st, self.lut, self.rt = st, lut, rt or ddb.Routing()
        w = lut.walk
        names_ = names_ or D.enum_tables()
        bs = F.bases(w, LAB_BLOCK)
        self.mux = group_cells(w, names_, LAB_BLOCK, CLOCK_MUX, bs)
        assert sorted(self.mux) == [0, 1] and all(len(m.first_off) == LINES + 1 for m in self.mux.values())
        self.clear = group_cells(w, names_, LAB_BLOCK, CLEAR_MUX, bs)
        assert sorted(self.clear) == [0, 1] and all(len(m.second_off) == LINES for m in self.clear.values())
        gt = names_["arch_group_type"]
        g = next(g for g in w.groups() if g["btype"] == LAB_BLOCK and gt.get(g["type"]) == CLOCK_SELECT)
        tab = P.load_tables()
        a = np.stack([F.absolute(bs, np.asarray([o for o in w.mux(g["paths"][le][0])["bits"] if o < 0x80000000], np.int64))[:, 0]
                      for le in range(16)], axis=1)
        r, j, k = P.sof_to_rbf(a.ravel(), tab)
        self.sel_cells = (r * P.BITS_PER_FRAME + (j - 1) * P.LANES + k).reshape(a.shape)
        # BLK_CLK_BUF record per (lab, line): exact element key (A7); LAB index = column rank * 90 + Y - 1
        keys = np.sort(self.rt.element_keys())
        order = np.argsort(self.rt.element_keys(), kind="stable")
        xs = np.asarray(lut.xs)
        lab = np.arange(len(bs))
        x, y = xs[lab // F.ROWS_PER_COLUMN], lab % F.ROWS_PER_COLUMN + 1
        e = names.enum_of("BLK_CLK_BUF")
        q = np.array([[ddb.element_key(e, int(xx), int(yy), 0, ln) for ln in range(LINES)] for xx, yy in zip(x, y)], np.int64)
        i = np.minimum(np.searchsorted(keys, q), len(keys) - 1)
        self.blk = np.where(keys[i] == q, order[i], -1)
        if (self.blk < 0).any():
            raise SystemExit("LAB without six BLK_CLK_BUF records")
        # edges: inverted default-bit edges, structural parents
        sz = st.size
        ed = st.edst.astype(np.int64)
        indeg = np.bincount(ed, minlength=self.rt.n)
        one = np.flatnonzero((sz == 1) & (st.nlit == 0))
        dflt = np.array([b for b in w.default_bits if b < P.N_BITS], np.int64)
        r, j, k = P.sof_to_rbf(dflt, tab)
        dcell = r * P.BITS_PER_FRAME + (j - 1) * P.LANES + k
        isdef = np.isin(st.cell[st.estart[one]], dcell)
        self.inv = one[isdef]
        self.inv_cell = st.cell[st.estart[self.inv]]
        self.single = one[~isdef]                            # 1-entry enable groups outside the default list: programmed iff the bit is set
        self.single_cell = st.cell[st.estart[self.single]]
        struct = np.flatnonzero((sz == 0) & (indeg[ed] == 1))
        self.parent_edge = np.full(self.rt.n, -1, np.int64)
        self.parent_edge[ed[struct]] = struct

    def lines(self, bits):
        """int64 [labs, 2]: clock line chosen by LAB_CLOCK_FAST_MUX gi 0 / gi 1, -1 = none (no single hot bit among the 6 line bits)."""
        out = []
        for gi in (0, 1):
            m = self.mux[gi]
            v = bits[m.cells0].astype(np.int64)
            hot = (v.sum(1) == 1) & (v[:, :LINES].sum(1) == 1)
            out.append(np.where(hot, v[:, :LINES].argmax(1), -1))
        return np.stack(out, axis=1)

    def le_blk(self, bits):
        """int64 [labs, 16]: BLK_CLK_BUF record each LE's register clock comes from (-1 = LAB clock mux has no line)."""
        ln = self.lines(bits)
        sel = bits[self.sel_cells].astype(np.int64)                 # 1 = gi 0, 0 = gi 1
        line = np.where(sel == 1, ln[:, 0:1], ln[:, 1:2])
        lab = np.arange(len(ln))[:, None]
        return np.where(line >= 0, self.blk[lab, np.maximum(line, 0)], -1)

    def sinks(self, bits):
        ln = self.lines(bits)
        for gi in (0, 1):
            v = bits[self.clear[gi].cells1].astype(np.int64)
            ln = np.concatenate([ln, np.where(v.sum(1) == 1, v.argmax(1), -1)[:, None]], axis=1)
        lab = np.broadcast_to(np.arange(len(ln))[:, None], ln.shape)
        ok = ln >= 0
        return np.unique(self.blk[lab[ok], ln[ok]])

    def apply(self, bits, edges):
        """edges: programmed real edge ids (one variant).  -> ids with the default-bit edges replaced by the cleared-bit rule and the
        structural edges that carry a used clock added."""
        edges = np.asarray(edges, np.int64)
        keep = edges[~np.isin(edges, self.inv)]
        inv_on = self.inv[bits[self.inv_cell] == 0]
        single_on = self.single[bits[self.single_cell] == 1]
        prog = np.unique(np.concatenate([keep, inv_on, single_on]))
        seeds = np.unique(np.concatenate([self.st.esrc[prog].astype(np.int64), self.sinks(bits)]))
        got, seen = [], set()
        front = seeds
        while len(front):
            pe = self.parent_edge[front]
            pe = pe[pe >= 0]
            pe = np.array([e for e in pe.tolist() if e not in seen], np.int64)
            seen.update(pe.tolist())
            got.append(pe)
            front = np.unique(self.st.esrc[pe].astype(np.int64)) if len(pe) else pe
        return np.unique(np.concatenate([prog] + got))
