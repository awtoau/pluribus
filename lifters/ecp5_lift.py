#!/usr/bin/env python3
"""Lattice ECP5 (LFE5U/LFE5UM) bitstream lifter — issue #9 / #15.

Takes a Trellis `.config` plus a device string and produces electrical nets,
a structural LUT4 + flip-flop netlist, and per-pad fabric connectivity, in the
same shape MachXO2Lift produces, so load.py drives either without caring which
family it has.

WHAT ACTUALLY DIFFERS FROM MachXO2
----------------------------------
The stub that preceded this file listed six expected differences.  Five of them
turned out to be wrong, and recording that is more useful than repeating them:

  * "Slice naming: TRELLIS_SLICE (SLICEL/SLICEM) vs SLICE[A-D]" — WRONG.
    TRELLIS_SLICE/SLICEL/SLICEM are *nextpnr* cell types, not bitstream names.
    A Trellis `.config` for ECP5 uses `SLICEA..SLICED` exactly as MachXO2 does.
  * "LUT init format: K=0 only" — WRONG.  ECP5 emits both `SLICEx.K0.INIT` and
    `SLICEx.K1.INIT`, 16-bit, identical to MachXO2.  Two LUT4s per slice.
  * "IO cells: TRELLIS_IO, not PIO" — WRONG in the same way; the bitstream
    calls them `PIOA..PIOD` and prjtrellis' bel type is `PIO`.
  * "Pad joint node names differ: PIOA_IO -> ..." — differs, but not like that;
    see the pad section below.
  * "Routing graph globalise_net() edge cases may differ" — RIGHT, and this is
    the one that mattered.  See below.
  * "No EFB fixed_conns" — RIGHT.  ECP5 has no EFB, so that whole path is a
    no-op here rather than a port.

So the LUT/FF/enum decode is shared with MachXO2 almost verbatim (the regexes
are literally the same), and the real work is routing.

THE ROUTING DIFFERENCE, WHICH IS THE WHOLE JOB
----------------------------------------------
`globalise_net_ecp5` (prjtrellis RoutingGraph.cpp) is much simpler than the
MachXO2 version — no spine tables, no stride, no CENTER_MAP — because
prjtrellis does not model ECP5 clock quadrants at all.  Upstream says so:
"TODO: quadrants and TAP_DRIVE regions".  Every `G_*` global that is not
VPTX/HPBX/HPRX is parked at the nominal location (0, 0).

That is a correctness trap, not just an approximation.  Two unrelated clock
nets with the same db name both canonicalise to (0, 0, "G_..."), so a naive
union-find fuses them — and through them, fuses every register in the design
onto one net.  MachXO2Lift dodges the equivalent case because its globaliser
returns an INVALID (-1,-1) location for chip-globals and the lifter drops
those endpoints.  ECP5 returns a *valid* (0,0), so the drop has to be explicit
here: see _is_chip_global() and its use in gkey().

Conversely, the MachXO2 lifter's gkey() carries a lot of hard-won surgery for
MachXO2-specific database defects — V-span top/bottom-edge mirroring, the
H06E right-edge sense bug, the V02S0601/0701 aliases.  None of those defects
exist on ECP5 (different tile DB, different edge conventions), so inheriting
them would inject net merges rather than fix them.  This lifter deliberately
does NOT reuse that code.  That is the reason ECP5 is a sibling class rather
than a `family=` parameter on MachXO2Lift — see the note in trellis_lift.py.

Bel pin nodes are bridged to the switchbox by FIXED pips absent from
`.config`, exactly as on MachXO2, but ECP5 has two suffixes to strip rather
than one: `_SLICE` (slice pins) and `_PIO` (pad pins).

Pads: ECP5 has a real PIO bel, so pad connectivity comes off the bel pins
(O=JPADDI{L}_PIO in, I=PADDO{L}_PIO out) rather than MachXO2's JQ{n}/JA{n}
joint-node convention.
"""

import os
import re
import sys
from collections import defaultdict

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

DEF_BUILD_DIR = os.environ.get("TRELLIS_BUILD",
                               "tmp/prjtrellis/libtrellis/build")
def _default_dbroot():
    """Resolve the trellis database through the single toolchain resolver.

    Same fix machxo2_lift.py already carries (#90); this lifter never got it and
    kept the literal path a since-removed in-tree prjtrellis checkout occupied.
    A caller that did not export TRELLIS_DBROOT therefore died on a missing
    devices.json -- after the pin file had loaded and the config had been read,
    so it read as a data problem rather than a stale constant.
    """
    _scripts = os.path.join(_REPO, "scripts")
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    import toolchain
    return toolchain.trellis_dbroot()


DEF_DBROOT = os.environ.get("TRELLIS_DBROOT") or _default_dbroot()

# `.config` line format is identical across Trellis families — and so, as it
# turns out, are the ECP5 slice key names.  These are the MachXO2 regexes.
TILE_RE = re.compile(r"^\.tile\s+(\S+):(\S+)")
ARC_RE = re.compile(r"^arc:\s+(\S+)\s+(\S+)")
LUT_RE = re.compile(r"^word:\s+SLICE([A-D])\.K([01])\.INIT\s+([01]+)")
SENUM_RE = re.compile(r"^enum:\s+SLICE([A-D])\.(\S+)\s+(\S+)")
ENUM_RE = re.compile(r"^enum:\s+(\S+)\s+(\S+)")
WORD_RE = re.compile(r"^word:\s+(\S+)\s+(\S+)")

# Reuse the shared containers + the FF D-source rule.  ff_d_source() encodes
# REG{j}.SD semantics (SD=1/omitted => D comes from the paired LUT's F through
# the internal DI path; SD=0 => D comes from the fabric-routed M wire).  ECP5
# uses the same CommonBels slice structure and the same nextpnr packing rule,
# and the round-trip FF check in scripts/ecp5_roundtrip.py is the guard.
from lifters.machxo2_lift import (  # noqa: E402
    DSU, Design, ParsedConfig, ff_d_source,
)


_PLC_ENUM_DEFAULTS = {}


def plc_enum_defaults(dbroot):
    """ECP5 PLC2/bits.db `.config_enum` defaults: {enum_name: value}.

    A decoded .config omits an enum at its default, so a missing key means the default.
    Sibling of machxo2_lift.plc_enum_defaults (different tile type and path).
    """
    d = _PLC_ENUM_DEFAULTS.get(dbroot)
    if d is None:
        d = {}
        path = os.path.join(dbroot, "ECP5", "tiledata", "PLC2", "bits.db")
        with open(path) as fh:
            for ln in fh:
                t = ln.split()
                if len(t) >= 3 and t[0] == ".config_enum":
                    d[t[1]] = t[2]
        if not d:
            from db import die
            die(f"no .config_enum entries in {path}")
        _PLC_ENUM_DEFAULTS[dbroot] = d
    return d


class ECP5Lift:
    """Routing-graph-backed lifter for one ECP5 device."""

    def __init__(self, device, build_dir=DEF_BUILD_DIR, dbroot=DEF_DBROOT):
        self._native_ids = os.environ.get("PLURIBUS_TRELLIS_BACKEND", "native") != "so"
        if os.environ.get("PLURIBUS_TRELLIS_BACKEND", "native") == "so":
            if build_dir not in sys.path:
                sys.path.insert(0, build_dir)
            import pytrellis
        else:
            from native_trellis import pytrellis_compat as pytrellis
        self._pt = pytrellis
        self._dbroot = dbroot
        self.dbroot = dbroot
        pytrellis.load_database(dbroot)
        self.device = device
        self.chip = pytrellis.Chip(device)
        self.rg = self.chip.get_routing_graph(True, True)
        self.max_row = self.chip.get_max_row()
        self.max_col = self.chip.get_max_col()

        # tile FULL "name:type" -> (row, col)
        self.tile_rc = {}
        for r in range(self.max_row + 1):
            for c in range(self.max_col + 1):
                for t in self.chip.get_tiles_by_position(r, c):
                    self.tile_rc[f"{t.info.name}:{t.info.type}"] = (r, c)
                    # tilegrid keys are already "R#C#:TYPE"; index the bare
                    # name too so callers can look up either form.
                    self.tile_rc[t.info.name] = (r, c)

        self._wn_index = {}
        self._bel_cache = {}
        # (row, col, "MUXCLK2") entries whose tile config actually drives that
        # mux node.  Filled by parse_config(); consulted by remap().  Empty
        # until then, so a bare ECP5Lift still resolves control pins to the
        # plain wire rather than guessing.
        self._prefer_mux_nodes = set()

    # ---- node-key helpers --------------------------------------------------
    def wname_id(self, col, row, name):
        if self._native_ids:
            # native backend: wire id == name, so the per-lift name->id index is the identity
            return name if self.rg.has_wire(col, row, name) else None
        key = (col, row)
        idx = self._wn_index.get(key)
        if idx is None:
            idx = {}
            t = self.rg.tiles.get(self._pt.Location(col, row))
            if t is not None:
                for wid in t.wires.keys():
                    idx[self.rg.to_str(wid)] = wid
            self._wn_index[key] = idx
        return idx.get(name)

    # Bel-pin node suffixes bridged to the switchbox by FIXED pips that are
    # never emitted as `.config` arcs.  MachXO2 only has _SLICE; ECP5 adds
    # _PIO because its pads are a real bel rather than a joint node.
    _FIXED_PIP_SUFFIXES = ("_SLICE", "_PIO")

    # Control-pin nodes reached through the slice's clock/reset distribution
    # mux.  Stripping "_SLICE" is enough for CLK0/LSR0 and CLK1/LSR1, whose
    # bare wires exist in the tile — but slices C and D have NO bare CLK2/CLK3
    # or LSR2/LSR3 wire.  Their control signals arrive on MUXCLK{n}/MUXLSR{n},
    # which the `.config` drives from CLK0/LSR0:
    #     arc: CLK0     G_HPBX0000     <- global clock enters the tile
    #     arc: MUXCLK2  CLK0           <- distributed to slice C
    # Without this bridge the FF's CLK pin lands on the dead "CLK2_SLICE" node,
    # resolves to nothing, and the register is recovered with clk=1'b0 — a
    # clockless flip-flop, which is silently wrong rather than obviously so.
    #
    # Slices A and B are the awkward case: their bare CLK0/CLK1/LSR0/LSR1
    # wires DO exist, so the plain "_SLICE" strip succeeds — but for index >= 1
    # that bare wire can be a dead end, because the config still distributes
    # through MUXCLK{n}.  So the mux node is preferred whenever the config
    # actually drives it; `_prefer_mux_nodes` is populated per parse from the
    # arcs, and remap() consults it before falling back to the bare wire.
    _MUX_CTRL_RE = re.compile(r"^(CLK|LSR)(\d)(?:_SLICE)?$")

    def remap(self, wire):
        """A bel pin's RoutingId -> the canonical fabric node the config arcs
        reference.  Crosses the fixed pips that `.config` never emits."""
        nm = self.rg.to_str(wire.id)
        col, row = wire.loc.x, wire.loc.y
        bare = nm
        for suf in self._FIXED_PIP_SUFFIXES:
            if nm.endswith(suf):
                bare = nm[:-len(suf)]
                break

        # Control pins: use the distribution-mux node when this tile's config
        # actually drives it (see _MUX_CTRL_RE).  Checked before the bare wire
        # because for slices B..D the bare wire may exist yet be a dead end.
        m = self._MUX_CTRL_RE.match(nm)
        if m:
            mux_name = f"MUX{m.group(1)}{m.group(2)}"
            if (row, col, mux_name) in self._prefer_mux_nodes:
                mux = self.wname_id(col, row, mux_name)
                if mux is not None:
                    return (col, row, mux)

        if bare is not nm:
            fid = self.wname_id(col, row, bare)
            if fid is not None:
                return (col, row, fid)
        return (col, row, wire.id)

    # Globals that prjtrellis parks at the nominal (0,0) location because it
    # does not model ECP5 clock quadrants.  Distinct physical nets share these
    # keys, so unioning through them would fuse unrelated logic.  Detected by
    # name (the position alone is ambiguous: (0,0) is also a real corner tile).
    _CHIP_GLOBAL_RE = re.compile(r"^G_")
    _POSITIONAL_GLOBAL = ("VPTX", "HPBX", "HPRX")

    @classmethod
    def _is_chip_global(cls, name):
        """True if `name` is an ECP5 global whose canonical position is a
        placeholder rather than a real location.

        VPTX/HPBX/HPRX globals keep their own tile position and so remain
        distinguishable; every other G_* collapses to (0,0) and must be
        dropped rather than unioned.  This is the ECP5 analogue of MachXO2's
        "globalise_net returned (-1,-1), drop the endpoint" rule.
        """
        if not cls._CHIP_GLOBAL_RE.match(name):
            return False
        return not any(s in name for s in cls._POSITIONAL_GLOBAL)

    # ---- clock tree (#116) -------------------------------------------------
    # prjtrellis parks/positions these per referencing tile, so the tree never joins.
    # Canonical node per physical wire; evidence: docs/lattice/ecp5/ecp5-diamond-oracle.md "Clock tree".
    _CK_UNIQUE = re.compile(
        r"^G_(JPCLKT\d+|[TLR]DCC\d+CLKI|CLKI_[TLR]DCC\d+|CLKO_[TLR]DCC\d+"
        r"|VPFS\d+|HPFE\d+|HPFW\d+)$")
    _CK_QPCLK = re.compile(r"^G_(LL|LR|UL|UR)PCLK(\d+)$")
    _CK_SPINE = re.compile(r"^G_(HPRX|VPTX)(\d\d)00$")
    _CK_HPBX = re.compile(r"^([GLR])_HPBX(\d\d)00$")

    def _clock_geom(self):
        g = getattr(self, "_ckg", None)
        if g is None:
            import json
            p = os.path.join(self._dbroot, "ECP5", self.device, "globals.json")
            with open(p) as fh:
                g = json.load(fh)
            self._ckg = g
        return g

    def _quad_of(self, col, row):
        for q, b in self._clock_geom()["quadrants"].items():
            if b["x0"] <= col <= b["x1"] and b["y0"] <= row <= b["y1"]:
                return q
        return None

    def clock_key(self, row, col, name):
        """Node key of a clock-tree wire, or None if `name` is not modelled here.
        Works for a decoded tile-local name (tap / spine / PLC tile) and for the
        position Diamond reports the same wire at (with a G_ prefix added)."""
        if not name.startswith(("G_", "L_", "R_")):
            return None
        if self._CK_UNIQUE.match(name):
            return ("clk", name[2:])
        m = self._CK_QPCLK.match(name)
        if m:       # quadrant clock i is the quadrant's HPRX i (Diamond: LRPCLK0 -> HPRX0000)
            return ("hprx", m.group(1), int(m.group(2)))
        g = self._clock_geom()
        m = self._CK_SPINE.match(name)
        if m:
            idx = int(m.group(2))
            q = self._quad_of(col, row)
            if m.group(1) == "HPRX":
                return None if q is None else ("hprx", q, idx)
            for sn, s in g["spines"].items():
                # Diamond names the vertical VPTX anywhere along its quadrant half
                if s["x"] == col and sn[:2] == q:
                    return ("vptx", sn, idx)
            for tn in g["taps"]:        # TAP_DRIVE tile in a tap column
                if int(tn[1:]) == col and q is not None:
                    return ("vptx", q + tn[1:], idx)
            return None
        m = self._CK_HPBX.match(name)
        if m:
            for tn, t in g["taps"].items():
                if t["lx0"] <= col <= t["lx1"]:
                    side = "L"
                elif t["rx0"] <= col <= t["rx1"]:
                    side = "R"
                else:
                    continue
                tcol = int(tn[1:])
                if m.group(1) in "LR":      # tap tile names its own side
                    side = m.group(1)
                return ("hpbx", row, tcol, side, int(m.group(2)))
        return None

    def apply_clock_fixed_conns(self, dsu, pc=None):
        """Union the clock tree's fixed conns between modelled wires, the DCC
        buffer CLKI -> CLKO, and pad -> JPCLKT for clock-capable pads (iodb
        function PCLKT<b>_<k> <-> JPCLKT<b><k>, 228/228 in the Diamond routes).
        Returns the number of unions."""
        nat = getattr(self.chip, "_native", None)
        if nat is None:
            return 0
        from native_trellis import tiledb
        n = 0
        seen = set()
        for tname, (row, col) in nat.geom.tile_rc.items():
            ttype = nat.geom.tile_type[tname]
            if ttype in seen or not ttype.startswith(("TMID", "LMID", "RMID", "BMID", "CMUX")):
                continue
            seen.add(ttype)
            _muxes, fixed = tiledb.load_tiletype(nat.db_root, nat.family, ttype)
            for sink, src in fixed:
                a, b = self.clock_key(row, col, sink), self.clock_key(row, col, src)
                if a is not None and b is not None and a[0] == b[0] == "clk":
                    dsu.union(a, b)
                    n += 1
        for key in [k for k in list(dsu.p) if k[0] == "clk" and k[1].startswith("CLKI_")]:
            ko = ("clk", "CLKO_" + key[1][len("CLKI_"):])
            dsu.union(key, ko)
            n += 1
        import json
        iop = os.path.join(self._dbroot, "ECP5", self.device, "iodb.json")
        with open(iop) as fh:
            pios = json.load(fh)["pio_metadata"]
        for e in pios:
            m = re.match(r"^PCLKT(\d)_(\d)$", e.get("function") or "")
            if not m:
                continue
            ck = ("clk", f"JPCLKT{m.group(1)}{m.group(2)}")
            if ck in dsu.p:
                pw = f"JPADDI{e['pio']}"
                if self.wname_id(e["col"], e["row"], pw) is None:
                    pw += "_PIO"
                pk = self.gkey(e["row"], e["col"], pw)
                if pk is not None:
                    dsu.union(pk, ck)
                    n += 1
        # pad-input mux wires (JPCLKT -> JINCK -> JPADDI) at each mid-edge tile: Diamond routes
        # pad -> JPADDI -> JINCK -> JPCLKT, the DB has them as fixed conns.  Only chains that
        # already touch a used clock node (two passes cover JPCLKT~JINCK~JPADDI).
        loc = re.compile(r"^([NSEW]\d+)*_?(JINCK|JPADDI)$")
        driven = {(r, c, k) for (r, c, k, _s) in pc.arcs} if pc is not None else set()
        pairs = []
        for tname, (row, col) in nat.geom.tile_rc.items():
            ttype = nat.geom.tile_type[tname]
            if not ttype.startswith(("TMID", "LMID", "RMID", "BMID", "ECLK")):
                continue
            muxes, fixed = tiledb.load_tiletype(nat.db_root, nat.family, ttype)
            # left/right pads: JINCK is a one-option mux (JPADDI, no bits) in ECLK_L/R
            # (the no-bits option is the idle default: skipped when the config drives the mux)
            fixed = list(fixed) + [
                (k, o) for k, v in muxes.items() if loc.match(k) and (row, col, k) not in driven
                for o in v if loc.match(o)]
            for sink, src in fixed:
                ends = []
                for nm in (sink, src):
                    ends.append(self.clock_key(row, col, nm) if nm.startswith("G_")
                                else (self.gkey(row, col, nm) if loc.match(nm) else None))
                if None not in ends:
                    pairs.append(tuple(ends))
        for _ in range(2):
            for a, b in pairs:
                if a in dsu.p or b in dsu.p:
                    dsu.union(a, b)
                    n += 1
        return n

    def gkey(self, row, col, name):
        """Canonical node key for a wire name referenced at (row, col), or
        None if the name must not participate in the union-find.

        Returns None for:
          * off-grid results (globalise_net gave no location), and
          * ambiguous chip-globals (see _is_chip_global).

        Deliberately free of the MachXO2 edge-case surgery — those work around
        MachXO2 tile-DB defects that ECP5 does not share.
        """
        ck = self.clock_key(row, col, name)
        if ck is not None:
            return ck
        if self._is_chip_global(name):
            return None
        g = self.rg.globalise_net(row, col, name)
        if g.loc.x < 0 or g.loc.y < 0:
            return None
        # globalise may itself yield a placeholder-positioned global after
        # prefix stripping; re-check on the resolved name.
        if self._is_chip_global(self.rg.to_str(g.id)):
            return None
        return (g.loc.x, g.loc.y, g.id)

    def bels_of(self, row, col):
        rc = (row, col)
        if rc in self._bel_cache:
            return self._bel_cache[rc]
        t = self.rg.tiles.get(self._pt.Location(col, row))
        if t is None:
            self._bel_cache[rc] = {}
            return {}
        res = {}
        for bk, bel in t.bels.items():
            bname = self.rg.to_str(bk)
            pins = {}
            for pid, (wire, _pdir) in bel.pins.items():
                pins[self.rg.to_str(pid)] = self.remap(wire)
            res[bname] = pins
        self._bel_cache[rc] = res
        return res

    # ---- parsing -----------------------------------------------------------
    def parse_config(self, path):
        """Parse a Trellis ECP5 `.config` into tile-resolved form.

        Same grammar as MachXO2 (and the same SLICE key names), minus the
        additive `.bram_init` / `.efb_block` sections, which are a MachXO2
        native_config extension with no ECP5 equivalent.
        """
        pc = ParsedConfig()
        cur_rc = None
        with open(path) as fh:
            for line in fh:
                s = line.strip()
                m = TILE_RE.match(s)
                if m:
                    # ECP5 tilegrid names are authoritative; unlike MachXO2
                    # there is no PLC column-offset quirk to work around.
                    cur_rc = self.tile_rc.get(f"{m.group(1)}:{m.group(2)}")
                    if cur_rc is None:
                        cur_rc = self.tile_rc.get(m.group(1))
                    if cur_rc:
                        pc.tile_type[cur_rc] = m.group(2)
                    continue
                if cur_rc is None:
                    continue
                r, c = cur_rc
                me = ENUM_RE.match(s)
                if me:
                    pc.enums[(r, c)][me.group(1)] = me.group(2)
                else:
                    mw = WORD_RE.match(s)
                    if mw:
                        pc.words[(r, c)][mw.group(1)] = mw.group(2)
                m = ARC_RE.match(s)
                if m:
                    pc.arcs.append((r, c, m.group(1), m.group(2)))
                    continue
                m = LUT_RE.match(s)
                if m:
                    pc.lut_init[(r, c, m.group(1), m.group(2))] = m.group(3)
                    continue
                m = SENUM_RE.match(s)
                if m:
                    pc.slice_enum[(r, c, m.group(1))][m.group(2)] = m.group(3)

        # Record which clock/reset distribution muxes this bitstream actually
        # drives, so remap() can route slice control pins through them rather
        # than onto a dead bare wire.  Recomputed per config, and the bel cache
        # is dropped because remap() results depend on it.
        pc.alias_arcs = self._drop_ccu2_alias_arcs(pc)
        self._prefer_mux_nodes = {
            (r, c, sink) for (r, c, sink, _src) in pc.arcs
            if sink.startswith(("MUXCLK", "MUXLSR"))
        }
        self._bel_cache.clear()
        return pc

    _CCU2_ALIAS_ARC = re.compile(r"^(F5|FX)[A-D]_SLICE$")

    @classmethod
    def _drop_ccu2_alias_arcs(cls, pc):
        """`F# <- F5x_SLICE / FXx_SLICE` in a MODE=CCU2 slice is bit aliasing, not a
        wide mux: bits.db has mux F# option F5x_SLICE = F8B10 and CCU2.INJECT1_0 NO =
        F8B10 (FXx: F8B11 / INJECT1_1).  Diamond routes F#_SLICE -> F# there (all
        78 CCU2 slices of the oracle corpus).  Removed from pc.arcs; returns them."""
        keep, dropped = [], []
        for a in pc.arcs:
            r, c, sink, src = a
            m = re.match(r"^F([0-7])$", sink)
            if (m and cls._CCU2_ALIAS_ARC.match(src) and pc.slice_enum.get(
                    (r, c, "ABCD"[int(m.group(1)) // 2]), {}).get("MODE") == "CCU2"):
                dropped.append(a)
            else:
                keep.append(a)
        pc.arcs[:] = keep
        return dropped

    # ---- netlist recovery --------------------------------------------------
    def recover_netlist(self, pc):
        """Build nets + LUT4/FF cells from a ParsedConfig.

        Net naming order is first-reference order (n1, n2, ...) so output is
        stable across runs.
        """
        d = Design()
        dsu = d.dsu = DSU()
        src_keys = set()
        skipped = 0

        for (r, c, sink, source) in pc.arcs:
            ks = self.gkey(r, c, sink)
            kd = self.gkey(r, c, source)
            if ks is None and kd is None:
                skipped += 1
                continue
            if ks is None or kd is None:
                # One side is a dropped chip-global or off-grid name.  Keep
                # the resolved side as a singleton so it still gets a net
                # name (it is a real fabric node), but do not union — that is
                # what would fuse unrelated nets through the (0,0) globals.
                k = ks if ks is not None else kd
                dsu.union(k, k)
                skipped += 1
                continue
            dsu.union(ks, kd)
            src_keys.add(kd)

        d.n_arcs = len(pc.arcs)
        d.skipped_arcs = skipped
        # ECP5 has no EFB and no MachXO2-style PLC fast-connect table.
        d.efb_resolved = {}
        d.plc_fc_applied = 0
        d.clock_fc_applied = self.apply_clock_fixed_conns(dsu, pc)

        d.used_roots = {dsu.find(k) for k in src_keys}

        net_name = d.net_name
        counter = [0]

        def net_of(key):
            root = dsu.find(key)
            if root not in net_name:
                counter[0] += 1
                net_name[root] = f"n{counter[0]}"
            return net_name[root]

        def connected(key):
            return key in dsu.p

        # Slices whose LUT INIT is MEMORY, not a truth table.  In DPRAM/RAMW
        # mode the 16 INIT bits are the stored RAM contents, so neither the
        # constant-folding below nor the LUT4 emission further down may treat
        # them as logic: an all-zero distributed-RAM word is an empty memory,
        # not a constant-0 gate, and folding it silently deletes the read port
        # (and with it every cone behind the RAM — on a VexRiscv image, the
        # whole cache-tag path).
        ram_slices = {
            (r, c, sl) for (r, c, sl), e in pc.slice_enum.items()
            if e.get("MODE") in ("DPRAM", "RAMW", "RAMW_BLOCK")
        }

        # ---- degenerate (constant) LUTs ----
        # An all-0/all-1 INIT computes a constant regardless of its inputs.
        # Map such a LUT's F output root to the literal BEFORE any net is
        # named, so downstream LUT/FF input resolution sees the constant
        # instead of falling through to the 1'b0 default.
        const_by_root = {}
        for (r, c, sl, k), init in pc.lut_init.items():
            if (r, c, sl) in ram_slices:
                continue
            s = set(init)
            if s not in ({"0"}, {"1"}):
                continue
            pins = self.bels_of(r, c).get(f"SLICE{sl}.K{k}")
            if not pins:
                continue
            fkey = pins.get("F")
            if fkey is None:
                continue
            dsu.union(fkey, fkey)
            const_by_root[dsu.find(fkey)] = "1'b1" if s == {"1"} else "1'b0"

        def resolve(key, default):
            if key is None or not connected(key):
                return default
            root = dsu.find(key)
            if root in const_by_root:
                return const_by_root[root]
            return net_of(key)

        # ---- LUT4s ----
        for (r, c, sl, k), init in pc.lut_init.items():
            is_ram = (r, c, sl) in ram_slices
            # Constant-folding applies to logic only — see ram_slices.
            if not is_ram and set(init) in ({"0"}, {"1"}):
                continue
            pins = self.bels_of(r, c).get(f"SLICE{sl}.K{k}")
            if not pins:
                continue

            def innet(pn, _pins=pins):
                return resolve(_pins.get(pn), None)

            fkey = pins.get("F")
            if fkey is not None and not connected(fkey):
                # A distributed-RAM read output is driven through the LUT
                # memory, not by any config arc, so its node may not be in the
                # DSU yet.  Seed it so it gets a real net name instead of
                # resolving to None and orphaning everything downstream.
                dsu.union(fkey, fkey)
            z = net_of(fkey) if fkey is not None else None
            d.luts.append({
                "name": f"lut_r{r}c{c}_{sl}k{k}",
                "init": init,
                "a": innet("A"), "b": innet("B"),
                "c": innet("C"), "d": innet("D"),
                "z": z,
                "z_used": fkey is not None and dsu.find(fkey) in d.used_roots,
                "mode": pc.slice_enum.get((r, c, sl), {}).get("MODE", "LOGIC"),
            })

        # ---- flip-flops ----
        enum_def = plc_enum_defaults(self.dbroot)   # missing enum key = bits.db default
        plc_tiles = {(r, c) for (r, c, _sl) in pc.slice_enum}
        plc_tiles |= {(r, c) for (r, c, _sl, _k) in pc.lut_init}
        for (r, c) in sorted(plc_tiles):
            bels = self.bels_of(r, c)
            for sl in "ABCD":
                senum = pc.slice_enum.get((r, c, sl), {})
                for j in (0, 1):
                    pins = bels.get(f"SLICE{sl}.FF{j}")
                    if not pins:
                        continue
                    qkey = pins.get("Q")
                    if qkey is None:
                        continue
                    # A register is materialised if EITHER its Q drives routed
                    # fabric, OR the bitstream carries explicit REG{j} config
                    # for it.  The Q-drives-something test alone is not
                    # sufficient: nextpnr emits registers whose Q output goes
                    # nowhere routed (a captured value read only by scan/debug,
                    # or a register the packer placed but whose consumer was
                    # optimised away).  Those still occupy the site and still
                    # have REG{j}.SD/REGSET/LSRMODE bits set, so dropping them
                    # loses real state — 4 of VexRiscv's 1683 registers, all on
                    # one signal, which is exactly the kind of gap that reads
                    # as "close enough" until someone traces that signal.
                    has_cfg = any(f"REG{j}.{p}" in senum
                                  for p in ("SD", "REGSET", "LSRMODE"))
                    if not has_cfg and dsu.find(qkey) not in d.used_roots:
                        continue
                    sd = senum.get(f"REG{j}.SD", "1")
                    d_default = "1'b0"
                    if ff_d_source(senum, j) == "F":
                        dkey = bels.get(f"SLICE{sl}.K{j}", {}).get("F")
                        # A used register whose paired LUT slot has no INIT
                        # word had that LUT optimised away to a constant; its
                        # DI floats to the slice VCC, so the register loads 1.
                        if ((r, c, sl, str(j)) not in pc.lut_init
                                and (dkey is None or not connected(dkey))):
                            d_default = "1'b1"
                    else:
                        dkey = pins.get("M")

                    d.ffs.append({
                        "name": f"ff_r{r}c{c}_{sl}{j}",
                        "q": net_of(qkey),
                        "d": resolve(dkey, d_default),
                        "clk": resolve(pins.get("CLK"), "1'b0"),
                        "ce": resolve(pins.get("CE"), "1'b1"),
                        "lsr": resolve(pins.get("LSR"), "1'b0"),
                        "regset": senum.get(f"REG{j}.REGSET", enum_def[f"SLICE{sl}.REG{j}.REGSET"]),
                        "sd": sd,
                        "gsr": senum.get("GSR", enum_def[f"SLICE{sl}.GSR"]),
                    })

        # Force net names for every resolved arc endpoint, including pad nodes
        # that only touch hard IP or drive external pins — without this their
        # DSU roots exist but net_name has no entry and pad_net() returns None.
        for (r, c, sink, source) in pc.arcs:
            for name in (sink, source):
                k = self.gkey(r, c, name)
                if k is not None and k in dsu.p:
                    net_of(k)

        # ---- distributed RAM (DPRAM read + RAMW write) ----
        # A slice group in distributed-RAM mode stores data in the LUT SRAM
        # cells themselves: the write port (MODE=RAMW) drives the LUT memory,
        # and the read ports (MODE=DPRAM) present it on their K0/K1 F outputs.
        # That write->read path is INTERNAL to the LUT array — no config arc
        # and no fixed_conn describes it — so without help the read outputs
        # look undriven and every cone downstream of a distributed RAM comes
        # back dangling.  On a VexRiscv image that is the whole cache-tag path.
        #
        # Model each RAMW data bit as a pass-through pseudo-LUT (INIT=0xAAAA,
        # F=A) into the corresponding DPRAM slice's F outputs, so reachability
        # flows write-data -> read-data.  Runs AFTER all real nets are named so
        # net numbering is identical to a run with no distributed RAM.
        for (r, c, sl) in pc.slice_enum:
            if pc.slice_enum[(r, c, sl)].get("MODE") != "RAMW":
                continue
            bels_here = self.bels_of(r, c)
            ramw_pins = bels_here.get("SLICEC.RAMW", {})
            # 4-bit-wide write port; each bit is read back by one DPRAM slice.
            for bit, dpram_sl, ramw_pin in (
                (0, "A", "B1"), (1, "B", "D1"), (2, "C", "C1"), (3, "D", "A1")
            ):
                if pc.slice_enum.get((r, c, dpram_sl), {}).get("MODE") \
                        != "DPRAM":
                    continue
                d_key = ramw_pins.get(ramw_pin)
                if d_key is None or not connected(d_key):
                    continue
                d_net = net_of(d_key)
                for k in (0, 1):
                    f_key = bels_here.get(f"SLICE{dpram_sl}.K{k}", {}).get("F")
                    if f_key is None:
                        continue
                    if not connected(f_key):
                        dsu.union(f_key, f_key)
                    d.luts.append({
                        "name": f"dpram_r{r}c{c}_d{bit}k{k}",
                        "init": "1010101010101010",   # 0xAAAA: F = A
                        "a": d_net, "b": None, "c": None, "d": None,
                        "z": net_of(f_key),
                        "z_used": dsu.find(f_key) in d.used_roots,
                    })

        d.all_nets = sorted(set(net_name.values()), key=lambda s: int(s[1:]))
        return d

    # ---- pad connectivity --------------------------------------------------
    def arc_endpoint_sets(self, pc):
        """Nodes appearing as a config-arc source / sink.  An endpoint counts
        if IT resolves, even when the other end is a dropped chip-global, so
        clock and hard-IP pads are not misreported as dangling."""
        sinks, sources = set(), set()
        for (r, c, sink, source) in pc.arcs:
            ks = self.gkey(r, c, sink)
            kd = self.gkey(r, c, source)
            if ks is not None:
                sinks.add(ks)
            if kd is not None:
                sources.add(kd)
        return sources, sinks

    def load_efb_fixed_conns(self, dbroot=None):
        """ECP5 has no EFB.  Returns an empty mapping.

        Not an error: MachXO2's EFB is a WISHBONE/I2C/SPI hard block wired to
        the fabric by fixed pips absent from `.config`.  ECP5's comparable
        hard blocks (SERDES/DCU, USRMCLK, OSC) are not wired that way, so
        there is nothing to union in.  load.py calls this unconditionally.
        """
        return {}

    def apply_efb_fixed_conns(self, dsu, efb_conns, cfg_row=None, cfg_col=None):
        """No-op counterpart to load_efb_fixed_conns (see there)."""
        return {}       # {port: direction}, as MachXO2Lift returns

    def pad_fabric_node(self, row, col, pio, direction):
        """Fabric node for a PIO pad.  `direction` in {'in','out'}.

        ECP5 pads are a real PIO bel, so the node comes off the bel pin
        rather than MachXO2's JQ{n}/JA{n} joint-node convention:
          in  -> bel pin "O" (JPADDI{L}_PIO), the pad driving the fabric
          out -> bel pin "I" (PADDO{L}_PIO),  the fabric driving the pad
        remap() has already stripped the _PIO suffix to cross the fixed pip.
        """
        pins = self.bels_of(row, col).get(f"PIO{pio}")
        if not pins:
            return None
        return pins.get("O" if direction == "in" else "I")

    def pio_sites(self):
        """All (row, col, pio_letter) sites on the device that have a PIO bel.

        This is a property of the DEVICE, not of any bitstream: a pad exists
        whether or not the design configures it.  (An earlier version filtered
        by the tiles present in a parsed config and under-reported by a third
        — a PIO tile with no arcs and no enums emits no `.tile` block at all,
        yet its pads are still physically there.  Callers wanting only the
        pads a design uses should intersect with pad_fabric_node() results.)

        Ordered by (row, col, letter) for stable output.
        """
        out = []
        for (col, row), tile in self.rg.tiles.items():
            for bname in tile.bels:
                nm = self.rg.to_str(bname)
                if len(nm) == 4 and nm.startswith("PIO"):
                    out.append((row, col, nm[3]))
        return sorted(out)
