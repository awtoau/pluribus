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

from . import ddb, names
from . import plane as P

# source: scripts/cycloneiv_clean_gate.py parse_vo on 16,763 corpus .vo files: every unconnected LUT input whose function depends on it is VCC
#         (datad of arithmetic LEs: 410 of 410 dependent cases, 0 GND); independent ones are either, so 1'b1 for all
UNCONNECTED = "1'b1"
LI_PER_LAB = 38                  # source: lab_control.Implicit (n_li counted from the routing graph tile); asserted in Emitter.__init__
GROUP_LE_INPUT = "LE_LUT_INPUT"  # source: libdb_asmdb arch-group-type table (gi 0..3, 16 sites)
LAB_BLOCK = 18                   # source: fields.PLACED
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
        tile = (rt.x == xs[len(xs) // 2]) & (rt.y == 45)
        if int((tile & (self.enum == names.enum_of("LOCAL_INTERCONNECT"))).sum()) != LI_PER_LAB:
            raise SystemExit("LI_PER_LAB differs from the routing graph")
        e_li, e_ll = names.enum_of("LOCAL_INTERCONNECT"), names.enum_of("LOCAL_LINE")
        e_buf = names.enum_of("LE_BUFFER")
        self.ll_rec = np.stack([self.find(e_ll, self.lx, self.ly, 0, le) for le in range(16)], axis=1)
        self.li_rec = np.stack([self.find(e_li, self.lx, self.ly, 0, i) for i in range(LI_PER_LAB)], axis=1)
        self.buf_rec = self.ext.reg.buf                               # [labs, 16, 2]
        self.e_buf = e_buf
        self.pads = self._pads()
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

    def _pads(self):
        """{('IO' | 'CLK', x, y, SUB_LOC): (io site | None, ball)}: Row / Column I/O pads (io chain) and Dedicated Clock pads (pkgpad site string)."""
        from . import pkgpad as K
        out = {}
        for site, b in ((s, b) for b, s in self.io.chain.ball_site.items() if s):
            m = re.fullmatch(r"X(\d+)Y(\d+)SUB_LOC(\d+)", self.io.chain.site_pad[site][0])
            out[("IO",) + tuple(map(int, m.groups()))] = (site, b)
        pins, pads = K.pins(), K.pads()
        for i, j in K.pin_pad_rank(pins).items():
            if pads[j]["strs"][3] == "Dedicated Clock":
                m = re.fullmatch(r"X(\d+)Y(\d+)SUB_LOC(\d+)", pads[j]["strs"][1])
                out[("CLK",) + tuple(map(int, m.groups()))] = (None, pins[i]["strs"][0])
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
    def __init__(self, ctx, rbf, label=None, workers=4):
        self.cx, self.rbf = ctx, rbf
        self.label = label or os.path.basename(os.path.dirname(os.path.abspath(rbf)))
        self.workers = workers

    def run(self):
        cx = self.cx
        T = cx.T
        nl = Netlist(self.label)
        bits = T.plane_bits(self.rbf)
        fired = cx.ext.apply(bits, cx.st.fire(bits, workers=self.workers))
        edges = np.asarray(fired[T.HEADLINE_VARIANT])
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
        ffp = ffc | reg_out
        # a LUT exists when its INIT is set or a used output path selects the LUT (a constant-0 LUT); an FF-only LE has no LUT
        lut_p = cells.any(-1) | (ubuf & ygr[..., :2]).any(-1) | (ll_used & ygr[..., 2])
        clk = np.where(ffp, cx.ext.clocks.le_blk(bits), -1)
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
        if t in PAD_SOURCES:
            p = cx.pads.get(("CLK" if t == "CLK_BUFFER" else "IO", x, y, z))      # SUB_LOC = the element's z (S) index
            if p is not None:
                return (f"pad_{p[1]}", ("PAD", p[1]))
            return self._ext(r, t, f"{t} with no package ball")
        return self._ext(r, t, {"CLKBUF_OUT": "global clock buffer: source pin / PLL not decoded",
                                "M4K_BUFFER": "M9K output: port wiring not decoded"}.get(t, f"source of type {t}: not decoded"))

    def _le_out(self, lab, le, comb, x, y):
        if comb:
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
                    if le > 0 and (lab, le - 1) in lut_at:
                        L["cin"] = f"co_{x}_{y}_{le - 1}"
                        L["pins"][2] = L["cin"]
                        L["prod"][2] = ("CO", x, y, le - 1)
                        nl.counts["lut_cin_from_previous_le"] += 1
                    else:
                        L["pins"][2] = UNCONNECTED
                        nl.und["carry chain entering a LAB / previous LE not a LUT"] += 1
                        L["und"] = L.get("und", []) + ["cin"]
                    continue
                if s == -1:
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
        # FFs
        labs, les = np.nonzero(self.ffp)
        for lab, le in zip(labs.tolist(), les.tolist()):
            x, y = int(cx.lx[lab]), int(cx.ly[lab])
            F = dict(name=f"ff_{x}_{y}_{le}", x=x, y=y, le=le, lab=lab, d=None, clk=None, clk_prod=None, clk_rec=None, und=[])
            if (lab, le) in lut_at:
                F["d"] = f"lc_{x}_{y}_{le}"
            else:
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
                nl.und["FF clock line (no LAB clock mux selection)"] += 1
            for k in ("enable", "async clear", "sync clear", "sync load", "clock polarity", "power-up level"):
                nl.und[f"FF {k} (modelled idle)"] += 1
            nl.ffs.append(F)

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
            ball = next((b for b, s in chain.ball_site.items() if s == site), None)
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
                    sub = B.SUB_LOC_BIM.get(k)
                    rec = int(cx.find(e_bim, x + sub[0], y, 0, sub[1])) if sub else -1
                    if rec >= 0 and self.parent[rec] >= 0:
                        io["drv"], io["drv_prod"] = self.sig(rec)
                        io["drv_rec"] = rec
                    else:
                        io["und"].append("output data: BLOCK_INPUT_MUX not programmed")
                        nl.und["VIO output pad: data mux not programmed / SUB_LOC not mapped"] += 1
                else:
                    li = self._hio_li(cx.hio_data, bits, site, x, y)
                    if li >= 0:
                        io["drv"], io["drv_prod"] = self.sig(li)
                        io["drv_rec"] = li
                    else:
                        io["und"].append("output data: HIO MIO_LABLINE_TO_DATA selects no LOCAL_INTERCONNECT")
                        nl.und["HIO output pad: data mux selects no LOCAL_INTERCONNECT"] += 1
            if io["dir"] == "bidir-or-tristate":
                li = self._hio_li(cx.hio_oe, bits, site, x, y) if site[0] == 5 else -1
                if li >= 0:
                    io["oe"], io["oe_prod"] = self.sig(li)
                else:
                    io["und"].append("output enable")
                    nl.und["bidirectional pad: output enable not decoded"] += 1
            if io["dir"] is None:
                nl.und["IO direction"] += 1
            nl.ios.append(io)

    def _hio_li(self, line, bits, site, x, y):
        """LOCAL_INTERCONNECT record feeding a HIO pad pin (io_line.Line input number < 38 = LI index of the pad's tile), -1 if none."""
        i = line.select(bits, site[1])
        return int(self.cx.find(names.enum_of("LOCAL_INTERCONNECT"), x, y, 0, i)) if 0 <= i < LI_PER_LAB else -1

    def _close(self, nl):
        """A referenced lc_ / ff_ / co_ signal without a cell is a decode inconsistency: declared as an undecoded source and counted."""
        defined = {L["name"] for L in nl.luts} | {f"co_{L['x']}_{L['y']}_{L['le']}" for L in nl.luts} | {F["name"] for F in nl.ffs}
        pat = re.compile(r"^(lc|co|ff)_\d+_\d+_\d+$")
        refs = set()
        for L in nl.luts:
            refs.update(p for p in L["pins"] if p)
        for F in nl.ffs:
            refs.update(p for p in (F["d"], F["clk"]) if p)
        for io in nl.ios:
            refs.update(p for p in (io.get("drv"), io.get("oe")) if p)
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
        nl.und["PLL: input clock / output-to-clock-buffer connectivity"] += len(nl.pll)
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
        for x, y in sorted(tiles):
            i = m9k.instance(x, y)
            ctl = {n: int(bits[c[i]]) for n, c in cx.m9k_ctl.items()}
            nl.m9k.append(dict(x=x, y=y, inst=i, content=content[i], ctl=ctl))
        nl.counts["m9k_used"] = len(nl.m9k)
        nl.und["M9K: port widths / connectivity / modes beyond TDP, packed"] += len(nl.m9k)
        # MAC: same block-boundary element types in a MUL column
        for x, y in sorted(mtiles):
            nl.mac.append(dict(x=x, y=y, inst=mac.instance(x, y)))
        nl.counts["mac_used"] = len(nl.mac)
        nl.und["MAC: mode / registers / connectivity"] += len(nl.mac)


def verilog(nl, module="cyc4_top"):
    """Flat structural Verilog of a Netlist (one module)."""
    o = []
    w = o.append
    inputs = {io["ball"]: io for io in nl.ios if io["dir"] == "input"}
    outputs = {io["ball"]: io for io in nl.ios if io["dir"] == "output"}
    others = {io["ball"]: io for io in nl.ios if io["dir"] not in ("input", "output")}
    w(f"// pluribus cycloneiv_clean emit: {nl.label}")
    w("// flat structural netlist; `// UNDECODED:` lines mark pieces the decoders do not cover (counts below)")
    w("// FF model: posedge, power-up 0, enable / clear / sync-clear / sync-load idle")
    for k, v in sorted(nl.und.items()):
        w(f"// UNDECODED count: {k}: {v}")
    ports = [f"input wire pad_{b}" for b in sorted(inputs)] + [f"output wire pad_{b}" for b in sorted(outputs)] + \
            [f"inout wire pad_{b}" for b in sorted(others)] + \
            [f"input wire {n} /* UNDECODED: {c} */" for n, (_t, c) in sorted(nl.srcs.items())]
    w(f"module {module} (")
    w("  " + ",\n  ".join(ports) if ports else "")
    w(");")
    w(f"// UNDECODED sources declared as input ports: {len(nl.srcs)}")
    w("// declarations")
    for L in nl.luts:
        w(f"wire {L['name']}; wire co_{L['x']}_{L['y']}_{L['le']};")
    for F in nl.ffs:
        w(f"reg {F['name']} = 1'b0;")
    w("// LUTs: localparam INIT bit index = {datad, datac, datab, dataa}; carry mode: C input = carry in, cout = INIT[{1'b0, cin, b, a}]")
    for L in nl.luts:
        n = L["name"]
        a_, b_, c_, d_ = L["pins"]
        und = L.get("und")
        w(f"localparam [15:0] I_{n} = 16'h{L['init']:04X};" + (f" // UNDECODED: {', '.join(und)}" if und else ""))
        w(f"assign {n} = I_{n}[{{{d_}, {c_}, {b_}, {a_}}}];")
        if L["mode"] == "cin":
            w(f"assign co_{L['x']}_{L['y']}_{L['le']} = I_{n}[{{1'b0, {c_}, {b_}, {a_}}}];")
        else:
            w(f"assign co_{L['x']}_{L['y']}_{L['le']} = 1'b0;")
    for F in nl.ffs:
        n = F["name"]
        if F["clk"] is not None and F["d"] is not None:
            w(f"always @(posedge {F['clk']}) {n} <= {F['d']}; // UNDECODED: enable, clears, sync load, clock polarity (idle)" + (f"; {'; '.join(F['und'])}" if F["und"] else ""))
        else:
            w(f"// UNDECODED: {n} has no clock or D source ({'; '.join(F['und'])}); register not clocked")
    for io in nl.ios:
        pn = f"pad_{io['ball']}"
        info = " ".join(f"{k}={v}" for k, v in io["fields"].items() if v not in (None, "OFF"))
        w(f"// IO {pn} site {io['x']},{io['y']},{io['k']} dir={io['dir']} {info}" + (" // UNDECODED: " + "; ".join(io["und"]) if io["und"] and io["dir"] == "input" else ""))
        if io["dir"] == "output" and io["drv"] is not None:
            w(f"assign {pn} = {io['drv']};")
        elif io["dir"] == "bidir-or-tristate" and io.get("drv") is not None and io.get("oe") is not None:
            w(f"assign {pn} = {io['oe']} ? {io['drv']} : 1'bz;")
        elif io["dir"] in ("output", "bidir-or-tristate"):
            w(f"// UNDECODED: {pn}: {'; '.join(io['und'])}")
    for p in nl.pll:
        w(f"// PLL_{p['k']}: " + " ".join(f"{k}={list(v) if isinstance(v, tuple) else v}" for k, v in p["params"].items()))
        w(f"// UNDECODED: PLL_{p['k']} input clock and output-to-clock-buffer connectivity")
    for m in nl.m9k:
        bitsv = m["content"]
        hexv = int("".join(str(int(b)) for b in bitsv[::-1]), 2) if bitsv.any() else 0
        w(f"// M9K x={m['x']} y={m['y']} ctl={json.dumps(m['ctl'], sort_keys=True)}")
        w(f"localparam [9215:0] M9K_{m['x']}_{m['y']}_INIT = 9216'h{hexv:X}; // bit p = RAM_CONTENT mux position p")
        w(f"// UNDECODED: M9K {m['x']},{m['y']} port widths, port wiring, read/write mode")
    for m in nl.mac:
        w(f"// UNDECODED: MAC x={m['x']} y={m['y']} mode, registers, connectivity (no behavioural multiplier)")
    w("endmodule")
    return "\n".join(o) + "\n"


def summary(nl):
    c = nl.counts
    return {"luts": len(nl.luts), "luts_carry_mode": sum(1 for L in nl.luts if L["mode"] == "cin"), "ffs": len(nl.ffs),
            "nets_referenced": len(nl.nets), "io_pads": len(nl.ios), "pll": len(nl.pll), "m9k": len(nl.m9k), "mac": len(nl.mac),
            "undecoded_sources": len(nl.srcs), "undecoded": dict(nl.und), "counts": dict(c)}
