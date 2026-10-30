"""Clean Cyclone IV GX (EP4CGX150) bitstream -> flat structural Verilog (#165).  Vendor-derived decoders only; undecoded = explicit, counted.

Pipeline per image (all decoders are the sibling modules; nothing here is fitted):
  tracer       programmed routing edges (vendor conduction rule) -> forest; a net = a programmed-edge root and everything below it
  LE_LUT_INPUT mux value = index of the driving routing element (ASM_LE_LUT_INPUT::process_atom@0x16c464): input number i < 38 =
               LOCAL_INTERCONNECT i, i >= 38 = LOCAL_LINE i - 38 of the LAB; selection value -> bits = the asmdb calc group (muxsel.MapSelect);
               gi 0..3 = DATAA..DATAD.  An unconnected input (no selection) is emitted 1'b1 (see UNCONNECTED).
  sources      LE_BUFFER 2 le + b / LOCAL_LINE le = output path; LE_REG_OUT_YGR gi 0 / 1 / 2 value 1 = LUT combout, 0 = register (reg_used.py)
  carry        LE_USE_CARRY clear = LUT C input is the carry chain; cin = cout of LE le - 1 of the same LAB
  FF           present per reg_used.py (+ a used output path that selects the register); clock = LE_CLOCK_SELECT x LAB_CLOCK_FAST_MUX (clocks.py);
               D = combout of the same LE
  IO           io_fields.py site decode; input pad = IO_DATAIN (x, y, 0, SUB_LOC); output data = BLOCK_INPUT_MUX of a VIO pad (bim.py)
  PLL / M9K / MAC  pll.py / m9k.py / mac.py parameters and content
NOT decoded (emitted as `// UNDECODED:` lines and counted, never guessed): FF enable / async clear / sync clear / sync load / clock polarity
(modelled idle, flagged on every FF), carry chains entering a LAB, HIO pad data, bidirectional OE, clock-buffer and PLL sources, M9K / MAC port
connectivity and widths, MAC mode.
"""
import collections
import json
import os
import re

import numpy as np

from . import ddb, m9k, m9kctl, mac, macctl, names, ram_mapper
from . import plane as P

# source: scripts/cycloneiv_clean_gate.py parse_vo on 16,763 corpus .vo files: every unconnected LUT input whose function depends on it is VCC
#         (datad of arithmetic LEs: 410 of 410 dependent cases, 0 GND); independent ones are either, so 1'b1 for all
UNCONNECTED = "1'b1"
LI_PER_LAB = 38                  # source: lab_control.Implicit (n_li counted from the routing graph tile); asserted in Emitter.__init__
GROUP_LE_INPUT = "LE_LUT_INPUT"  # source: libdb_asmdb arch-group-type table (gi 0..3, 16 sites)
LAB_BLOCK = 18                   # source: fields.PLACED
CLEAR_NONE = 10                  # source: LAB_CLEAR_FAST_MUX aux: input 10 = unconstrained second level (no source)
F_ROWS = 90                      # source: fields.ROWS_PER_COLUMN
HALF_ROWS = 18                   # source: macctl.HALF (18 x 18 mode)
LES_PER_LAB = 16                 # source: LE_LUT_INPUT groups: 16 sites
# source: routing.rcf roots of input ports on rb_000..009 (10 designs, 0 contradictions; IO_DATAIN / IO_RAW_DATAIN -> Row / Column I/O pad, CLK_BUFFER -> Dedicated Clock pad): element S index = pad SUB_LOC
PAD_SOURCES = ("IO_DATAIN", "IO_RAW_DATAIN", "CLK_BUFFER")
# source: m9k.WRITERS / RAM_FLAGS (libcomp_asmram writers): the M9K control groups decoded in m9k.py
M9K_CONTROL = ("RAM_USE_TRUE_DUAL_PORT_MODE", "RAM_USE_PACKED_MODE", "RAM_REG_DATA_OUT", "RAM_REG_DATA_OUT_B", "RAM_NEW_DATA_MODE")


def _ident(s):
    return re.sub(r"[^A-Za-z0-9_]", "_", str(s))


class LeInputs:
    """LE_LUT_INPUT selection decode: select(bits) -> int64 [labs, 16, 4] = input number per (LAB, LE, pin); -1 none, -2 ambiguous."""

    def __init__(self, lut):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        from . import fields as F, muxsel
        w = lut.walk
        gt = D.enum_tables()["arch_group_type"]
        bs = F.bases(w, LAB_BLOCK)
        tab = P.load_tables()
        gs = sorted((g for g in w.groups() if g["btype"] == LAB_BLOCK and gt.get(g["type"]) == GROUP_LE_INPUT), key=lambda g: g["gi"])
        if [g["gi"] for g in gs] != [0, 1, 2, 3]:
            raise SystemExit("LE_LUT_INPUT groups are not gi 0..3")
        self.m = [[muxsel.MapSelect(w, g, bs, le, tab) for le in range(16)] for g in gs]

    def select(self, bits):
        return np.stack([np.stack([self.m[gi][le].select(bits) for le in range(16)], axis=1) for gi in range(4)], axis=2)


class Ctx:
    """Design-independent state (one per process; read-only after construction, shared by worker threads)."""

    def __init__(self, tracer=None):
        from . import tracer as T
        self.T = T
        self.tr = tracer or T.Tracer()
        self.st, self.lut, self.ext, self.io = self.tr.st, self.tr.lut, self.tr.ext, self.tr.io
        self.rt = rt = self.ext.clocks.rt
        self.enum = np.where(rt.tpl >= 0, rt.enum[np.maximum(rt.tpl, 0)].astype(np.int32), -1)
        self.tname = {v: k for k, v in names.enums().items()}
        self.keys = rt.element_keys()
        self.order = np.argsort(self.keys, kind="stable")
        self.skeys = self.keys[self.order]
        xs = np.asarray(self.lut.xs)
        nlab = len(self.lut.xs) * 90
        lab = np.arange(nlab)
        self.lx, self.ly = xs[lab // 90].astype(np.int64), (lab % 90 + 1).astype(np.int64)
        self.leinp = LeInputs(self.lut)
        from . import ffctl
        self.ffc = ffctl.FfCtl(self.lut, self.rt, self.ext.clocks)
        from . import macctl
        self.macctl = macctl.MacCtl(self.lut.walk)
        from . import m9kctl
        self.m9kctl = m9kctl.M9kCtl(self.lut.walk)
        tile = (rt.x == xs[len(xs) // 2]) & (rt.y == 45)
        if int((tile & (self.enum == names.enum_of("LOCAL_INTERCONNECT"))).sum()) != LI_PER_LAB:
            raise SystemExit("LI_PER_LAB differs from the routing graph")
        e_li, e_ll = names.enum_of("LOCAL_INTERCONNECT"), names.enum_of("LOCAL_LINE")
        e_buf = names.enum_of("LE_BUFFER")
        self.ll_rec = np.stack([self.find(e_ll, self.lx, self.ly, 0, le) for le in range(16)], axis=1)
        self.li_rec = np.stack([self.find(e_li, self.lx, self.ly, 0, i) for i in range(LI_PER_LAB)], axis=1)
        self.buf_rec = self.ext.reg.buf                               # [labs, 16, 2]
        self.e_buf = e_buf
        self._pads_by = {}
        self.pads = self.pads_of(896)
        self._hard_tables()
        self.lab_of = {(int(x), int(y)): i for i, (x, y) in enumerate(zip(self.lx, self.ly))}

    def _hard_tables(self):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        from . import asmdb_walk as W, fields as F, io_decode as ID, io_fields as IF, m9k, pll
        w = self.lut.walk
        flds = F.fields(w, D.enum_tables())
        self.io_table = json.load(open(ID.DECODE_PATH))
        self.io_dec = IF.Decoder(self.io_table)
        self.io_cram_names = sorted({e["group"] for e in self.io_table["cram_values"]})
        self.pllmap = pll.PllMap(flds)
        from . import io_line
        gt = D.enum_tables()["arch_group_type"]
        self.hio_data = io_line.Line(w, gt, 5, "MIO_LABLINE_TO_DATA", 0)         # HIO pad data / OE source (docs/cycloneiv-clean-emit.md)
        self.hio_oe = io_line.Line(w, gt, 5, "MIO_LABLINE_TO_OE")
        tab = P.load_tables()

        def cell(a):
            r, j, k = P.sof_to_rbf(a.ravel(), tab)
            return (r * P.BITS_PER_FRAME + (j - 1) * P.LANES + k).reshape(a.shape)
        bs = F.bases(w, m9k.MEAB)
        self._m9k_cells = cell(F.absolute(bs, m9k.content_offsets(flds)))      # [720, 9216]
        self.m9k_ctl = {}
        for f in flds:
            if f.btype == m9k.MEAB and f.name in M9K_CONTROL:
                self.m9k_ctl[f.name] = cell(F.absolute(bs, np.asarray(f.sites[0][0], np.int64)))[:, 0]

    def m9k_content(self, bits):
        return bits[self._m9k_cells]

    def find(self, enum, x, y, z, i):
        q = ddb.element_key(enum, np.asarray(x, np.int64), np.asarray(y, np.int64), z, np.asarray(i, np.int64))
        q = np.broadcast_to(q, np.broadcast(np.asarray(x), np.asarray(y), np.asarray(i)).shape)
        j = np.minimum(np.searchsorted(self.skeys, q), len(self.skeys) - 1)
        return np.where(self.skeys[j] == q, self.order[j], -1)

    def pads_of(self, count):
        """Pad table of one package (pin count 484 / 672 / 896), cached."""
        if count not in self._pads_by:
            self._pads_by[count] = self._pads(count)
        return self._pads_by[count]

    def pinmap(self):
        if getattr(self, "_pinmap", None) is None:
            from . import io_pins
            self._pinmap = io_pins.PinMap(self.io, self.io_dec)
        return self._pinmap

    def _pads(self, count=896):
        """{('IO' | 'CLK', x, y, SUB_LOC): (io site | None, ball)} of one package: Row / Column I/O pads (pad table order -> IO site) and Dedicated Clock pads."""
        from . import pkgpad as K
        out = {}
        pins, pads = K.pins(count), K.pads()
        pad_site = {j: s for s, j in K.io_site_pads(pads).items()}
        for i, j in K.pin_pad(pins).items():
            m = re.fullmatch(r"X(\d+)Y(\d+)SUB_LOC(\d+)", pads[j]["strs"][1])
            if pads[j]["strs"][3] == "Dedicated Clock":
                out[("CLK",) + tuple(map(int, m.groups()))] = (None, pins[i]["strs"][0])
            elif j in pad_site:
                out[("IO",) + tuple(map(int, m.groups()))] = (pad_site[j], pins[i]["strs"][0])
        return out

    def desc(self, r):
        """(type name, x, y, z, index) of a record."""
        e, x, y, z, i = self.rt.element(int(r))
        return self.tname.get(e, f"T{e}"), x, y, z, i


class Netlist:
    def __init__(self, label):
        self.label = label
        self.luts, self.ffs, self.ios, self.srcs = [], [], [], {}     # srcs: signal name -> (type, cause)
        self.pll, self.m9k, self.mac = [], [], []
        self.und = collections.Counter()                              # cause -> count
        self.counts = collections.Counter()
        self.nets = set()                                             # distinct root records referenced by an emitted sink
        self.package, self.package_pins, self.package_info = "F896", 896, {}   # set by Builder.run (--package)


def _roots(ctx, edges):
    """parent[] of the programmed forest and a root-finder (pointer doubling)."""
    st = ctx.st
    e = np.asarray(edges, np.int64)
    parent = np.full(ctx.rt.n, -1, np.int64)
    s, d = st.esrc[e].astype(np.int64), st.edst[e].astype(np.int64)
    parent[d] = s
    conflict = int(len(d) - len(np.unique(d)))
    used_src = np.zeros(ctx.rt.n, bool)
    used_src[s] = True

    def root(rec):
        cur = np.asarray(rec, np.int64).copy()
        for _ in range(512):
            ok = cur >= 0
            p = np.where(ok, parent[np.maximum(cur, 0)], -1)
            m = p >= 0
            if not m.any():
                return cur
            cur = np.where(m, p, cur)
        raise SystemExit("routing forest: root search did not converge (loop)")
    return parent, root, used_src, conflict


class Builder:
    def __init__(self, ctx, rbf, label=None, workers=4, package="auto"):
        self.cx, self.rbf, self.package = ctx, rbf, package
        self.label = label or os.path.basename(os.path.dirname(os.path.abspath(rbf)))
        self.workers = workers

    def _choose_package(self, nl):
        """--package auto|F484|F672|F896: auto = pkginfer (refuses to guess: F896 then, with a warning); a given package that disagrees with the inferred one is used and warned about."""
        import logging
        from . import pkginfer
        log = logging.getLogger("cycloneiv_clean_emit")
        inf = pkginfer.infer(self.cx.pinmap(), self.cx.io_dec, np.fromfile(self.rbf, np.uint8))
        nl.package_info = {"inferred": inf["package"], "exact": inf["exact"], "reason": inf["reason"], "ground_sites": inf["ground_sites"]}
        if self.package == "auto":
            if inf["package"] is None:
                log.warning("package inference: %s; using F896", inf["reason"])
            nl.package = inf["package"] or "F896"
        else:
            nl.package = self.package
            if inf["package"] != self.package:
                log.warning("package %s given but the bitstream is consistent with %s (%s)", self.package, inf["package"], inf["reason"])
        nl.package_pins = pkginfer.PACKAGES[nl.package]
        nl.package_info["used"] = nl.package
        log.info("package used: %s (inferred %s, exact %s)", nl.package, inf["package"], inf["exact"])

    @staticmethod
    def _const_out(chain, bits, site):
        """Output pad whose data source selects no LOCAL_INTERCONNECT / BLOCK_INPUT_MUX = constant driver 1 xor MIO_DATA_INVERT[0]
        (case builds, HIO and VIO, 2 pads each: constant 1 '00', constant 0 '10', data-driven '00')."""
        from . import plane as PL
        r, j, k = PL.address_to_plane(np.asarray(chain.cram[site]["MIO_DATA_INVERT"], np.int64))
        return 1 - int(bits[np.asarray(r) * PL.BITS_PER_FRAME + (np.asarray(j) - 1) * 8 + np.asarray(k)][0])

    def run(self):
        cx = self.cx
        T = cx.T
        nl = Netlist(self.label)
        self._choose_package(nl)
        bits = T.plane_bits(self.rbf)
        fired = cx.ext.apply(bits, cx.st.fire(bits, workers=self.workers))
        edges = np.asarray(fired[T.HEADLINE_VARIANT])
        # MAC clock from a block clock line (MAC_CLK_FAST_MUX): the line's structural parents conduct like the LAB clock sinks
        md0 = cx.macctl.decode(bits)
        mcols0 = mac.columns()
        sel = np.flatnonzero(md0["used"] & (md0["clk_line"] >= 0) & (md0["clk_sel"] < 0))
        if len(sel):
            e_blk = names.enum_of("BLK_CLK_BUF")
            recs = [int(cx.find(e_blk, mcols0[i // F_ROWS], i % F_ROWS + 1, 0, int(md0["clk_line"][i]))) for i in sel]
            edges = np.unique(np.concatenate([edges, cx.ext.clocks.chain([r for r in recs if r >= 0])]))
        # M9K clock from a block clock line (RAM_CLOCK_FAST_MUX gi 0): same structural parents as the LAB clock sinks
        mk0 = cx.m9kctl.decode(bits)
        recs = []
        mx = m9k.columns()
        for i in np.flatnonzero((mk0["clk_fast"] != 0).any(axis=1)).tolist():
            ln = cx.m9kctl.clock_line(mk0["clk_fast"][i])
            if isinstance(ln, int):
                r = int(cx.find(names.enum_of("BLK_CLK_BUF"), mx[i // F_ROWS], i % F_ROWS + 1, 0, ln))
                if r >= 0:
                    recs.append(r)
        if recs:
            edges = np.unique(np.concatenate([edges, cx.ext.clocks.chain(recs)]))
        parent, root, used_src, conflict = _roots(cx, edges)
        nl.counts["forest_edges"], nl.counts["forest_fanin_conflicts"] = len(edges), conflict
        cells = cx.lut.cells(bits).astype(np.uint8)                      # [labs, 16, 16]
        carry = cx.lut.carry_in(bits)
        sel = cx.leinp.select(bits)
        ygr = np.stack([bits[c] == 1 for c in cx.ext.reg.ygr], axis=-1)   # [labs, 16, 3] True = LUT output
        ubuf = cx.ext.reg.used(edges)
        ffc = cx.ext.reg.ff(bits, edges)
        ll_edge = used_src[np.maximum(cx.ll_rec, 0)] & (cx.ll_rec >= 0)
        live = cells.any(-1) | (ubuf & ygr[..., :2]).any(-1) | (ll_edge & ygr[..., 2]) | ffc          # LEs that exist before the selected-LOCAL_LINE pass
        ll_used = ll_edge | self._ll_selected(live, carry & cells.any(-1), sel)         # an FF-only LE's DATAC is its D input, not the carry
        reg_out = (ubuf & ~ygr[..., :2]).any(-1) | (ll_used & ~ygr[..., 2])
        self.lsig, self.lev = cx.ffc.lab_signals(bits), cx.ffc.le_val(bits)
        # source: ASM_LE_USE_SYNC_CLEAR / _LOAD::process_atom: the shared LE bit is set only for a register whose sclr / sload term is connected -> a register exists
        sync_ff = self.lev["LE_USE_SYNC_CLEAR"] == 1
        nl.counts["ff_from_sync_bit_only"] = int((sync_ff & ~(ffc | reg_out)).sum())
        ffp = ffc | reg_out | sync_ff
        # a LUT exists when its INIT is set or a used output path selects the LUT (a constant-0 LUT); an FF-only LE has no LUT
        lut_p = cells.any(-1) | (ubuf & ygr[..., :2]).any(-1) | (ll_used & ygr[..., 2])
        self.sel_only = lut_p & ~live        # constant-0 LUT claimed only by a selected LOCAL_LINE: no GT route reaches its pins
        grp = self.lev["LE_CLOCK_SELECT"]                                   # value = clock / enable signal index = LAB_CLOCK_FAST_MUX gi (ffctl.py)
        clk = np.where(ffp, np.take_along_axis(self.lsig["clk_rec"], grp, axis=1), -1)
        # source: ASM_LAB_CLOCK_FAST_MUX::process_end_of_phase@0x15e138 writes the clock mux of every LAB signal with a real source, and
        #         ASM_LE_CLOCK_SELECT::process_atom@0x16ba06 selects it per register: a register whose selected clock mux decodes to no input
        #         (first level unconfigured) cannot exist.  Register claims by output select alone (YGR) are dropped then; sync-bit FFs are kept.
        csel = np.take_along_axis(self.lsig["clk_sel"], grp, axis=1)
        drop = ffp & (csel == -1) & ~sync_ff
        nl.counts["ff_claim_dropped_no_clock_source"] = int(drop.sum())
        ffp = ffp & ~drop
        clk = np.where(ffp, clk, -1)
        self.bits, self.edges, self.parent, self.root, self.used_src = bits, edges, parent, root, used_src
        self.cells, self.carry, self.sel, self.ygr, self.ffp, self.lut_p, self.clk = cells, carry, sel, ygr, ffp, lut_p, clk
        nl.counts["ff_claim_reg_used"], nl.counts["ff_from_used_register_output"] = int(ffc.sum()), int((ffp & ~ffc).sum())
        self.pad_names = {}
        self._signals_prepare(nl)
        self._logic(nl)
        self._io(nl, bits)
        self._hard(nl, bits, edges)
        self._close(nl)
        return nl

    @staticmethod
    def _ll_selected(live, carry, sel):
        """bool [labs, 16]: LOCAL_LINE le is selected by a LE_LUT_INPUT pin of an existing LE (`live`).  The consumer is a mux, not a routing
        edge, so `used_src` does not see it; the pin is not tested for function dependence (a dependence filter loses GT-routed pins)."""
        pin = np.broadcast_to(np.arange(4), sel.shape)
        ok = live[..., None] & ~(carry[..., None] & (pin == 2)) & (sel >= LI_PER_LAB) & (sel < LI_PER_LAB + 16)
        out = np.zeros(live.shape, bool)
        lab, le, g = np.nonzero(ok)
        out[lab, sel[lab, le, g] - LI_PER_LAB] = True
        return out

    # ---- sources -----------------------------------------------------------------------------------------------------------------
    def _signals_prepare(self, nl):
        self.mac_refs = set()
        self.m9k_refs = set()
        self.sig_cache = {}
        self.nl = nl

    def sig(self, rec, why=""):
        """Signal expression of the net containing record `rec` (-> (expr, producer tuple)); undecoded sources are declared and counted."""
        cx, nl = self.cx, self.nl
        r = int(self.root(np.asarray([rec]))[0])
        got = self.sig_cache.get(r)
        if got is None:
            got = self.sig_cache[r] = self._source(r)
        nl.nets.add(r)
        return got

    def _source(self, r):
        cx, nl = self.cx, self.nl
        t, x, y, z, i = cx.desc(r)
        if t == "LE_BUFFER":
            lab = cx.lab_of.get((x, y))
            if lab is None or i >= 32:
                return self._ext(r, t, "LE_BUFFER outside the LAB grid")
            le, b = i // 2, i % 2
            return self._le_out(lab, le, bool(self.ygr[lab, le, b]), x, y)
        if t == "LOCAL_LINE":
            lab = cx.lab_of.get((x, y))
            if lab is None or i >= 16:
                return self._ext(r, t, "LOCAL_LINE outside the LAB grid")
            return self._le_out(lab, i, bool(self.ygr[lab, i, 2]), x, y)
        if t == "M4K_BUFFER":                                   # M9K port-A data out bit i (routing.rcf: M4K_BUFFER:X<x>Y<y>S0I<bit>)
            self.m9k_refs.add((x, y))
            return (f"m9k_{x}_{y}_o[{i}]", ("M9K", x, y, i))
        if t == "DSP_BUFFER":                                   # MAC result bit i (routing.rcf: DSP_BUFFER:X<x>Y<y>S0I<bit> of the MAC tile)
            self.mac_refs.add((x, y))
            return (f"mac_{x}_{y}_r[{i}]", ("MAC", x, y, i))
        if t in PAD_SOURCES:
            p = cx.pads_of(nl.package_pins).get(("CLK" if t == "CLK_BUFFER" else "IO", x, y, z))      # SUB_LOC = the element's z (S) index
            if p is not None:
                return (f"pad_{p[1]}", ("PAD", p[1]))
            return self._ext(r, t, f"{t} with no package ball")
        return self._ext(r, t, {"CLKBUF_OUT": "global clock buffer: source pin / PLL not decoded",
                                "M4K_BUFFER": "M9K output: port wiring not decoded"}.get(t, f"source of type {t}: not decoded"))

    def _le_out(self, lab, le, comb, x, y):
        if comb or not self.ffp[lab, le]:          # register select without a register (dropped claim): the LUT output
            return (f"lc_{x}_{y}_{le}", ("LC", x, y, le))
        return (f"ff_{x}_{y}_{le}", ("FF", x, y, le))

    def _ext(self, r, t, cause):
        _, x, y, z, i = self.cx.desc(r)
        name = f"u_{_ident(t).lower()}_{x}_{y}_{z}_{i}"
        self.nl.srcs[name] = (t, cause)
        return (name, ("SRC", t, x, y, z, i))

    # ---- logic -------------------------------------------------------------------------------------------------------------------
    def _logic(self, nl):
        cx = self.cx
        labs, les = np.nonzero(self.lut_p)
        lut_at = {}
        for lab, le in zip(labs.tolist(), les.tolist()):
            lut_at[(lab, le)] = None
        for lab, le in zip(labs.tolist(), les.tolist()):
            x, y = int(cx.lx[lab]), int(cx.ly[lab])
            m = 0
            c = self.cells[lab, le]
            for l in range(16):
                m |= int(c[15 - l]) << l
            L = dict(name=f"lc_{x}_{y}_{le}", x=x, y=y, le=le, lab=lab, init=m, pins=[None] * 4, prod=[None] * 4, rec=[None] * 4,
                     cin=None, mode="datac")
            cin_mode = bool(self.carry[lab, le])
            for gi in range(4):
                s = int(self.sel[lab, le, gi])
                if gi == 2 and cin_mode:
                    L["mode"] = "cin"
                    # source: ASM_CARRY_CHAIN_MONITOR_BASIC::validate_chain_le_locations@0xfb2b6: LE n > 0 <- LE n - 1 of the same LAB; LE 0 <- LE 15 of the
                    #         LAB at Y + 1 (same X)
                    src = (lab, le - 1) if le > 0 else (lab + 1 if (lab + 1) % F_ROWS else -1, LES_PER_LAB - 1)
                    if src in lut_at:
                        sx, sy = int(cx.lx[src[0]]), int(cx.ly[src[0]])
                        L["cin"] = f"co_{sx}_{sy}_{src[1]}"
                        L["pins"][2] = L["cin"]
                        L["prod"][2] = ("CO", sx, sy, src[1])
                        nl.counts["lut_cin_from_previous_le" if le > 0 else "lut_cin_from_lab_above"] += 1
                    else:
                        L["pins"][2] = UNCONNECTED
                        nl.und["carry-in source LE has no LUT" if src[0] >= 0 else "carry-in from LE 15 of a LAB above the last row"] += 1
                        L["und"] = L.get("und", []) + ["cin"]
                    continue
                if gi == 2 and self.lev["LE_USE_REGISTER_FEEDBACK"][lab, le] and self.ffp[lab, le]:
                    # source: LE_USE_REGISTER_FEEDBACK set <-> the LE's DATAC input is its own register (ASM_LE_USE_REGISTER_FEEDBACK::process_atom@0x16c294)
                    L["pins"][2] = f"ff_{x}_{y}_{le}"
                    L["prod"][2] = ("FF", x, y, le)
                    nl.counts["lut_datac_register_feedback"] += 1
                    continue
                if s == -1 or self.sel_only[lab, le]:
                    L["pins"][gi] = UNCONNECTED
                    nl.counts["lut_pin_unconnected"] += 1
                    continue
                if s < 0:
                    L["pins"][gi] = UNCONNECTED
                    nl.und["LE_LUT_INPUT selection ambiguous / invalid"] += 1
                    L["und"] = L.get("und", []) + ["abcd"[gi]]
                    continue
                rec = int(cx.li_rec[lab, s]) if s < LI_PER_LAB else int(cx.ll_rec[lab, s - LI_PER_LAB]) if s - LI_PER_LAB < 16 else -1
                if rec < 0:
                    L["pins"][gi] = UNCONNECTED
                    nl.und["LE_LUT_INPUT selects a record absent from the graph"] += 1
                    L["und"] = L.get("und", []) + ["abcd"[gi]]
                    continue
                L["rec"][gi] = rec
                L["pins"][gi], L["prod"][gi] = self.sig(rec)
                nl.counts["lut_pin_connected"] += 1
            nl.luts.append(L)
            lut_at[(lab, le)] = L
        self.lut_at = lut_at
        # FFs
        labs, les = np.nonzero(self.ffp)
        for lab, le in zip(labs.tolist(), les.tolist()):
            x, y = int(cx.lx[lab]), int(cx.ly[lab])
            F = dict(name=f"ff_{x}_{y}_{le}", x=x, y=y, le=le, lab=lab, d=None, clk=None, clk_prod=None, clk_rec=None, und=[])
            if (lab, le) in lut_at and not (self.lev["LE_USE_SYNC_CLEAR"][lab, le] and self.lsig["sync_state"][lab] in (4, 5)):
                F["d"] = f"lc_{x}_{y}_{le}"
            else:
                # sload tied high (LAB_ENABLE_SYNC_SIGNALS state 4 / 5, LE sync bit set): D = ASDATA; FF-only LE (no LUT) is the same path
                # FF-only LE: D = ASDATA = the LE's DATAC input (gi 2); evidence: rb_000 FF-only LEs, ASDATA net = the LI selected by gi 2
                s = int(self.sel[lab, le, 2])
                rec = int(cx.li_rec[lab, s]) if 0 <= s < LI_PER_LAB else int(cx.ll_rec[lab, s - LI_PER_LAB]) if LI_PER_LAB <= s < LI_PER_LAB + 16 else -1
                if rec >= 0:
                    F["d"], F["d_prod"] = self.sig(rec)
                    nl.counts["ff_d_from_asdata"] += 1
                else:
                    F["und"].append("d: FF-only LE with no DATAC selection")
                    nl.und["FF-only LE: ASDATA source"] += 1
            b = int(self.clk[lab, le])
            if b >= 0:
                F["clk_rec"] = b
                F["clk"], F["clk_prod"] = self.sig(b)
            else:
                F["und"].append("clk")
                nl.und["FF clock: selected LAB clock mux has no selection (first level 0)"] += 1
            self._ff_controls(nl, F, lab, le)
            nl.ffs.append(F)

    def _ff_controls(self, nl, F, lab, le):
        """FF enable / async clear / sync clear / sync load / clock polarity from ffctl.py (vendor writers, value laws); fields: clk_inv, ena, aclr, sclr, sload, asdata."""
        cx, ls, lv = self.cx, self.lsig, self.lev
        g = int(lv["LE_CLOCK_SELECT"][lab, le])                  # clock and enable signal index = mux gi
        inv = ls["invert"][lab]
        # source: LAB_INVERT gi k = line k of the VIRTUAL_LAB_LINE table (ASM_LAB_MODEL_TITAN ctor@0x166e26, data @0x3cda00): 0 clk0, 1 ce0, 2 clk1, 3 ce1, 4 sload, 5 sclr (table lines 5..8, unused clock 3 and the aclr pair, are skipped);
        #         clock value 1 = inverted, ce / sload / sclr value 1 = positive (corpus 100 %, incl. an inverted-sclr build)
        sc = int(ls["clk_sel"][lab, g])
        F["clk_inv"] = bool(inv[2 * g]) ^ (0 <= sc < 4)           # a LAB_CONTROL_MUX source flips the polarity bit (look_up_signal_polarity@0x1563ae), as for aclr
        nl.counts["ff_clk_inverted" if F["clk_inv"] else "ff_clk_positive"] += 1

        def ctl(key, rec, why, sense_inv):
            if rec < 0:
                F["und"].append(key)
                nl.und[f"FF {key}: {why}"] += 1
                return
            F[key], F[key + "_prod"] = self.sig(rec)
            F[key + "_rec"], F[key + "_inv"] = rec, bool(sense_inv)
            nl.counts[f"ff_{key}_used" + ("_inverted" if sense_inv else "")] += 1
        if ls["ce_on"][lab, g]:                                     # LAB_ENABLE_CE gi g value 1 = enable g used
            ctl("ena", int(ls["ce_rec"][lab, g]), "LAB_CE_FAST_MUX selection not decoded", not inv[2 * g + 1])
        ga = int(lv["LE_CLEAR_SELECT"][lab, le])                    # aclr signal index = LAB_CLEAR_FAST_MUX gi
        sel = int(ls["aclr_sel"][lab, ga])
        if sel == CLEAR_NONE:
            nl.counts["ff_aclr_idle"] += 1
        else:
            # source: ASM_LAB_CLR_INVERT_PAIR::process_end_of_phase@0x15ee88: value bit ga = polarity; a LAB_CONTROL_MUX source flips it (look_up_signal_polarity@0x1563ae)
            ctl("aclr", int(ls["aclr_rec"][lab, ga]), "LAB_CLEAR_FAST_MUX selection not decoded", bool(ls["clr_polarity"][lab, ga]) ^ (0 <= sel < 4))
        if lv["LE_USE_SYNC_CLEAR"][lab, le]:                        # shared bit: sclr term connected OR sload term connected (ASM_LE_USE_SYNC_CLEAR / LOAD::process_atom)
            st = int(ls["sync_state"][lab])
            if st in (2, 3, 5):
                ctl("sclr", int(ls["sclr_rec"][lab]), "LAB_SYNC_CLR_FAST_MUX selection not decoded", not ls["invert"][lab, 5])
            if st in (4, 5):
                F["sload_vcc"] = True                                 # FF-only LE: sload tied high, D = ASDATA (state 4 / 5)
                nl.counts["ff_sload_vcc"] += 1
            if st in (1, 3):
                ctl("sload", int(ls["sload_rec"][lab]), "LAB_SYNC_LOAD_FAST_MUX_MAG selection not decoded", not inv[4])
                s = int(self.sel[lab, le, 2])                         # asdata = the LE's DATAC input
                rec = int(cx.li_rec[lab, s]) if 0 <= s < LI_PER_LAB else int(cx.ll_rec[lab, s - LI_PER_LAB]) if LI_PER_LAB <= s < LI_PER_LAB + 16 else -1
                if rec >= 0:
                    F["asdata"], F["asdata_prod"] = self.sig(rec)
                    F["asdata_rec"] = rec
                else:
                    F["und"].append("asdata")
                    nl.und["FF sync load: ASDATA (DATAC) source"] += 1
            if st == -1:
                F["und"].append("sync")
                nl.und["FF sync controls: LAB_ENABLE_SYNC_SIGNALS state not in the vendor value table"] += 1
        nl.counts["ff_power_up_low"] += 1                           # no power-up configuration group exists (ASM_REG_POWER_UP_MONITOR writes no bits); all corpus FFs are `low`

    # ---- IO ----------------------------------------------------------------------------------------------------------------------
    def _io(self, nl, bits):
        cx = self.cx
        from . import bim as B
        from . import io_decode as ID
        from . import io_fields as IF
        from . import plane as PL
        table = cx.io_table
        dec = cx.io_dec
        chain = cx.io.chain
        val, _ = cx.io.cff.read(self.rbf)
        site_ball = {p[0]: p[1] for k, p in cx.pads_of(nl.package_pins).items() if k[0] == "IO"}
        pos = {}
        for site, (name, fn) in chain.site_pad.items():
            m = re.fullmatch(r"X(\d+)Y(\d+)SUB_LOC(\d+)", name)
            pos[site] = tuple(map(int, m.groups()))
        e_bim = names.enum_of("BLOCK_INPUT_MUX")
        for site in sorted(chain.cff):
            vec = ID.site_vector(chain, val, site)
            cram = {}
            for n in cx.io_cram_names:
                a = chain.cram.get(site, {}).get(n)
                if a:
                    r, j, k = PL.address_to_plane(np.asarray(a, np.int64))
                    cram[n] = "".join(str(int(b)) for b in bits[np.asarray(r) * PL.BITS_PER_FRAME + (np.asarray(j) - 1) * 8 + np.asarray(k)])
            d = dec.decode(site, vec, cram)
            nl.counts["io_sites_" + d["class"]] += 1
            if d["class"] != "used":
                if d["class"] == "MISSING":
                    nl.und["IO site: pattern matches no decoded class"] += 1
                continue
            ball = site_ball.get(site)
            if ball is None or site not in pos:
                nl.und["used IO site without package ball"] += 1
                continue
            x, y, k = pos[site]
            io = dict(ball=ball, site=site, x=x, y=y, k=k, dir=d["direction"].get("value"), fields={}, drv=None, und=[])
            for f in ("standard", "drive", "slew", "termination", "pull-up", "bus-hold", "open-drain", "registered-input", "registered-output", "registered-oe"):
                s = d[f]
                io["fields"][f] = s.get("value") if s["status"] in ("decoded", "default") else "UNDECODED" if "MISSING" in s["status"] else s["status"]
                if io["fields"][f] == "UNDECODED":
                    nl.und[f"IO {f}"] += 1
            if io["dir"] in ("output", "bidir-or-tristate"):
                if site[0] == 6:
                    sub = B.vio_pin(k)
                    rec = int(cx.find(e_bim, x + sub[0], y, 0, sub[1])) if sub else -1
                    if rec >= 0 and self.parent[rec] >= 0:
                        io["drv"], io["drv_prod"] = self.sig(rec)
                        io["drv_rec"] = rec
                    else:
                        io["const"] = self._const_out(chain, bits, site)
                        nl.counts["VIO output pad: constant driver"] += 1
                        if io["dir"] != "output":
                            io["und"].append("tri-state pad with constant data: OE not emitted")
                else:
                    li = self._hio_li(cx.hio_data, bits, site, x, y)
                    if li >= 0:
                        io["drv"], io["drv_prod"] = self.sig(li)
                        io["drv_rec"] = li
                    else:
                        io["const"] = self._const_out(chain, bits, site)
                        nl.counts["HIO output pad: constant driver"] += 1
                        if io["dir"] != "output":
                            io["und"].append("tri-state pad with constant data: OE not emitted")
            if io["dir"] == "bidir-or-tristate":
                li = self._hio_li(cx.hio_oe, bits, site, x, y) if site[0] == 5 else -1
                sub = B.vio_pin(k, "OE") if site[0] == 6 else None
                rec = int(cx.find(e_bim, x + sub[0], y, 0, sub[1])) if sub else -1
                if rec >= 0 and self.parent[rec] >= 0:
                    io["oe"], io["oe_prod"] = self.sig(rec)
                elif li >= 0:
                    io["oe"], io["oe_prod"] = self.sig(li)
                else:
                    io["und"].append("output enable")
                    nl.und["bidirectional pad: output enable not decoded"] += 1
            if io["dir"] is None:
                nl.und["IO direction"] += 1
            nl.ios.append(io)

    def _hio_li(self, line, bits, site, x, y):
        """LOCAL_INTERCONNECT record feeding a HIO pad pin (io_line.Line input number < 42 = LI index of the pad's tile), -1 if none."""
        from . import bim
        i = line.select(bits, site[1])
        return int(self.cx.find(names.enum_of("LOCAL_INTERCONNECT"), x, y, 0, i)) if 0 <= i < bim.hio_li_count() else -1

    def _mac(self, nl, md, i, x, y):
        """18 x 18 multiplier model of one MAC tile (macctl.py).  Pins come from the LOCAL_INTERCONNECT records of the tile."""
        cx = self.cx
        e_li = names.enum_of("LOCAL_INTERCONNECT")

        def pin(sel, inv=False, idle="1'b0"):
            if sel < 0:
                if sel == -2:
                    nl.und["MAC pin: ambiguous input selection"] += 1
                return idle
            rec = int(cx.find(e_li, x, y, 0, int(sel)))
            if rec < 0:
                nl.und["MAC pin: selects a LOCAL_INTERCONNECT absent from the graph"] += 1
                return idle
            e, _ = self.sig(rec)
            return f"(~{e})" if inv else e
        nine = bool(md["nine"][i])
        M = dict(x=x, y=y, inst=i, nine=nine, ireg=[bool(v) for v in md["ireg"][i]], oreg=bool(md["oreg"][i]), und=[])
        # units: 18 x 18 = one multiplier on rows 0..35; nine-bit = N0 / N1, 9 x 9 each, product bits 18 n .. 18 n + 17 (DSP_BUFFER index, GT of gxhb_mac_two_mult_w9)
        M["units"] = []
        for n in ((0, 1) if nine else (0,)):
            ar, br = macctl.rows(n, nine)
            M["units"].append(dict(n=n, w=9 if nine else HALF_ROWS,
                                   a=[pin(md["data_sel"][i, k], md["data_inv"][i, k]) for k in ar],
                                   b=[pin(md["data_sel"][i, k], md["data_inv"][i, k]) for k in br],
                                   ireg=[bool(v) for v in (md["ireg_n"][i, n] if nine else md["ireg"][i])], oreg=bool(md["oreg_n"][i, n] if nine else md["oreg"][i])))
        M["a"], M["b"] = M["units"][0]["a"], M["units"][0]["b"]
        M["sign"] = [pin(md["sign_sel"][i, k], False, "1'b0") if md["sign_sel"][i, k] >= 0 else ("1'b0" if md["unsigned"][i, k] else "1'b1") for k in (0, 1)]
        any_reg = any(u["oreg"] or any(u["ireg"]) for u in M["units"])
        if any_reg:
            if md["clk_sel"][i] >= 0:
                M["clk"] = pin(md["clk_sel"][i], bool(md["clk_inv"][i]))
            elif md["clk_line"][i] >= 0:
                rec = int(cx.find(names.enum_of("BLK_CLK_BUF"), x, y, 0, int(md["clk_line"][i])))
                M["clk"] = self.sig(rec)[0] if rec >= 0 else "1'b0"
                if rec < 0:
                    M["und"].append("clock line record absent")
            else:
                M["clk"] = "1'b0"
                M["und"].append("clock")
                nl.und["MAC clock: no PIA_TO_CLK / CLK_FAST_MUX selection"] += 1
        M["ena"] = pin(md["ena_sel"][i], bool(md["ena_inv"][i]), "1'b1")
        M["aclr"] = pin(md["aclr_sel"][i], bool(md["aclr_inv"][i]), "1'b0")
        nl.counts["mac_oreg"] += M["oreg"]
        nl.counts["mac_ireg_a"] += M["ireg"][0]
        nl.counts["mac_ireg_b"] += M["ireg"][1]
        nl.counts["mac_signed_a_static"] += int(md["sign_sel"][i, 0] < 0 and not md["unsigned"][i, 0])
        nl.counts["mac_signed_b_static"] += int(md["sign_sel"][i, 1] < 0 and not md["unsigned"][i, 1])
        nl.counts["mac_sign_dynamic"] += int((md["sign_sel"][i] >= 0).sum())
        return M

    def _m9k(self, nl, M, mk, i, x, y):
        """Behavioural single-port (port A) memory of one M9K tile (m9kctl.py); anything else is flagged and counted, not modelled."""
        cx = self.cx
        W, A, cls = int(mk["W"][i]), int(mk["A"][i]), int(mk["cls"][i])
        if W in (32, 36):                       # x32 / x36 decode as class by16 + packed bit; depth from the measured layout (m9k.depth)
            A = m9k.depth(W).bit_length() - 1
        M.update(W=W, A=A, cls=cls, modelled=False)
        why = None
        if cls < 0:
            why = "word-width class not decoded"
        elif W not in (1, 2, 4, 8, 9, 16, 18, 32, 36):
            why = f"width {W} (undecoded) not modelled"
        elif int(mk["read_groups"][i]) and W not in (32, 36):
            why = "separate read-address groups (dual-port / wide modes) not modelled"
        if why:
            M["why"] = why
            nl.und["M9K: " + why.split(" (")[0]] += 1
            return
        e_li = names.enum_of("LOCAL_INTERCONNECT")

        def pin(sel):
            if sel < 0:
                return "1'b0"
            rec = int(cx.find(e_li, x, y, 0, int(sel)))
            return self.sig(rec)[0] if rec >= 0 else "1'b0"
        # pin <-> group from the constructor tables of libcomp_asmram (ram_mapper.py): data bit k = DATAIN idx data_idx(W)[k]; address pin idx -> write-address or data group
        # x16 words take the byte-enable layout (mode 5, parity lane skipped) only with byte enables wired; otherwise the x18 layout (mode 11) carries 16 bits
        Wm = 18 if W == 16 and not bool((mk["be"][i, :2] >= 0).any()) else W
        # x32 / x36 = two x18 atoms (mode 11 each, gi 0..17 and 18..35): logical bits 0..LA-1 on the second atom's gi 18.., the rest on gi 0.. (read off the gxm9k_h32 / hb32 / hb36
        # data-pin and bus maps; input group = output buffer index; the atom order is not in the mapper tables)
        lane_a = {32: 14, 36: 18}.get(W, 0)
        if lane_a:
            idx = [18 + k if k < lane_a else k - lane_a for k in range(W)]
            gi_d = {ix: ix for ix in idx}
        else:
            idx = ram_mapper.data_idx(Wm)[:W]
            gi_d = ram_mapper.data_gi(Wm)
        M["out_idx"] = idx
        data = [pin(mk["data"][i, gi_d[ix]]) for ix in idx]
        # address bit order: port index ix is logical bit (ix - 8) mod 13 (ix 8..12 are the low bits): reproduces the low (A - 9) bits on RAM_MS_DATA_INPUT gi 12..15
        # (x1..x8), then write-address gi 12, 0..7 for A = 9, with no specimen order; the permutation itself is not in the mapper tables (checked by the sims)
        Wa = 18 if W in (32, 36) else Wm                           # x32 / x36 = two x18 atoms: address pins of the x18 mode
        asrc = ram_mapper.addr_sources(Wa)
        slot = {g: j for j, g in enumerate(m9kctl.WRITE_SLOTS)}

        def apin(ix):
            for grp, gi in asrc.get(ix, ()):
                if grp == "RAM_MS_DATA_INPUT" and mk["data"][i, gi] >= 0:
                    return pin(mk["data"][i, gi])
                if grp == "RAM_MS_WRITE_ADDRESS_INPUT" and gi in slot and mk["waddr"][i, slot[gi]] >= 0:
                    return pin(mk["waddr"][i, slot[gi]])
            return "1'b0"
        order = sorted(asrc, key=lambda ix: (ix - 8) % 13)[:A]
        addr = [apin(ix) for ix in order] if A >= 8 else []
        raddr = None
        if W in (32, 36):                                       # simple dual port: separate read address (RAM_MS_READ_ADDRESS_INPUT gi = port index)
            rg = {ix: gi for gi, ty, ix in ram_mapper.entries("RAM_MS_READ_ADDRESS_INPUT", Wa)}
            raddr = [pin(mk["raddr"][rg[ix]][i]) if ix in rg and rg[ix] in mk["raddr"] else "1'b0" for ix in sorted(rg, key=lambda ix: (ix - 8) % 13)[:A]]
        ln = cx.m9kctl.clock_line(mk["clk_fast"][i])
        if isinstance(ln, int):
            rec = int(cx.find(names.enum_of("BLK_CLK_BUF"), x, y, 0, ln))
            clk = self.sig(rec)[0] if rec >= 0 else "1'b0"
        else:                                                   # LOCAL_INTERCONNECT clock: first decoded RAM_PIA_TO_INPUT_YGR clock group
            clk = pin(mk["pia"][i, int(mk["cg"][i])])
        be = [pin(mk["be"][i, k]) if mk["be"][i, k] >= 0 else "1'b1" for k in range(2)] if W == 16 else None
        if W != 16 and (mk["be"][i, :4] >= 0).any():
            M["why"] = "byte enables of non-16-bit words not modelled"
            nl.und["M9K: byte enables of non-16-bit words"] += 1
            return
        bitsv = M["content"]
        words = m9k.read_words(bitsv, W)
        M.update(modelled=True, be=be, data=data, addr=addr, raddr=raddr, we=pin(mk["we"][i]), clk=clk, oreg=bool(mk["oreg"][i]),
                 init=[int("".join(str(int(b)) for b in r[::-1]), 2) for r in words])
        nl.counts["m9k_single_port_modelled"] += 1
        nl.counts[f"m9k_w{W}"] += 1
        nl.counts["m9k_oreg"] += M["oreg"]

    def _close(self, nl):
        """A referenced lc_ / ff_ / co_ signal without a cell is a decode inconsistency: declared as an undecoded source and counted."""
        defined = {L["name"] for L in nl.luts} | {f"co_{L['x']}_{L['y']}_{L['le']}" for L in nl.luts} | {F["name"] for F in nl.ffs}
        pat = re.compile(r"^(lc|co|ff)_\d+_\d+_\d+$")
        refs = set()
        for L in nl.luts:
            refs.update(p for p in L["pins"] if p)
        for F in nl.ffs:
            refs.update(p for p in (F["d"], F["clk"], F.get("ena"), F.get("aclr"), F.get("sclr"), F.get("sload"), F.get("asdata")) if p)
        for io in nl.ios:
            refs.update(p for p in (io.get("drv"), io.get("oe")) if p)
        for M in nl.m9k:
            if M.get("modelled"):
                for e in M["data"] + M["addr"] + [M["we"], M["clk"]] + (M.get("be") or []):
                    refs.update(re.findall(r"(?:pad|lc|ff|co|u)_\w+", e))
        for M in nl.mac:
            for e in M["a"] + M["b"] + M["sign"] + [M.get("clk", ""), M["ena"], M["aclr"]]:
                refs.update(re.findall(r"(?:pad|lc|ff|co|u)_\w+", e))
        have = {io["ball"] for io in nl.ios}
        for r in sorted(refs):
            if r.startswith("pad_") and r[4:] not in have:
                # pad read by the fabric but its IO site is not a decoded 'used' class: an input by routing (IO_DATAIN root), flagged
                nl.ios.append(dict(ball=r[4:], site=None, x=None, y=None, k=None, dir="input", fields={}, drv=None, und=["IO site class not decoded; input by routing"], dir_source="routing"))
                have.add(r[4:])
                nl.und["input pad with undecoded IO site (direction from routing only)"] += 1
        for r in sorted(refs):
            if pat.match(r) and r not in defined:
                nl.srcs[r] = ("dangling", "reference to an LE output with no emitted cell")
                nl.und["reference to an LE output with no emitted cell"] += 1

    # ---- hard blocks -------------------------------------------------------------------------------------------------------------
    def _hard(self, nl, bits, edges):
        cx = self.cx
        from . import m9k, mac, pll
        cff = cx.io.cff.read(self.rbf)[0]
        pm = cx.pllmap
        for k, bt, p in pm.used(cff):
            nl.pll.append(dict(k=k, params=pm.params(cff, bt, p)))
        nl.counts["pll_enabled"] = len(nl.pll)
        # output counters c# with a programmed PLL_BUFFER -> CLKBUF_IN edge (clkbuf.py); the input clock source (PLL_CLKIN mux) is not decoded (#175)
        icd = {v[2]: k for k, v in pll.pll_tiles().items()}
        sp = cx.st.esrc[np.asarray(edges, np.int64)].astype(np.int64)
        for r in sp[cx.enum[sp] == names.enum_of("PLL_BUFFER")].tolist():
            for pl in nl.pll:
                if pl["k"] == icd[(int(cx.rt.x[r]), int(cx.rt.y[r]))]:
                    pl.setdefault("to_clkbuf", set()).add(int(cx.rt.element(r)[4]))
        nl.und["PLL: input clock source"] += len(nl.pll)
        # M9K: used = an M4K_BUFFER with programmed fan-out or a programmed edge into an M9K-column BLOCK_INPUT_MUX / M4K_LEFT_CONTROL_INPUT
        rt = cx.rt
        st = cx.st
        e = np.asarray(edges, np.int64)
        s, d = st.esrc[e].astype(np.int64), st.edst[e].astype(np.int64)
        e_out = names.enum_of("M4K_BUFFER")
        e_in = [names.enum_of("BLOCK_INPUT_MUX"), names.enum_of("M4K_LEFT_CONTROL_INPUT")]
        cols, mcols = set(m9k.columns()), set(mac.columns())
        tiles, mtiles = set(), set()
        for arr, enums in ((s, [e_out]), (d, e_in)):
            r = arr[np.isin(cx.enum[arr], enums)]
            for x, y in set(zip(rt.x[r].tolist(), rt.y[r].tolist())):
                if x in cols and 1 <= y <= 90:
                    tiles.add((x, y))
                elif x in mcols and 1 <= y <= 90:
                    mtiles.add((x, y))
        content = cx.m9k_content(bits)                               # [720, 9216] mux-position bit values
        mk = cx.m9kctl.decode(bits)
        tiles |= {t for t in self.m9k_refs if t[0] in cols}
        for x, y in sorted(tiles):
            i = m9k.instance(x, y)
            ctl = {n: int(bits[c[i]]) for n, c in cx.m9k_ctl.items()}
            M = dict(x=x, y=y, inst=i, content=content[i], ctl=ctl)
            self._m9k(nl, M, mk, i, x, y)
            nl.m9k.append(M)
        nl.counts["m9k_used"] = len(nl.m9k)
        # MAC: used = any control cell set (macctl.py; routing cannot see it: the outputs are DSP_BUFFER elements)
        md = cx.macctl.decode(bits)
        mcols = mac.columns()
        used = set(np.flatnonzero(md["used"]).tolist()) | {mac.instance(x, y) for x, y in self.mac_refs if x in mcols}
        nl.counts["mac_used_by_bits"], nl.counts["mac_used_by_output_only"] = int(md["used"].sum()), len(used) - int(md["used"].sum())
        for i in sorted(used):
            nl.mac.append(self._mac(nl, md, i, mcols[i // F_ROWS], i % F_ROWS + 1))
        nl.counts["mac_used"] = len(nl.mac)


def verilog(nl, module="cyc4_top"):
    """Flat structural Verilog of a Netlist (one module)."""
    o = []
    w = o.append
    inputs = {io["ball"]: io for io in nl.ios if io["dir"] == "input"}
    outputs = {io["ball"]: io for io in nl.ios if io["dir"] == "output"}
    others = {io["ball"]: io for io in nl.ios if io["dir"] not in ("input", "output")}
    w(f"// pluribus cycloneiv_clean emit: {nl.label}")
    w(f"// package ball table: {nl.package} (inferred {nl.package_info.get('inferred')}, exact {nl.package_info.get('exact')})")
    w("// flat structural netlist; `// UNDECODED:` lines mark pieces the decoders do not cover (counts below)")
    w("// FF model (dffeas): async clear, then on clk edge with ena: sclr -> 0, sload -> asdata, else d; power-up 0; controls decoded per FF (ffctl.py)")
    for k, v in sorted(nl.und.items()):
        w(f"// UNDECODED count: {k}: {v}")
    ports = [f"input wire pad_{b}" for b in sorted(inputs)] + [f"output wire pad_{b}" for b in sorted(outputs)] + \
            [f"inout wire pad_{b}" for b in sorted(others)] + \
            [f"input wire {n} /* UNDECODED: {c} */" for n, (_t, c) in sorted(nl.srcs.items())]
    w("// LUT output delay (empty = zero-delay netlist); a LUT fed by the clock pad changes after the register samples in hardware: compile with -DLUT_DELAY=#1")
    w("`ifndef LUT_DELAY\n`define LUT_DELAY\n`endif")
    w(f"module {module} (")
    w("  " + ",\n  ".join(ports) if ports else "")
    w(");")
    w(f"// UNDECODED sources declared as input ports: {len(nl.srcs)}")
    w("// declarations")
    for L in nl.luts:
        w(f"wire {L['name']}; wire co_{L['x']}_{L['y']}_{L['le']};")
    for F in nl.ffs:
        w(f"reg {F['name']} = 1'b0;")
    for m in nl.m9k:
        if m.get("modelled"):
            n = f"m9k_{m['x']}_{m['y']}"
            w(f"wire [{m['W'] - 1}:0] {n}_q;")
            # _o = output bus indexed by M4K_BUFFER index = DATAIN idx of the width (ram_mapper.data_idx: x16 skips idx 8)
            w(f"wire [35:0] {n}_o;")
            for k, ix in enumerate(m["out_idx"]):
                w(f"assign {n}_o[{ix}] = {n}_q[{k}];")
            top = [j for j in range(36) if j not in m["out_idx"]]
            for j in top:
                w(f"assign {n}_o[{j}] = 1'b0;")
        else:
            w(f"wire [35:0] m9k_{m['x']}_{m['y']}_q = 36'b0; // UNDECODED: M9K not modelled ({m.get('why', '')})")
            w(f"wire [35:0] m9k_{m['x']}_{m['y']}_o = m9k_{m['x']}_{m['y']}_q;")
    for m in nl.mac:
        w(f"wire [35:0] mac_{m['x']}_{m['y']}_r;")
    w("// LUTs: localparam INIT bit index = {datad, datac, datab, dataa}; carry mode: C input = carry in, cout = INIT[{1'b0, cin, b, a}]")
    for L in nl.luts:
        n = L["name"]
        a_, b_, c_, d_ = L["pins"]
        und = L.get("und")
        w(f"localparam [15:0] I_{n} = 16'h{L['init']:04X};" + (f" // UNDECODED: {', '.join(und)}" if und else ""))
        w(f"assign `LUT_DELAY {n} = I_{n}[{{{d_}, {c_}, {b_}, {a_}}}];")
        if L["mode"] == "cin":
            w(f"assign `LUT_DELAY co_{L['x']}_{L['y']}_{L['le']} = I_{n}[{{1'b0, {c_}, {b_}, {a_}}}];")
        else:
            # source: cycloneiv_atoms.v cycloneiv_lcell_comb: cout = lut4(mask, dataa, datab, cin, 1'b0) in every mode; a LE not using the chain has cin = gnd
            #         (LE_USE_CARRY set: carry-in term unconnected, ASM_LE_USE_CARRY::process_atom@0x16c186)
            w(f"assign `LUT_DELAY co_{L['x']}_{L['y']}_{L['le']} = I_{n}[{{1'b0, 1'b0, {b_}, {a_}}}];")
    for F in nl.ffs:
        n = F["name"]
        if F["clk"] is not None and F["d"] is not None:
            def x(key, idle):
                return idle if F.get(key) is None else (f"(~{F[key]})" if F.get(key + "_inv") else F[key])
            clk = f"(~{F['clk']})" if F.get("clk_inv") else F["clk"]
            clrn, ena, sclr, sload, asd = x("aclr", "1'b1"), x("ena", "1'b1"), x("sclr", "1'b0"), x("sload", "1'b0"), F.get("asdata") or "1'b0"
            ev = f"posedge {clk}" + (f" or negedge {clrn}" if F.get("aclr") is not None else "")
            body = f"{n} <= {sclr} ? 1'b0 : {sload} ? {asd} : {F['d']};"
            body = body.replace(f"{sclr} ? 1'b0 : ", "") if F.get("sclr") is None else body
            body = body.replace(f"{sload} ? {asd} : ", "") if F.get("sload") is None else body
            w(f"always @({ev}) begin" + (f" if (!{clrn}) {n} <= 1'b0; else" if F.get("aclr") is not None else "") +
              (f" if ({ena}) " if F.get("ena") is not None else " ") + body + " end" + (f" // UNDECODED: {'; '.join(F['und'])}" if F["und"] else ""))
        else:
            w(f"// UNDECODED: {n} has no clock or D source ({'; '.join(F['und'])}); register not clocked")
    for io in nl.ios:
        pn = f"pad_{io['ball']}"
        info = " ".join(f"{k}={v}" for k, v in io["fields"].items() if v not in (None, "OFF"))
        w(f"// IO {pn} site {io['x']},{io['y']},{io['k']} dir={io['dir']} {info}" + (" // UNDECODED: " + "; ".join(io["und"]) if io["und"] and io["dir"] == "input" else ""))
        if io["dir"] == "output" and io.get("const") is not None:
            w(f"assign {pn} = 1'b{io['const']};")
        elif io["dir"] == "output" and io["drv"] is not None:
            w(f"assign {pn} = {io['drv']};")
        elif io["dir"] == "bidir-or-tristate" and io.get("drv") is not None and io.get("oe") is not None:
            w(f"assign {pn} = {io['oe']} ? {io['drv']} : 1'bz;")
        elif io["dir"] in ("output", "bidir-or-tristate"):
            w(f"// UNDECODED: {pn}: {'; '.join(io['und'])}")
    for p in nl.pll:
        w(f"// PLL_{p['k']}: " + " ".join(f"{k}={list(v) if isinstance(v, tuple) else v}" for k, v in p["params"].items()))
        w(f"// PLL_{p['k']} counters feeding clock buffers: " + (" ".join(f"c{c}" for c in sorted(p.get("to_clkbuf", ()))) or "none"))
        w(f"// UNDECODED: PLL_{p['k']} input clock source")
    for m in nl.m9k:
        if m.get("modelled"):
            n = f"m9k_{m['x']}_{m['y']}"
            W, A = m["W"], m["A"]
            w(f"// M9K {n}: single port, {W} bit x {1 << A} words, output register = {m['oreg']}")
            w(f"reg [{W - 1}:0] {n}_mem [0:{(1 << A) - 1}];")
            w(f"initial begin " + " ".join(f"{n}_mem[{k}] = {W}'h{v:X};" for k, v in enumerate(m["init"])) + " end")
            w(f"wire [{A - 1}:0] {n}_ad = {{{', '.join(reversed(m['addr']))}}};")
            w(f"wire [{W - 1}:0] {n}_di = {{{', '.join(reversed(m['data']))}}};")
            if m.get("raddr"):
                w(f"wire [{A - 1}:0] {n}_rd = {{{', '.join(reversed(m['raddr']))}}};")
            rd = f"{n}_rd" if m.get("raddr") else f"{n}_ad"
            w(f"reg [{A - 1}:0] {n}_ar = 0; reg [{W - 1}:0] {n}_qr = 0;")
            if m.get("be"):
                wr = f"if ({m['we']}) begin if ({m['be'][0]}) {n}_mem[{n}_ad][7:0] <= {n}_di[7:0]; if ({m['be'][1]}) {n}_mem[{n}_ad][15:8] <= {n}_di[15:8]; end"
            else:
                wr = f"if ({m['we']}) {n}_mem[{n}_ad] <= {n}_di;"
            w(f"always @(posedge {m['clk']}) begin {n}_ar <= {rd}; {wr} {n}_qr <= {n}_mem[{n}_ar]; end")
            w(f"assign {n}_q = " + (f"{n}_qr;" if m["oreg"] else f"{n}_mem[{n}_ar];"))
            continue
        bitsv = m["content"]
        hexv = int("".join(str(int(b)) for b in bitsv[::-1]), 2) if bitsv.any() else 0
        w(f"// M9K x={m['x']} y={m['y']} ctl={json.dumps(m['ctl'], sort_keys=True)}")
        w(f"localparam [9215:0] M9K_{m['x']}_{m['y']}_INIT = 9216'h{hexv:X}; // bit p = RAM_CONTENT mux position p")
        w(f"// UNDECODED: M9K {m['x']},{m['y']} port widths, port wiring, read/write mode")
    for m in nl.mac:
        n = f"mac_{m['x']}_{m['y']}"
        w(f"// MAC {n}: {'two 9 x 9' if m['nine'] else '18 x 18'}, " + ", ".join(f"N{u['n']} input regs A/B = {u['ireg']} output reg = {u['oreg']}" for u in m["units"]) + (f" // UNDECODED: {'; '.join(m['und'])}" if m["und"] else ""))
        w(f"wire {n}_sa = {m['sign'][0]}, {n}_sb = {m['sign'][1]};")
        w(f"reg [35:0] {n}_q = 36'b0; wire [35:0] {n}_pw;")
        regs = []
        for u in m["units"]:
            k, W9 = f"{n}_u{u['n']}", u["w"]
            w(f"wire [{W9 - 1}:0] {k}_a = {{{', '.join(reversed(u['a']))}}};")
            w(f"wire [{W9 - 1}:0] {k}_b = {{{', '.join(reversed(u['b']))}}};")
            w(f"reg [{W9 - 1}:0] {k}_ar = {W9}'b0, {k}_br = {W9}'b0;")
            w(f"wire [{W9 - 1}:0] {k}_ax = {k}_{'ar' if u['ireg'][0] else 'a'};")
            w(f"wire [{W9 - 1}:0] {k}_bx = {k}_{'br' if u['ireg'][1] else 'b'};")
            w(f"wire signed [{W9}:0] {k}_xa = {{{n}_sa & {k}_ax[{W9 - 1}], {k}_ax}}, {k}_xb = {{{n}_sb & {k}_bx[{W9 - 1}], {k}_bx}};")
            w(f"wire signed [{2 * W9 + 1}:0] {k}_p = {k}_xa * {k}_xb;")
            lo = 18 * u["n"] if m["nine"] else 0
            w(f"assign {n}_pw[{lo + 2 * W9 - 1}:{lo}] = {k}_p[{2 * W9 - 1}:0];")
            w(f"assign {n}_r[{lo + 2 * W9 - 1}:{lo}] = " + (f"{n}_q[{lo + 2 * W9 - 1}:{lo}];" if u["oreg"] else f"{n}_pw[{lo + 2 * W9 - 1}:{lo}];"))
            regs.append((k, u))
        if any(u["oreg"] or any(u["ireg"]) for u in m["units"]):
            ev = f"posedge {m['clk']}" + ("" if m["aclr"] == "1'b0" else f" or posedge {m['aclr']}")
            clr = "" if m["aclr"] == "1'b0" else f"if ({m['aclr']}) begin " + " ".join(f"{k}_ar <= 0; {k}_br <= 0;" for k, _ in regs) + f" {n}_q <= 36'b0; end else "
            w(f"always @({ev}) {clr}if ({m['ena']}) begin " + " ".join(f"{k}_ar <= {k}_a; {k}_br <= {k}_b;" for k, _ in regs) + f" {n}_q <= {n}_pw; end")
    w("endmodule")
    return "\n".join(o) + "\n"


def summary(nl):
    c = nl.counts
    return {"luts": len(nl.luts), "luts_carry_mode": sum(1 for L in nl.luts if L["mode"] == "cin"), "ffs": len(nl.ffs),
            "nets_referenced": len(nl.nets), "io_pads": len(nl.ios), "pll": len(nl.pll), "m9k": len(nl.m9k), "mac": len(nl.mac),
            "package": nl.package_info,
            "undecoded_sources": len(nl.srcs), "undecoded": dict(nl.und), "counts": dict(c)}
