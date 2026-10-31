"""LOCAL_INTERCONNECT -> BLOCK_INPUT_MUX edges of the IO pad pins, VIO (block type 6) and HIO (5) (#165, #171).  Vendor-derived only.

The routing graph has no fan-out for LOCAL_INTERCONNECT, and BLOCK_INPUT_MUX records carry no asm.ddb groups, so these edges are decoded here:
  - Site s of an IO group = pad s of its kind (pkgpad.io_site_pads); the pad names its tile and SUB_LOC k.
  - Pin -> BLOCK_INPUT_MUX index: routing.ddb block interface nodes (blockiface.py): interface VIO_L / VIO_R / HIO, connection to element IO
    (port type, z = SUB_LOC, index).  Pin <-> asm group (source: ASMIO_MIO_LABLINE_TO_*::process_atom, libcomp_asmio): see PINS.
  - The group selects the LOCAL_INTERCONNECT index (input number = LI index, ASM_RE_PROXY::get_index of the first useful RE source).
  - VIO_R serves SUB_LOC 0, 1 in tile x + 1, VIO_L SUB_LOC 2, 3 in tile x (interface names L / R; 24 / 24 label pads agree,
    scripts/cycloneiv_clean_bim_specimens.py); HIO is one interface, BIM in the pad tile.
Not bound to a pin: OEREG CE and the INREG / OUTREG CLK groups (one CLK BIM pin per pad, two CLK groups; ledger B-008).
"""
import numpy as np

from . import blockiface, ddb, io_line, muxsel, names, pkgpad
from . import plane as P

# source: ASMDB_ARCH_GROUP_BLOCK_TYPE HIO / VIO (docs/altera/cycloneIV/cycloneiv-clean-io.md)
HIO, VIO = 5, 6
# CLR reads the asynchronous reset pin (ALOAD / ACLR atom ports), SCLR reads port 0x4a = SRESET; INREG / OUTREG CE = pin names INCLKENA / OUTCLKENA
# source: ASMIO_MIO_LABLINE_TO_{DATA,OE,CLR,SCLR}::process_atom (libcomp_asmio, docs/ghidra-readable-index.md): group, gi, DB_INPUT_PORT_TYPE pin name, pin index
PINS = (("MIO_LABLINE_TO_DATA", 0, "DATAIN", 0), ("MIO_LABLINE_TO_DATA", 1, "DATAIN", 1), ("MIO_LABLINE_TO_OE", -1, "OE", 0),
        ("MIO_LABLINE_TO_CLR", -1, "ARESET", 0), ("MIO_LABLINE_TO_SCLR", -1, "SRESET", 0),
        ("MIO_LABLINE_TO_INREG_CE", -1, "INCLKENA", 0), ("MIO_LABLINE_TO_OUTREG_CE", -1, "OUTCLKENA", 0))
# source: blockiface interface names VIO_L / VIO_R: tile offset of the BIM tile from the pad tile
VIO_TILE_DX = {"VIO_R": 1, "VIO_L": 0}
GROUP = PINS[0][0]
# source: blockiface interface names CM_<module>: HIOL_B / HIOL_T (left edge, lower / upper half), HIOR (right edge), VIOB_{L,R} (bottom row), VIOT_{L,R} (top row), PLL<n>
CM_EDGE = (("x", 0, ("CM_HIOL_B", "CM_HIOL_T")), ("x", -1, ("CM_HIOR",)), ("y", 0, ("CM_VIOB_L", "CM_VIOB_R")), ("y", -1, ("CM_VIOT_L", "CM_VIOT_R")))
PLL_INTERFACES = tuple(f"PLL{i}" for i in range(1, 9))
_pins = []


def pins():
    if not _pins:
        _pins.append(blockiface.Pins())
    return _pins[0]


def hio_li_count():
    """LOCAL_INTERCONNECT inputs of the HIO pad pin muxes (interface HIOR: 42; HIOL is the same, checked)."""
    n = pins().li_count("HIOR")
    if pins().li_count("HIOL") != n:
        raise SystemExit("HIOL / HIOR LOCAL_INTERCONNECT counts differ")
    return n


def vio_pin(k, port="DATAIN", idx=0):
    """-> (BIM tile dx, BIM index) of VIO pad SUB_LOC k, pin `port`; None if no VIO interface drives it."""
    for iface in ("VIO_R", "VIO_L"):
        i = pins().bim(iface, port, k, idx)
        if i >= 0:
            return VIO_TILE_DX[iface], i
    return None


def __getattr__(name):
    if name == "SUB_LOC_BIM":                 # {SUB_LOC: (dx, BIM index)} of the pad data pin
        return {k: vio_pin(k) for k in range(4)}
    raise AttributeError(name)


def cm_interfaces(x, y, nx, ny, clkin):
    """Interfaces whose BLOCK_INPUT_MUX -> CLKBUF_IN connections apply to the tile (x, y); `clkin` = set of (z, index) of the CLKBUF_IN records there.
    Tiles whose only CLKBUF_IN is (1, 0) are PLL tiles (all PLL<n> tables are identical, checked by the caller); edge tiles take the CM_ interface of
    their edge, a lower / upper half pair by y < ny // 2; a left / right pair gives both modules (the R module's BLOCK_INPUT_MUX sit in tile x + 1)."""
    if clkin == {(1, 0)}:
        return PLL_INTERFACES[:1]
    for axis, edge, ifs in CM_EDGE:
        v, n = (x, nx) if axis == "x" else (y, ny)
        if v == (edge if edge >= 0 else n - 1):
            return (ifs[0] if y < ny // 2 else ifs[-1],) if axis == "x" and len(ifs) == 2 else ifs
    return ()


def finder(rt):
    """-> find(key) -> record id of an exact (enum, x, y, z, index) key, -1 if absent."""
    keys_all = rt.element_keys()
    order = np.argsort(keys_all, kind="stable")
    keys = keys_all[order]

    def find(q):
        i = np.minimum(np.searchsorted(keys, q), len(keys) - 1)
        return int(order[i]) if keys[i] == q else -1
    return find


class Implicit:
    def __init__(self, rt=None, n_real=0):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        from . import asmdb_walk as W
        rt = rt or ddb.Routing()
        w, nm = W.Walk(), D.enum_tables()["arch_group_type"]
        pads = pkgpad.pads()
        site_pad = pkgpad.io_site_pads(pads)
        tab = P.load_tables()
        find = finder(rt)
        e_li, e_bim = names.enum_of("LOCAL_INTERCONNECT"), names.enum_of("BLOCK_INPUT_MUX")
        self.sites, self.sel, self.eid, src, dst = [], [], [], [], []
        n = n_real
        for btype in (VIO, HIO):
            for gname, gi, port, pidx in PINS:
                g = next(g for g in w.groups() if g["btype"] == btype and nm.get(g["type"]) == gname and g["gi"] == gi)
                line = io_line.Line(w, nm, btype, gname, gi, tab) if btype == HIO else None
                for s in range(len(g["paths"])):
                    if (btype, s) not in site_pad:
                        continue
                    x, y, k = pkgpad.pad_site(pads[site_pad[(btype, s)]])
                    pin = vio_pin(k, port, pidx) if btype == VIO else (0, pins().bim("HIO", port, k, pidx))
                    if pin is None or pin[1] < 0:
                        continue
                    dx, i_bim = pin
                    bim = find(ddb.element_key(e_bim, x + dx, y, 0, i_bim))
                    if btype == VIO:
                        m = muxsel.MapSelect(w, g, np.zeros(1, np.int64), s, tab)
                        valid = [i for i in range(len(m.aux)) if m.aux[i] != muxsel.ABSENT and m.aux[i] < len(m.first_off)]
                        sel = (lambda bits, m=m: int(m.select(bits)[0]))
                    else:
                        valid = [v for v in range(line.n_inputs) if line._ok(s, v)]
                        sel = (lambda bits, line=line, s=s: line.select(bits, s))
                    ids = np.full(max(valid) + 1 if valid else 0, -1, np.int64)
                    for i in valid:
                        li = find(ddb.element_key(e_li, x + dx, y, 0, i))
                        if li >= 0 and bim >= 0:
                            ids[i] = n
                            n += 1
                            src.append(li)
                            dst.append(bim)
                    self.sites.append((btype, gname, gi, x, y, k))
                    self.sel.append(sel)
                    self.eid.append(ids)
        # BLOCK_INPUT_MUX -> CLKBUF_IN: fixed wires, conduct when the clock buffer input select (clkbuf.py) names the CLKBUF_IN
        e_clk = names.enum_of("CLKBUF_IN")
        enum = np.where(rt.tpl >= 0, rt.enum[np.maximum(rt.tpl, 0)].astype(np.int32), -1)
        tiles = {}
        for r in np.flatnonzero(enum == e_clk).tolist():
            t = rt.tpl[r]
            tiles.setdefault((int(rt.x[r]), int(rt.y[r])), set()).add((int(rt.z[t]), int(rt.index[t])))
        pll = [pins().clkbuf(i) for i in PLL_INTERFACES]
        if any(p != pll[0] for p in pll):
            raise SystemExit("PLL<n> interfaces differ in their BLOCK_INPUT_MUX -> CLKBUF_IN connections")
        nx, ny = int(rt.x.max()) + 1, int(rt.y.max()) + 1
        self.into_clkbuf = {}                                  # CLKBUF_IN record -> BLOCK_INPUT_MUX -> CLKBUF_IN edge id
        for (x, y), clkin in sorted(tiles.items()):
            for iface in cm_interfaces(x, y, nx, ny, clkin):
                dx = 1 if iface.startswith("CM_VIO") and iface.endswith("_R") else 0      # R module: BLOCK_INPUT_MUX in tile x + 1 (as VIO_R)
                for k, outs in pins().clkbuf(iface).items():
                    b = find(ddb.element_key(e_bim, x + dx, y, 0, k))
                    for z, i in outs:
                        c = find(ddb.element_key(e_clk, x, y, z, i))
                        if b >= 0 and c >= 0:
                            if c in self.into_clkbuf:
                                raise SystemExit(f"CLKBUF_IN record {c} has two BLOCK_INPUT_MUX parents")
                            self.into_clkbuf[c] = n
                            src.append(b)
                            dst.append(c)
                            n += 1
        self.esrc = np.asarray(src, np.int32)
        self.edst = np.asarray(dst, np.int32)
        self.n_real = n_real

    def apply(self, bits):
        """-> programmed implicit edge ids: one per pad pin whose group resolves to exactly one existing LOCAL_INTERCONNECT."""
        out = []
        for sel, ids in zip(self.sel, self.eid):
            v = sel(bits)
            if 0 <= v < len(ids) and ids[v] >= 0:
                out.append(ids[v])
        return np.asarray(out, np.int64)
