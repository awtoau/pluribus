"""Cyclone IV GX (EP4CGX150) PLL configuration (#169).  Vendor-derived structure, specimen-confirmed.

- PLL config is CFF (periphery frames), not CRAM: every PLL arch group (block types 43 FAST_PLL, 45 GENERAL_PLL) carries CFF-tagged
  absolute addresses (tag 101, cycloneiv_io.ADDRESS_SPACES); `paths[k]` of a group = PLL instance k of that block type.  No instance base needed.
- Field value = mux bits read LSB first in mux order (bit j of the value = j-th mux bit).
- Counter encodings (libcomp_asm ASM_PLL_M_HIGH_COUNTER / M_LOW / N_HIGH / OUTPUT_COUNTER_* ::process_atom, static decompile):
  high = (count + 1) >> 1, low = count >> 1 for an uneven split; `*_MULT_FACTOR` group = even 0 / odd 2 / bypass.
"""
import numpy as np

from . import fields as F, cycloneiv_io as IO

PLL_BLOCKS = {43: "FAST_PLL", 45: "GENERAL_PLL"}      # source: libdb_asmdb ASMDB_ARCH_GROUP_BLOCK_TYPE (reference/ghidra/globals.tsv)
DIRT = "ddb_stingray4_asmdb_dirt.ddb"      # source: quartus common/devinfo/cycloneivgx; COORDINATE_MAP_DATA (PLL tiles) + CLKMUX_PLL_SOURCE (per clock buffer)
BLOCK_NAMES = {"FAST_PLL": 43, "GENERAL_PLL": 45}      # source: dirt ARCH_GROUP_BLOCK_TYPE strings of COORDINATE_MAP_DATA entries; numbers = PLL_BLOCKS
_dirt_cache = {}


def _dirt():
    """(dirt node list with `abs` on every INTEGER node, dirt type names).  Integer decode: scripts/cycloneiv_clean_dirt.py, io_dirt.py."""
    if not _dirt_cache:
        import os
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
        import cycloneiv_clean_dirt as D
        nodes, ok = D.decode_dirt(os.path.join(_devinfo(), DIRT))
        if not ok:
            raise ValueError("dirt ddb not fully consumed")
        acc = 0
        for n in nodes:
            if n["cls"] == 3 and n["val"]:
                acc += n["val"][0]
                n["abs"] = acc
        _dirt_cache["v"] = (nodes, D.enum_tables()["dirt_type"])
    return _dirt_cache["v"]


def _top(nodes, tt, name):
    return next(nodes[c] for c in nodes[0]["ch"] if nodes[c]["flag"] == 1 and tt.get(nodes[c]["idx"]) == name)


def pll_tiles():
    """{icd: (block type, path, (x, y))}: every PLL of the die.  icd = IC_DESIGN_INDEX = the Quartus location number (PLL_k); path = entry order
    inside the block's COORDINATE_MAP_DATA (= group path k of the CFF groups); (x, y) = SW_LOC of the PLL tile (= PLL_BUFFER / PLL_CLKIN record tile)."""
    nodes, tt = _dirt()
    out = {}
    for blk in _top(nodes, tt, "COORDINATE_MAP_DATA")["ch"]:
        kids = nodes[blk]["ch"]
        bt = next((nodes[k]["val"][0] for k in kids if nodes[k]["cls"] == 4), None)
        if bt not in BLOCK_NAMES:
            continue
        for path, e in enumerate(nodes[next(k for k in kids if nodes[k]["cls"] == 2)]["ch"]):
            f = {tt.get(nodes[k]["idx"]): nodes[k]["abs"] for k in nodes[e]["ch"] if nodes[k]["cls"] == 3}
            out[f["IC_DESIGN_INDEX"]] = (BLOCK_NAMES[bt], path, (f["SW_LOC_X"], f["SW_LOC_Y"]))
    return out


def clkmux_pll_source():
    """{clock buffer gid: icd}: CLKMUX_PLL_SOURCE (30 integers, index = gid).  Read by ASM_CLKBUF_CLK_INPUT_SELECT_CYCLONEII::second_pll_feeds_clock_mux@0x2f9adc."""
    nodes, tt = _dirt()
    return {nodes[c]["idx"]: nodes[c]["abs"] for c in _top(nodes, tt, "CLKMUX_PLL_SOURCE")["ch"]}


def __getattr__(name):
    if name == "PLL_SITE":       # PLL_k -> (block type, path index), from the dirt PLL coordinate map (was specimen-derived for k = 1..5, 8: same values)
        return {k: (bt, p) for k, (bt, p, _) in sorted(pll_tiles().items())}
    raise AttributeError(name)
# source: ASM_PLL_*_COUNTER::process_atom decompile + gxhb_pll_* pair builds (postfit.vo m / n / c#_high / c#_low / c#_initial / charge_pump_current_bits)
COUNTER_FIELDS = {"M": ("PLL_M_HIGH_COUNTER", "PLL_M_LOW_COUNTER", "PLL_M_MULT_FACTOR", "PLL_M_PRESET"),
                  "N": ("PLL_N_HIGH_COUNTER", "PLL_N_LOW_COUNTER", "PLL_N_MULT_FACTOR", None)}
# source: ASM_PLL_OUTPUT_COUNTER_* classes (libcomp_asm) = arch-group names; gi = output counter index c0..c4
OUT_FIELDS = ("PLL_OUTPUT_COUNTER_HIGH_COUNTER", "PLL_OUTPUT_COUNTER_LOW_COUNTER", "PLL_OUTPUT_COUNTER_MULT_FACTOR", "PLL_OUTPUT_COUNTER_PRESET")
# source: gxhb_pll_* builds: unused output counter reads high 15 / low 15 / mult factor 3 (21 of 21 specimens, counters 1..4)
UNUSED_COUNTER = (15, 15, 3)


class PllMap:
    """(block type, group name, gi) -> list per PLL path of CFF bit indices (group mux bits, LSB first)."""

    def __init__(self, flds):
        self.g = {}
        for f in flds:
            if f.btype not in PLL_BLOCKS:
                continue
            paths = []
            for site in f.sites:
                arr = np.concatenate([np.asarray(o, np.int64) for o in site]) if site else np.zeros(0, np.int64)
                paths.append((arr & 0x1FFFFFFF) if len(arr) and (arr >> 29 == 5).all() else None)
            self.g[(f.btype, f.name, f.gi)] = paths

    def value(self, cff, btype, path, name, gi=-1):
        idx = self.g[(btype, name, gi)][path]
        return None if idx is None else int(sum(int(cff[i]) << j for j, i in enumerate(idx)))

    def read(self, cff, btype, path):
        """{ 'NAME#gi': int } for every CFF-tagged group of one PLL path."""
        out = {}
        for (bt, nm, gi), paths in self.g.items():
            if bt == btype and path < len(paths) and paths[path] is not None:
                out[f"{nm}#{gi}"] = self.value(cff, bt, path, nm, gi)
        return out

    def enabled(self, cff, btype, path):
        return self.value(cff, btype, path, "PLL_ENABLE_PLL") == 1

    def used(self, cff):
        """[(PLL_k, btype, path)] of PLLs whose enable bit is set."""
        return [(k, bt, p) for k, (bt, p) in sorted(__getattr__('PLL_SITE').items()) if self.enabled(cff, bt, p)]

    def params(self, cff, btype, path):
        """Decoded parameters {m, n, c0..c4: (high, low, initial, kind), charge_pump} of one PLL path."""
        v = lambda nm, gi=-1: self.value(cff, btype, path, nm, gi)      # noqa: E731
        out = {"m": v("PLL_M_HIGH_COUNTER") + v("PLL_M_LOW_COUNTER"), "n": v("PLL_N_HIGH_COUNTER") + v("PLL_N_LOW_COUNTER"),
               "charge_pump": v("PLL_CHARGE_PUMP_CURRENT"), "loop_filter_r": v("PLL_LOOP_FILTER_R"), "loop_filter_c": v("PLL_LOOP_FILTER_C"),
               "usage_mode": v("PLL_USAGE_MODE"),
               "vco_post_scale": 2 if v("PLL_VCO_DIVIDE_BY_2") == 0 else 1}      # writer ASM_PLL_VCO_DIVIDE_BY_2: value = (post_scale == 2); 1-bit one-hot stores NOT value
        for c in range(5):
            h, lo, mf, pre = (v(nm, c) for nm in OUT_FIELDS)
            out[f"c{c}"] = ("bypass", 0, 0, 0) if (h, lo, mf) == UNUSED_COUNTER else ("counter", h, lo, pre)
        return out


class Wires:
    """Fixed-wire PLL edges (empty asm group, enabled by the PLL itself): PLL_FBOUT -> PLL_FEEDBACK_IN of every enabled PLL (CFF PLL_ENABLE_PLL).
    The second parent of PLL_FEEDBACK_IN (core feedback, 2-entry group) is the external-feedback path: not specimened, not modelled (#175)."""

    def __init__(self, st, rt, walk, nm):
        from . import ddb, names as N
        self.pm = PllMap(F.fields(walk, nm))
        tiles = pll_tiles()
        xy = {v[2]: (k, v[0], v[1]) for k, v in tiles.items()}
        enum = np.where(rt.tpl >= 0, rt.enum[np.maximum(rt.tpl, 0)].astype(np.int32), -1)
        e_in = N.enum_of("PLL_FEEDBACK_IN")
        self.edge = {}                                    # (btype, path) -> edge id
        for r in np.flatnonzero(enum == N.enum_of("PLL_FBOUT")).tolist():
            for d in rt.fanout(r).tolist():
                if enum[d] == e_in:
                    e = int(st.edge_ids([r], [d])[0])
                    if e >= 0:
                        _, bt, path = xy[(int(rt.x[r]), int(rt.y[r]))]
                        self.edge[(bt, path)] = e
        self.cff, self._seen = None, (None, frozenset())
        self.site = {v[:2]: k for k, v in tiles.items()}      # (btype, path) -> icd

    def enabled(self, bits):
        """frozenset of icd (PLL_k) with PLL_ENABLE_PLL set; `bits` is a tracer.Plane (carries the rbf the CFF is read from)."""
        rbf = getattr(bits, "rbf", None)
        if rbf is None:
            return frozenset()
        if self._seen[0] != rbf:
            if self.cff is None:
                self.cff = IO.Cff()
            cff = self.cff.read(rbf)[0]
            self._seen = (rbf, frozenset(k for bp, k in self.site.items() if self.pm.enabled(cff, *bp)))
        return self._seen[1]

    def apply(self, bits):
        """-> edge ids of the enabled PLLs."""
        en = self.enabled(bits)
        return np.asarray([e for bp, e in sorted(self.edge.items()) if self.site[bp] in en], np.int64)


# group (gi) -> (element, DB_INPUT_PORT_TYPE, port index) of the vendor block interface PLL<n> (blockiface.py).  Name match for 7 ports, 7 of 7 specimens
# (gxhb_pllmp_{ar,pfd,sw,scan}); the other six by elimination of the interface's remaining BIM ports, unspecimened (ledger P-009)
# source: group names = libdb_asmdb arch-group-type table; ports = DB_INPUT_PORT_TYPE_STRING (libdb_dbs.so) in the PLL1..PLL8 interfaces
INPUT_GROUPS = {("PLL_ARESET_INPUT", -1): ("PLL", "ARESET", 0), ("PLL_PFD_ENA_INPUT", -1): ("PLL", "PFDENA", 0),
                ("PLL_CLOCK_SWITCH_INPUT", -1): ("PLL", "CLKSWITCH", 0), ("PLL_SCAN_DATA_INPUT", -1): ("PLL", "SCANDATA", 0),
                ("PLL_SCAN_CLOCK_INPUT", -1): ("PLL", "SCANCLK", 0), ("PLL_SCAN_CLOCK_ENABLE_INPUT", -1): ("PLL", "SCANCLKENA", 0),
                ("PLL_CONFIG_UPDATE_INPUT", -1): ("PLL", "CONFIGUPDATE", 0), ("PLL_PHASE_UP_DOWN_INPUT", -1): ("PLL", "PHASEUPDOWN", 0),
                ("PLL_PHASE_CLK_INPUT", -1): ("PLL", "PHASESTEP", 0), ("PLL_PHASE_COUNTER_SELECT_INPUT", 0): ("PLL", "PHASECOUNTERSELECT", 0),
                ("PLL_PHASE_COUNTER_SELECT_INPUT", 1): ("PLL", "PHASECOUNTERSELECT", 1), ("PLL_PHASE_COUNTER_SELECT_INPUT", 2): ("PLL", "PHASECOUNTERSELECT", 2),
                ("PLL_EXTCLK_ENABLE_INPUT", -1): ("CLKBUFBLOCK", "ENA", 0)}
# source: the six groups above without a specimen (ledger P-009)
INPUT_UNSPECIMENED = ("PLL_PHASE_UP_DOWN_INPUT", "PLL_PHASE_CLK_INPUT", "PLL_PHASE_COUNTER_SELECT_INPUT", "PLL_EXTCLK_ENABLE_INPUT")


class Inputs:
    """LOCAL_INTERCONNECT -> BLOCK_INPUT_MUX edges at the PLL tile for the fabric control inputs (areset, pfdena, clkswitch, scan, phase), absent from
    the routing graph (appended, ids >= n_real).  Group PLL_<port>_INPUT of PLL path p = LOCAL_INTERCONNECT index of the PLL tile (value = io_line select;
    the writer ASM_PLL_INPUT::process_atom@0x1a3ea8 stores ASM_RE_PROXY::get_index of the source); the BIM index of the port comes from the vendor
    interface PLL<icd> (blockiface.py).  Wire pad -> LI -> BIM is the RCF route (gxhb_pllmp_*: 7 of 7)."""

    def __init__(self, walk, nm_all, rt, n_real=0):
        from . import blockiface as B, ddb, io_line, names as N, plane as P
        from .bim import finder
        nm = nm_all["arch_group_type"]
        tab = P.load_tables()
        find = finder(rt)
        pn = B.input_port_names()
        de = B.dev_enums()
        ifs = {d["name"]: d for d in B.load() if d["type"] == 1}
        e_li, e_bim = N.enum_of("LOCAL_INTERCONNECT"), N.enum_of("BLOCK_INPUT_MUX")
        self.items, src, dst, n = [], [], [], n_real           # (line, btype, path, {LI index: edge id})
        for icd, (bt, path, (x, y)) in sorted(pll_tiles().items()):
            nodes = ifs[f"PLL{icd}"]["nodes"]
            for (g, gi), (el, port, idx) in INPUT_GROUPS.items():
                bims = [m["index"] for m in nodes if m["enum"] == de["LEIM"] for c in m["conns"]
                        if c["enum"] == de[el] and pn.get(c["port"]) == port and c["index"] == idx]
                if len(bims) != 1:
                    continue
                b = find(ddb.element_key(e_bim, x, y, 0, bims[0]))
                if b < 0:
                    continue
                m = {}
                for li in range(128):
                    r = find(ddb.element_key(e_li, x, y, 0, li))
                    if r >= 0:
                        m[li] = n
                        src.append(r)
                        dst.append(b)
                        n += 1
                self.items.append((io_line.Line(walk, nm, bt, g, gi, tab), path, m))
        self.esrc, self.edst, self.n_real = np.asarray(src, np.int32), np.asarray(dst, np.int32), n_real

    def apply(self, bits):
        """-> programmed edge ids: one per (PLL path, port) whose group selects an existing LOCAL_INTERCONNECT."""
        out = []
        for ln, path, m in self.items:
            if not len(ln.cells[path]):
                continue
            v = ln.select(bits, path)
            if v in m:
                out.append(m[v])
        return np.asarray(out, np.int64)


def load(walk, names):
    return PllMap(F.fields(walk, names))


def read_cff(rbf, cff=None):
    return (cff or IO.Cff()).read(rbf)[0]


BASIC_PLL = "ddb_stingray_basic.pll"       # source: quartus common/devinfo/cycloneivgx text table (pll GPLL / MPLL blocks)


def basic_tables(path=None):
    """{key: list of ints} of the first `pll GPLL` block: charge_pump_current_bit, loop_filter_resistor_bit, loop_filter_capacitor_bit.
    List index = field value, entry = physical value (0 = unused code, -1 terminator)."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
    import toolchain
    path = path or os.path.join(os.path.dirname(toolchain.quartus_bin()), "common", "devinfo", "cycloneivgx", BASIC_PLL)
    out, seen = {}, 0
    for ln in open(path):
        t = ln.split()
        if t[:1] == ["pll"]:
            seen += 1
        elif seen == 1 and t and t[0] in ("charge_pump_current_bit", "loop_filter_resistor_bit", "loop_filter_capacitor_bit"):
            out[t[0]] = [int(x) for x in t[1:] if x != "-1"]
    return out


BANDWIDTH_GPLL = "ddb_stingray_bandwidth_gpll.pll"      # source: quartus common/devinfo/cycloneivgx text table "V3 - Cyclone IIIGX BW settings": (M*post lo, hi, ICP, R, C, ...)


BANDWIDTH_MPLL = "ddb_stingray_bandwidth_mpll.pll"      # source: same directory; carries both ICP 1 and ICP 3 rows per M * post range


def _devinfo():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
    import toolchain
    return os.path.join(os.path.dirname(toolchain.quartus_bin()), "common", "devinfo", "cycloneivgx")


TIMING = "ddb_stingray4.pll"      # source: quartus common/devinfo/cycloneivgx; per part / speed grade PLL limits (EP4CGX150 parts); every value is a PERIOD in ps (min / max name the period)


def limits(kind="GPLL", grade=7):
    """Limits of the `pll <kind>` blocks without operating_condition of the EP4CGX150 parts of one speed grade: the loosest value over the parts.
    -> {vco: {post: (min, max)}, pfd: (min, max), input: (min, max), output_min}, periods in ps.  vco is the period after the post-scale divider."""
    import os
    blocks, cur = [], None
    for ln in open(os.path.join(_devinfo(), TIMING)):
        t = ln.split()
        if t[:1] == ["pll"]:
            cur = {"kind": t[1], "cond": False}
            blocks.append(cur)
        elif cur is not None and t:
            if t[0] == "operating_condition":
                cur["cond"] = True
            elif t[0].startswith("vco_m") and len(t) == 3:
                cur[f"{t[0]}#{t[1]}"] = int(t[2])
            elif len(t) == 2:
                cur[t[0]] = t[1]
    sel = [b for b in blocks if b["kind"] == kind and not b["cond"] and b.get("part", "").startswith("EP4CGX150") and int(b["speed_grade"]) == grade]
    if not sel:
        raise ValueError(f"no EP4CGX150 {kind} block of speed grade {grade} in {TIMING}")
    lo = lambda key: min(int(b[key]) for b in sel)      # noqa: E731
    hi = lambda key: max(int(b[key]) for b in sel)      # noqa: E731
    return {"vco": {p: (lo(f"vco_min_post_scale#{p}"), hi(f"vco_max_post_scale#{p}")) for p in (1, 2)},
            "pfd": (lo("pfd_min"), hi("pfd_max")), "input": (lo("input_min"), hi("input_max")), "output_min": lo("output_min")}


def fin_interval(prm, kind="GPLL", grade=7):
    """Interval (MHz) of the input frequency consistent with the decoded parameters and the vendor limits (periods in ps -> MHz = 1e6 / ps):
    VCO = Fin * M / N with the post-scale period (post * T_vco) inside vco[post], PFD = Fin / N, input range, every used output counter
    below output_min (Fout = Fin * M / (N * C)).  -> (lo, hi) or None when empty.  Formula check: gxhb_pllsite_* builds (Fin 50 MHz)."""
    lim = limits(kind, grade)
    m, n, post = prm["m"], prm["n"], prm["vco_post_scale"]
    f = lambda ps, r: 1e6 / (ps + r)      # noqa: E731   the vendor periods are integer ps: +-0.5 ps rounding on each limit (widens the interval)
    tmin, tmax = lim["vco"][post]
    lo = [post * f(tmax, 0.5) * n / m, f(lim["pfd"][1], 0.5) * n, f(lim["input"][1], 0.5)]
    hi = [post * f(tmin, -0.5) * n / m, f(lim["pfd"][0], -0.5) * n, f(lim["input"][0], -0.5)]
    for c in range(5):
        kd = prm[f"c{c}"]
        if kd[0] == "counter":
            hi.append(f(lim["output_min"], -0.5) * n * (kd[1] + kd[2]) / m)
    lo, hi = max(lo), min(hi)
    return (lo, hi) if lo <= hi else None


def bandwidth_rows(kind="gpll"):
    """[(lo, hi, icp, r, c)] of a vendor bandwidth settings table (charge-pump / loop-filter field values per M * post-scale range)."""
    import os
    path = os.path.join(_devinfo(), BANDWIDTH_GPLL if kind == "gpll" else BANDWIDTH_MPLL)
    rows = []
    for ln in open(path):
        t = ln.split()
        if len(t) >= 5 and all(x.lstrip("-").isdigit() for x in t[:5]):
            rows.append(tuple(int(x) for x in t[:5]))
    return rows


def bandwidth_settings(m, post, bandwidth="medium"):
    """(icp, r, c) for M * post: low / medium use the GPLL table (ICP 1); high takes the ICP 3 rows of the MPLL table.  None when outside every range."""
    rows = [r for r in bandwidth_rows("mpll") if r[2] == 3] if bandwidth == "high" else bandwidth_rows("gpll")
    for lo, hi, icp, r, c in rows:
        if lo <= m * post <= hi:
            return icp, r, c
    return None
