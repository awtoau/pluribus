"""Register-control decode of a Cyclone IV GX LAB (#165).  Vendor groups + vendor value->bit rules (asmdb_select); no fitted constant.

LAB signals (libcomp_asm ASM_LAB_*_FAST_MUX / ASM_LAB_ENABLE_* process_end_of_phase, static decompile):
  clock k (k = 0, 1)  LAB_CLOCK_FAST_MUX gi k;  inputs 0..3 = LAB_CONTROL_MUX index, 4..9 = BLK_CLK_BUF line input - 4 (value = RE index + base)
  aclr k              LAB_CLEAR_FAST_MUX gi k;  inputs 0..3 = LAB_CONTROL_MUX, 4..9 = BLK_CLK_BUF line, 10 = unconstrained second level (no source)
  enable k            LAB_CE_FAST_MUX gi k;     input i = LAB_CONTROL_MUX i; used iff LAB_ENABLE_CE gi k (value 1: CE index == clock index == gi)
  sclr / sload        LAB_SYNC_CLR_FAST_MUX / LAB_SYNC_LOAD_FAST_MUX_MAG: input i = LAB_CONTROL_MUX i;
                      used per LAB_ENABLE_SYNC_SIGNALS value (1 sload, 2 sclr, 3 both, 4 sload=VCC, 5 sload=VCC + sclr; value -> bits via the mux map)
LE selections: LE_CLOCK_SELECT / LE_CLEAR_SELECT (1 bit: signal index), LE_USE_SYNC_CLEAR / LE_USE_SYNC_LOAD (DECISION mux, value 1 writes the
  one real bit; both groups share it: bit = sclr term connected OR sload term connected).
Value -> bit law (ASMDB_ARCH_GROUP_STD::select, docs/cycloneiv-clean-io.md): every bit of a mux entry is inverted when its `arch_value` is 0
(LE_CLOCK_SELECT, LE_CLEAR_SELECT, LE_USE_CARRY, LAB_ENABLE_CE, LAB_CLR_INVERT_PAIR, LAB_INVERT gi 5); `val()` undoes it.
Select decode = inverse of the vendor writer: each input i has the bit pattern asmdb_select.select() gives for (first level, value i) and
(second level, nxt[i]); the input whose constrained bits all match wins, most constrained first (FREE second level = unconstrained).
"""
import numpy as np

from . import asmdb_select as S
from . import clocks, ddb, names, plane as P
from . import fields as F

LAB_BLOCK = clocks.LAB_BLOCK
ABSENT, FREE = 0xFFFFFFFE, 0xFFFFFFFB          # source: asmdb mux vectors (muxsel.ABSENT / muxsel.FREE)
N_LCM = 4                                       # source: LAB_CLOCK_FAST_MUX aux: inputs 0..3 are the LAB_CONTROL_MUX inputs (4 per LAB, lab_control.py)
CLEAR_NONE = 10                                 # source: LAB_CLEAR_FAST_MUX aux: input 10 = first level 0, second level unconstrained (no source)
LINE_BASE = 4                                   # source: LAB_CLOCK_FAST_MUX aux: line inputs follow (inputs 4..9 = first-level bits 0..5)
# source: ASM_LAB_ENABLE_SYNC_SIGNALS::process_atom@0x15feb6 (value per sload / sclr signal index; names are ours)
SYNC_STATE = {0: "none", 1: "sload", 2: "sclr", 3: "both", 4: "sload_vcc", 5: "sload_vcc+sclr"}
# source: libdb_asmdb arch-group-type table (one bit per LE, LAB block 18); semantics from the ASM_LE_* process_atom writers (docstring)
LE_GROUPS = ("LE_CLOCK_SELECT", "LE_CLEAR_SELECT", "LE_USE_SYNC_CLEAR", "LE_USE_SYNC_LOAD", "LE_USE_CARRY", "LE_USE_REGISTER_FEEDBACK",
             "LE_USE_REG_CASCADE_ARM")


def _cols(bs, offs, tab):
    """{position in the mux bit list: cell index array [labs]} of the valid (31-bit CRAM) offsets."""
    ok = [i for i, o in enumerate(offs) if 0 <= o < 0x80000000]
    if not ok:
        return {}
    a = F.absolute(bs, np.asarray([offs[i] for i in ok], np.int64))
    r, j, k = P.sof_to_rbf(a.ravel(), tab)
    c = (r * P.BITS_PER_FRAME + (j - 1) * P.LANES + k).reshape(a.shape)
    return {i: c[:, n] for n, i in enumerate(ok)}


class Calc:
    """Inverse of a calc group's writer: select(bits) -> int64 [labs] input number (-1 none, -2 ambiguous)."""

    def __init__(self, w, g, bs, tab, site=0):
        refs = g["paths"][site]
        d = g["data"][0]
        aux = w.mux(d["aux"])["bits"]
        nxt = w.mux(d["nxt"])["bits"] if d["nxt"] and d["nxt"][0] == "MUX" else None
        self.av = [x["av"] for x in g["data"]]
        self.offs = [w.mux(r)["bits"] for r in refs]
        self.cols = [_cols(bs, o, tab) for o in self.offs]
        self.pos = [{o: n for n, o in enumerate(offs)} for offs in self.offs]
        self.pat = {}
        for i, a in enumerate(aux):
            if a == ABSENT:
                continue
            p = []
            try:
                p += [(0, o, v if self.av[0] else 1 - v) for o, v in S.select(w, refs[0], i) if o != S.DUMMY]
                if len(refs) > 1 and nxt is not None and nxt[i] not in (FREE, ABSENT):
                    p += [(1, o, v if self.av[1] else 1 - v) for o, v in S.select(w, refs[1], nxt[i]) if o != S.DUMMY]
            except (ValueError, NotImplementedError):
                continue
            self.pat[i] = p

    def select(self, bits):
        n = len(next(iter(self.cols[0].values())))
        best = np.full(n, -1, np.int64)
        spec = np.zeros(n, np.int64)
        amb = np.zeros(n, bool)
        for i, p in self.pat.items():
            ok = np.ones(n, bool)
            for lvl, o, v in p:
                ok &= bits[self.cols[lvl][self.pos[lvl][o]]] == v
            k = len(p)
            take = ok & (k > spec)
            tie = ok & (k == spec) & (best >= 0)
            amb = np.where(take, False, amb | tie)
            best = np.where(take, i, best)
            spec = np.where(take, k, spec)
        return np.where(amb, -2, best)


class FfCtl:
    def __init__(self, lut, rt=None, clk=None, names_=None):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        w = lut.walk
        names_ = names_ or D.enum_tables()
        gt = names_["arch_group_type"]
        tab = P.load_tables()
        bs = F.bases(w, LAB_BLOCK)
        self.nlab = len(bs)
        by = {}
        for g in w.groups():
            if g["btype"] == LAB_BLOCK:
                by.setdefault(gt.get(g["type"]), {})[g["gi"]] = g
        self.calc = {n: {gi: Calc(w, by[n][gi], bs, tab) for gi in by[n]}
                     for n in ("LAB_CLOCK_FAST_MUX", "LAB_CLEAR_FAST_MUX", "LAB_CE_FAST_MUX", "LAB_SYNC_CLR_FAST_MUX", "LAB_SYNC_LOAD_FAST_MUX_MAG")}
        self.one = {n: {gi: (_cols(bs, w.mux(by[n][gi]["paths"][0][0])["bits"], tab)[0], by[n][gi]["data"][0]["av"]) for gi in by[n]}
                    for n in ("LAB_ENABLE_CE", "LAB_INVERT")}
        ref = by["LAB_ENABLE_SYNC_SIGNALS"][-1]["paths"][0][0]
        self.sync_cols = _cols(bs, w.mux(ref)["bits"], tab)
        sav = by["LAB_ENABLE_SYNC_SIGNALS"][-1]["data"][0]["av"]
        self.sync_val = {tuple(v if sav else 1 - v for _, v in S.select(w, ref, s)): s for s in SYNC_STATE}
        cg = by["LAB_CLR_INVERT_PAIR"][6]
        self.clr_inv = _cols(bs, w.mux(cg["paths"][0][0])["bits"], tab)
        self.clr_inv_av = cg["data"][0]["av"]
        self.le = {}
        for n in LE_GROUPS:
            g = by[n][-1]
            cs = [_cols(bs, w.mux(g["paths"][le][0])["bits"], tab) for le in range(16)]
            self.le[n] = (np.stack([c[max(c)] for c in cs], axis=1), g["data"][0]["av"])    # the real (last valid) bit per LE [labs, 16], arch_value
        rt = rt or ddb.Routing()
        keys_all = rt.element_keys()
        order = np.argsort(keys_all, kind="stable")
        keys = keys_all[order]
        xs = np.asarray(lut.xs)
        lab = np.arange(self.nlab)
        x, y = xs[lab // F.ROWS_PER_COLUMN].astype(np.int64), (lab % F.ROWS_PER_COLUMN + 1).astype(np.int64)
        e = names.enum_of("LAB_CONTROL_MUX")
        q = np.stack([ddb.element_key(e, x, y, 0, k) for k in range(N_LCM)], axis=1)
        i = np.minimum(np.searchsorted(keys, q), len(keys) - 1)
        self.lcm = np.where(keys[i] == q, order[i], -1)                              # [labs, 4]
        if (self.lcm < 0).any():
            raise SystemExit("LAB without four LAB_CONTROL_MUX records")
        self.blk = clk.blk if clk is not None else None                              # [labs, 6]

    def _src(self, sel, lines=True):
        """record per LAB for input numbers `sel` [labs]: LAB_CONTROL_MUX i (i < 4) or BLK_CLK_BUF line (i - 4); -1 none / ambiguous."""
        lab = np.arange(self.nlab)
        out = np.full(self.nlab, -1, np.int64)
        m = (sel >= 0) & (sel < N_LCM)
        out[m] = self.lcm[lab[m], sel[m]]
        if lines and self.blk is not None:
            m = (sel >= LINE_BASE) & (sel < LINE_BASE + self.blk.shape[1])
            out[m] = self.blk[lab[m], sel[m] - LINE_BASE]
        return out

    def lab_signals(self, bits):
        """dict of per-LAB arrays: *_sel = input number (-1 none, -2 ambiguous), *_rec = source record (-1 none)."""
        c = self.calc
        o = {}
        for key, name, lines in (("clk", "LAB_CLOCK_FAST_MUX", True), ("aclr", "LAB_CLEAR_FAST_MUX", True), ("ce", "LAB_CE_FAST_MUX", False)):
            o[key + "_sel"] = np.stack([c[name][g].select(bits) for g in (0, 1)], axis=1)
            o[key + "_rec"] = np.stack([self._src(o[key + "_sel"][:, g], lines) for g in (0, 1)], axis=1)
        # ASM_LE_CLEAR_SELECT::process_atom@0x16baea: an LE without ACLR selects a signal whose real source is NULL (ground).  gi 0 / gi 1 share the six
        # second-level line bits and both read first-level 00 = "line" when unused, so equal line selections mean signal 1 is the unused one.
        a = o["aclr_sel"]
        same_line = (a[:, 0] == a[:, 1]) & (a[:, 0] >= LINE_BASE) & (a[:, 0] < LINE_BASE + 6)
        o["aclr_shared_line"] = same_line
        a[same_line, 1] = CLEAR_NONE
        o["aclr_rec"][same_line, 1] = -1
        o["ce_on"] = np.stack([self.val(self.one["LAB_ENABLE_CE"][g], bits) == 1 for g in (0, 1)], axis=1)
        o["sclr_sel"] = c["LAB_SYNC_CLR_FAST_MUX"][0].select(bits)
        o["sload_sel"] = c["LAB_SYNC_LOAD_FAST_MUX_MAG"][0].select(bits)
        o["sclr_rec"] = self._src(o["sclr_sel"], False)
        o["sload_rec"] = self._src(o["sload_sel"], False)
        v = np.stack([bits[self.sync_cols[k]] for k in sorted(self.sync_cols)], axis=1)
        st = np.full(self.nlab, -1, np.int64)
        for pat, s in self.sync_val.items():
            st[(v == np.asarray(pat)).all(1)] = s
        o["sync_state"] = st
        o["invert"] = np.stack([self.val(self.one["LAB_INVERT"][g], bits) for g in sorted(self.one["LAB_INVERT"])], axis=1)
        o["clr_polarity"] = np.stack([bits[self.clr_inv[k]] if self.clr_inv_av else 1 - bits[self.clr_inv[k]] for k in sorted(self.clr_inv)], axis=1)
        return o

    @staticmethod
    def val(cell_av, bits):
        c, av = cell_av
        return bits[c] if av else 1 - bits[c]

    def le_val(self, bits):
        """{group name: int [labs, 16]} vendor VALUE of each per-LE selection (bit undone through arch_value)."""
        return {n: (bits[c] if av else 1 - bits[c]) for n, (c, av) in self.le.items()}
