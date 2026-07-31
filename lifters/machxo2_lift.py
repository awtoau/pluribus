#!/usr/bin/env python3
"""Device-generic MachXO2 / Project-Trellis bitstream lifter.

This is the reusable engine behind the MachXO2 recovery pipeline. Nothing here
is board-specific: it takes a Trellis `.config` (the CRC-verified unpack of a
MachXO2 `.bin`) plus a device string, and produces electrical nets, a structural
LUT4 + flip-flop netlist, and per-pad fabric connectivity. Board wrapper scripts
just supply paths, the device, and the package.

Scope: MachXO2 (LCMXO2). The compressed-bitstream forced-deserialise and the
PIO/slice node conventions are family-specific; ECP5/MachXO3 would need their
own unpack path. Validated against one real bitstream so far -- use the
round-trip self-test (synthesise a known design -> lift -> compare) to extend
confidence to other images.

The three painful bridges, in ONE place so copies can't drift:
  * pad data rides fabric joint nodes, not the PIO bel pins: input pad -> JQ{idx}
    (config-arc SOURCE), output pad -> JA{idx} (config-arc SINK), idx=A0/B1/C2/D3.
  * slice bel pins live on internal "*_SLICE" nodes bridged to the switchbox by
    FIXED pips not present in .config -> strip a trailing "_SLICE".
  * globalise_net returns an INVALID (-1,-1) location for chip-global clock/spine
    names -> such arc endpoints are dropped so they cannot fuse unrelated nets.
"""

import json
import os
import re
from collections import defaultdict

DEF_BUILD_DIR = os.environ.get("TRELLIS_BUILD",
                               "tmp/prjtrellis/libtrellis/build")


def _default_dbroot():
    """Resolve the trellis database through the single toolchain resolver (#90).

    The old fallback was the literal path a since-removed in-tree prjtrellis
    checkout used to occupy, so any caller that did not export TRELLIS_DBROOT
    died on a missing devices.json instead of finding the installed database.
    """
    import sys
    _scripts = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "scripts")
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    import toolchain
    return toolchain.trellis_dbroot()


DEF_DBROOT = os.environ.get("TRELLIS_DBROOT") or _default_dbroot()

# EFB fixed connections are hard-wired routes between the EFB hard IP and the
# switchbox.  They are never emitted as `.config` arcs, so they are invisible
# to the normal routing-arc union-find; load_efb_fixed_conns() reads them out
# of CIB_CFG0/bits.db and apply_efb_fixed_conns() unions them in.
#
# There is deliberately no hand-written wire → port table here.  One used to
# exist (_EFB_FIXED_DRIVER_WIRES, listing E2_JF0 → JWBDATO0 and friends) but
# was dead code: bits.db is the only source, and a second hand-maintained copy
# of it could only ever drift.

# Regex matching the fabric-side wire for SPI/Timer fixed connections, which
# are device-size-prefixed (e.g. "1200_E3_JQ0", "2000_S14E4_JPADDIB_PIO").
# Group 1 is the device-size token, group 2 the local wire name for gkey().
#
# The token MATTERS: CIB_CFG0/bits.db carries the prefixed connections for
# every MachXO2 size at once, and for the pad-side ports they name different
# wires per size (JSPIMISOI is S11E2_JPADDID_PIO on the 1200 but
# S14E4_JPADDIB_PIO on the 2000).  Stripping the prefix without checking it
# unions this chip's EFB against three other devices' pads.
_EFB_PREFIXED_WIRE_RE = re.compile(r'^(\d+)_(\S+)$')

# Device-size token of an "LCMXO2-<size>[HC|HE|ZE]" part name.
_DEVICE_SIZE_RE = re.compile(r'-(\d+)')

TILE_RE = re.compile(r"^\.tile\s+(\S+):(\S+)")
ARC_RE = re.compile(r"^arc:\s+(\S+)\s+(\S+)")
LUT_RE = re.compile(r"^word:\s+SLICE([A-D])\.K([01])\.INIT\s+([01]+)")
SENUM_RE = re.compile(r"^enum:\s+SLICE([A-D])\.(\S+)\s+(\S+)")
ENUM_RE = re.compile(r"^enum:\s+(\S+)\s+(\S+)")
WORD_RE = re.compile(r"^word:\s+(\S+)\s+(\S+)")

# Additive sections emitted by scripts/native_config.py AFTER the tile blocks
# (the config pytrellis silently dropped at bitstream command 0x72):
#   .bram_init <index>  -- recovered EBR block-RAM contents.  <index> is the
#     sequential EBR *write index* from LSC_EBR_ADDRESS (native_config
#     build_bram_data), NOT a tile.  1024 whitespace-separated 9-bit hex words.
#   .efb_block sel <hex> flags <hex> len <n>  then  data: <hex bytes>
#     -- the 0x72 EFB peripheral config-register preloads (docs/cmd-0x72.md).
BRAM_INIT_RE = re.compile(r"^\.bram_init\s+(\d+)")
EFB_BLOCK_RE = re.compile(r"^\.efb_block\s+sel\s+(\S+)\s+flags\s+(\S+)\s+len\s+(\d+)")
EFB_DATA_RE = re.compile(r"^data:\s*(.*)$")

# Known buggy BASE_TYPE values that are actually PULLMODE=NONE artefacts.
# The prjtrellis MachXO2 database assigns overlapping bit patterns to PULLMODE=NONE
# and to OUTPUT_MIPI / SSTL25_I in the BASE_TYPE enum.  The result: any LVTTL33
# output with PULLMODE=NONE decodes as one of these spurious standards.
# See issue #11 (private) and handover-2026-06-23.md.
_PULLMODE_NONE_GHOST_IOSTDS = frozenset(
    ("OUTPUT_MIPI", "SSTL25_I", "OUTPUT_SSTL25_I")
)


def _correct_pio_iostandard(pio_enums: "dict[str, str]") -> "dict[str, str]":
    """Correct prjtrellis PULLMODE/BASE_TYPE overlap bug for MachXO2.

    When PULLMODE=NONE, the NONE bits (all zeros) overlap with the OUTPUT_MIPI
    encoding in the BASE_TYPE enum, causing LVTTL33 outputs to decode as
    OUTPUT_MIPI or SSTL25_I.  The correct IO standard is LVTTL33 in this case.

    Takes a dict whose keys are PIO-qualified property names
    (e.g. ``{"PIOA.BASE_TYPE": "OUTPUT_MIPI", "PIOA.PULLMODE": "NONE", ...}``)
    or plain property names for a single PIO slice
    (e.g. ``{"BASE_TYPE": "OUTPUT_MIPI", "PULLMODE": "NONE"}``).

    Returns a corrected copy; the original is not mutated.

    NOTE: apply this only at the point of reporting.  The raw pc.enums /
    sites dicts are kept unmodified so the original decoded values remain
    available for diagnostics.
    """
    corrected = dict(pio_enums)
    # Handle both "PIOA.PULLMODE" (full-key form from pc.enums) and
    # plain "PULLMODE" (per-PIO-slice form from fpga_iomap parse_config).
    found_full_key_form = False
    for pio in ('A', 'B', 'C', 'D'):
        qualified_pm  = f'PIO{pio}.PULLMODE'
        qualified_bt  = f'PIO{pio}.BASE_TYPE'
        if qualified_pm in corrected:
            # Full-key form: dict is indexed as "PIOA.PULLMODE" etc.
            found_full_key_form = True
            pm = corrected.get(qualified_pm)
            bt = corrected.get(qualified_bt)
            if pm == 'NONE' and bt in _PULLMODE_NONE_GHOST_IOSTDS:
                corrected[qualified_bt] = 'OUTPUT_LVTTL33'
        elif qualified_bt in corrected and corrected[qualified_bt] in _PULLMODE_NONE_GHOST_IOSTDS:
            # BASE_TYPE looks like a ghost (PULLMODE=NONE artefact) but the
            # corresponding PULLMODE key is absent.  In all real textcfg
            # output, PULLMODE=NONE and the ghost BASE_TYPE appear together —
            # seeing one without the other is a decoder inconsistency.
            # This is a hard error per project fail-fast policy (#81).
            from db import die
            die(
                f"PIO{pio}.BASE_TYPE={corrected[qualified_bt]!r} looks like a "
                f"PULLMODE=NONE ghost but PIO{pio}.PULLMODE is absent — "
                f"decoder inconsistency (both must appear together or neither). "
                f"Full dict: {dict(pio_enums)!r}"
            )

    if not found_full_key_form:
        # Plain-key form: single-PIO dict with "PULLMODE" / "BASE_TYPE".
        # This is used by fpga_iomap for per-PIO-slice dicts.
        pm = corrected.get('PULLMODE')
        bt = corrected.get('BASE_TYPE')
        if 'PULLMODE' in corrected or 'BASE_TYPE' in corrected:
            if pm == 'NONE' and bt in _PULLMODE_NONE_GHOST_IOSTDS:
                corrected['BASE_TYPE'] = 'OUTPUT_LVTTL33'
            elif bt in _PULLMODE_NONE_GHOST_IOSTDS and 'PULLMODE' not in corrected:
                # Ghost BASE_TYPE without PULLMODE — same decoder inconsistency as
                # the full-key case above.  Hard error per fail-fast policy (#81).
                from db import die
                die(
                    f"BASE_TYPE={bt!r} looks like a PULLMODE=NONE ghost but "
                    f"PULLMODE is absent from the PIO dict — decoder inconsistency. "
                    f"Full dict: {dict(pio_enums)!r}"
                )
        # If neither PULLMODE nor BASE_TYPE is present, the dict is a non-PIO
        # config dict (generic tile config, or truly empty) — pass through unchanged.

    return corrected


def ff_d_source(slice_enums, j):
    """Which slice wire feeds REG{j}'s D input: 'F' or 'M'.

    Trellis PLC bits.db defines REG{j}.SD with value 1 as the zero-state
    (bit clear, enum OMITTED from the textcfg), meaning DI — the FF is
    packed with its slice LUT and D comes through the internal F→DI
    path (nextpnr machxo2 pack.cc sets SD=1 when pairing FF+COMB).
    An explicit "SD 0" (bit set) means D comes from the fabric-routed
    M wire (nextpnr renames the port DI→M in that case).

    Getting this wrong is catastrophic and quiet: with the polarity
    inverted every FF resolves DI (which never appears in config arcs)
    and the whole netlist recovers d=1'b0 — a real bitstream came back
    with 1081 of its 1090 FFs constant-D before this was fixed, while
    every cell count, net name and LUT INIT still looked correct.
    scripts/ffd_stats.py is the regression guard.
    """
    return "F" if slice_enums.get(f"REG{j}.SD", "1") == "1" else "M"


class DSU:
    """Union-find over arbitrary hashable node keys."""

    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        root = x
        while self.p[root] != root:
            root = self.p[root]
        while self.p[x] != root:
            self.p[x], x = root, self.p[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


class ParsedConfig:
    """Raw, tile-resolved contents of a Trellis `.config`.

    enums[(row,col)] stores the raw decoded values from the bitstream --
    including any prjtrellis decode artefacts.  Use _correct_pio_iostandard()
    at the point of reporting PIO IO standards; do NOT mutate this dict.
    """

    def __init__(self):
        self.arcs = []                       # (row, col, sink, source)
        self.lut_init = {}                   # (row,col,slice,k) -> init16
        self.slice_enum = defaultdict(dict)  # (row,col,slice) -> {prop:val}
        self.tile_type = {}                  # (row,col) -> type
        self.enums = defaultdict(dict)       # (row,col) -> {enum_key:val}
        self.words = defaultdict(dict)       # (row,col) -> {word_key:bits}
        # Additive 0x72 sections (native_config).  bram_init keys are EBR
        # write indices (map to physical EBR1 tiles via that tile's EBR.WID
        # word — see load.py); efb_blocks keys are the 0x72 `sel` selector.
        self.bram_init = {}                  # ebr_write_index -> [1024 ints] (9-bit words)
        self.efb_blocks = {}                 # sel(int) -> [payload bytes]
        self.diamond_version = None          # Diamond version if known (e.g. "3.14.0.201")


class Design:
    """Recovered structural netlist (nets + LUT4s + flip-flops)."""

    def __init__(self):
        self.luts = []
        self.ffs = []
        self.net_name = {}      # dsu-root -> "n<k>"
        self.all_nets = []
        self.dsu = None
        self.used_roots = set()
        self.n_arcs = 0
        self.skipped_arcs = 0


class MachXO2Lift:
    """Routing-graph-backed lifter for one MachXO2 device."""

    def __init__(self, device, build_dir=DEF_BUILD_DIR, dbroot=DEF_DBROOT):
        import sys
        # Backend: pure-Python native routing graph (default, no .so) or the
        # legacy pytrellis .so (PLURIBUS_TRELLIS_BACKEND=so) for A/B parity.
        if os.environ.get("PLURIBUS_TRELLIS_BACKEND", "native") == "so":
            if build_dir not in sys.path:
                sys.path.insert(0, build_dir)
            import pytrellis
        else:
            _repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if _repo not in sys.path:
                sys.path.insert(0, _repo)
            from native_trellis import pytrellis_compat as pytrellis
        self._pt = pytrellis
        pytrellis.load_database(dbroot)
        self.device = device
        self.chip = pytrellis.Chip(device)
        self.rg = self.chip.get_routing_graph(True, True)

        # tile FULL "name:type" -> (row, col)
        self.tile_rc = {}
        for r in range(self.chip.get_max_row() + 1):
            for c in range(self.chip.get_max_col() + 1):
                try:
                    for t in self.chip.get_tiles_by_position(r, c):
                        self.tile_rc[t.info.name] = (r, c)
                except Exception:
                    pass

        self._wn_index = {}
        self._bel_cache = {}

    # ---- node-key helpers --------------------------------------------------
    def wname_id(self, col, row, name):
        key = (col, row)
        idx = self._wn_index.get(key)
        if idx is None:
            idx = {}
            try:
                t = self.rg.tiles[self._pt.Location(col, row)]
                for wid in t.wires.keys():
                    idx[self.rg.to_str(wid)] = wid
            except Exception:
                pass
            self._wn_index[key] = idx
        return idx.get(name)

    def remap(self, wire):
        """A bel pin's RoutingId -> the canonical fabric-node key the config
        arcs reference. Strips a trailing '_SLICE' to cross the fixed pip."""
        nm = self.rg.to_str(wire.id)
        col, row = wire.loc.x, wire.loc.y
        if nm.endswith("_SLICE"):
            fid = self.wname_id(col, row, nm[:-6])
            if fid is not None:
                return (col, row, fid)
        return (col, row, wire.id)

    # Segment longline prefixes: N-hop wires (N=1,3,6) whose canonical endpoint
    # can fall off the chip boundary when the wire origin is within N tiles of
    # the edge.  globalise_net() returns (-1,-1) in that case even though the
    # wire is real and has a well-defined canonical position.  Recovery: walk the
    # origin toward the interior by 1..N tiles — the canonical key is identical
    # at every valid origin, so the first success is authoritative.
    _SEG_EAST  = re.compile(r'^E(\d)_')   # eastward N-hop → walk west (col-1)
    _SEG_WEST  = re.compile(r'^W(\d)_')   # westward N-hop → walk east (col+1)
    _SEG_NORTH = re.compile(r'^N(\d)_')   # northward N-hop → walk south (row+1)
    _SEG_SOUTH = re.compile(r'^S(\d)_')   # southward N-hop → walk north (row-1)

    # Vertical span longline base name (V<span><N|S><idx>).  At the top edge
    # (globalised row 0) a V##N/V##S span wire (span >= 2) is a truncated end of
    # a vertical longline whose continuation lands one row into the interior as
    # the opposite-direction wire of the same span/index.  See gkey().
    _VSPAN = re.compile(r'^V(\d+)([NS])(\d+)$')

    @staticmethod
    def _mirror_e_h06e(name):
        """Remap an E{N}_H06E{M} wire name to W{N}_H06W{M} for PIC_R tiles.

        In PIC_R0 (right-edge IO) tiles, prjtrellis emits H06 pad-to-bus pips
        as E{N}_H06E{M}.  The mirrored W{N}_H06W{M} form is safe to pass to
        globalise_net and returns the correct wire id.  The caller then fixes
        the canonical column to max_col so DSU unifies with interior arcs that
        reference the same bus as H06W{M} (local, anchored at max_col)."""
        m = re.match(r'^E(\d)_H06E(\d+)$', name)
        if m:
            return f"W{m.group(1)}_H06W{m.group(2)}"
        return None

    def _v02_alias(self, x, y, wire_id):
        """Canonicalise a globalised key onto the V02N form of its span.

        Some plain V02S#### names resolve to isolated fanin=0 copies while their
        V02N mates carry the drivers (issue #65).  Kept narrow -- span 2, indices
        0601/0701 only -- because broad vertical-span merges trigger the #78
        pad/FF fusion.

        EVERY exit from gkey's valid-globalise path must come through here.  The
        bare-name rewrite at the top of gkey flips S->N before globalising, and
        the top/bottom-edge rule flips N->S after; if either bypasses this, one
        physical wire ends up with two canonical keys and its net splits in two.
        Both of today's #46 net-merge failures were exactly that (#46).
        """
        if x < 0 or y < 0:
            return (x, y, wire_id)
        mv = self._VSPAN.match(self.rg.to_str(wire_id))
        if not (mv and mv.group(2) == 'S' and int(mv.group(1)) == 2
                and mv.group(3) in ('0601', '0701')):
            return (x, y, wire_id)
        flip_name = f"V{mv.group(1)}N{mv.group(3)}"
        if self.wname_id(x, y, flip_name) is None:
            return (x, y, wire_id)
        gm = self.rg.globalise_net(y, x, flip_name)
        if gm.loc.x < 0 or gm.loc.y < 0:
            return (x, y, wire_id)
        # Compare the whole KEY, not just the location: this remap's job is to
        # change the wire id AT the same location, so a location-only guard
        # would reject precisely the cases it exists to fix.
        gk = (gm.loc.x, gm.loc.y, gm.id)
        return gk if gk != (x, y, wire_id) else (x, y, wire_id)

    def gkey(self, row, col, name):
        """Canonical node key, or None if the name globalises to an invalid
        (-1,-1) location (chip-global clock/spine longlines).

        For segment longlines (E3/W3/N3/S3 etc.) that fail at chip-edge tiles
        because their canonical endpoint would fall off the grid, we walk the
        origin back into the interior — the canonical key is the same for every
        valid origin of the same wire.

        Right-edge boundary fix: E{N}_H06E{M} wires at PIC_R tiles (col ==
        max_col) are remapped to W{N}_H06W{M} before globalising, because
        prjtrellis encodes these pips with the wrong E/W sense for the right
        boundary.  E{N}_H06E{M} arcs at interior PLC tiles within N columns of
        the right edge would canonicalise to an off-chip position — their
        walk-back incorrectly collapses them to the same canonical key as the
        PIC_R tile's H06E wire, merging unrelated nets.  We detect this case
        (col + N > max_col at a non-boundary tile) and return None instead of
        the wrong key, so those stub arcs are silently dropped rather than
        causing a net-merge bug."""
        # Issue #65: in recovered configs, these plain V02S local names can be
        # dead-end aliases while their V02N counterparts carry the routed net.
        # Keep this mapping intentionally narrow to avoid broad V-span merges.
        if name == "V02S0601":
            name = "V02N0601"
        elif name == "V02S0701":
            name = "V02N0701"

        g = self.rg.globalise_net(row, col, name)
        if g.loc.x >= 0 and g.loc.y >= 0:
            # Top/bottom-edge vertical-span canonicalization (net_merge_gap
            # defect).  When a name globalises to row 0 (top) or the max row
            # (bottom) and is a V##N/V##S span wire (span >= 2) it is a truncated
            # end of a vertical longline: the two ends land as V##N@(col,edge)
            # (driver/injection side) and V##S@(col,edge) (load/source side),
            # while the wire's load-bearing continuation lands one row into the
            # interior as the opposite-direction wire of the same span/index
            # (V##S resp. V##N).  globalise_net hands the two ends distinct keys,
            # so a signal driven onto the edge wire and consumed on its
            # continuation never unions -- leaving the recovered output/clock net
            # dangling.  Remap the truncated end onto its interior continuation
            # (one row inward) so they fuse into one net.  Keys off the
            # globalised RESULT row (not the input row) so hop-prefixed
            # references (e.g. a "N1_V<span>N<idx>" vertical longline) -- which
            # resolve to the edge from an interior tile -- are caught too.
            max_row = self.chip.get_max_row()
            if g.loc.y in (0, max_row):
                mv = self._VSPAN.match(self.rg.to_str(g.id))
                if mv and int(mv.group(1)) >= 2:
                    flip = "S" if mv.group(2) == "N" else "N"
                    cname = f"V{mv.group(1)}{flip}{mv.group(3)}"
                    crow = 1 if g.loc.y == 0 else max_row - 1
                    if self.wname_id(g.loc.x, crow, cname) is not None:
                        gc = self.rg.globalise_net(crow, g.loc.x, cname)
                        if gc.loc.x >= 0 and gc.loc.y >= 0:
                            # Normalise like every other exit, do NOT return
                            # raw.  This branch flips N->S; the bare-name
                            # rewrite at the top of gkey flips S->N.  Returning
                            # early let the two meet at one location holding
                            # opposite letters -- one physical wire, two keys.
                            # That is what stranded top-edge pads 85 and 86.
                            return self._v02_alias(gc.loc.x, gc.loc.y, gc.id)
            # Main return
            return self._v02_alias(g.loc.x, g.loc.y, g.id)

        # Walk-back recovery for segment longlines near chip boundaries.
        m = (self._SEG_EAST.match(name)  or self._SEG_WEST.match(name) or
             self._SEG_NORTH.match(name) or self._SEG_SOUTH.match(name))
        if m:
            hops = int(m.group(1))
            wire = m.string
            is_east  = wire[0] == 'E'
            is_north = wire[0] == 'N'
            max_col  = self.chip.get_max_col()
            max_row  = self.chip.get_max_row()

            # Right-edge guard: E{N}_H06E{M} wires where col+hops > max_col.
            # At the PIC_R tile (col == max_col): _mirror_e_h06e converts to
            # W{N}_H06W{M} which globalise_net resolves to (col-N, row, id).
            # The same physical bus is referenced by interior arcs at the same
            # right-edge tile as H06W{M} with canonical (col, row, id).
            # We override the column to max_col (col) so DSU unifies the pad
            # wire with those downstream routing arcs.
            # At PLC tiles interior to the boundary (col < max_col): this is a
            # dead stub whose true canonical falls off-chip; return None to
            # suppress the arc rather than collapsing it to the PIC_R tile's
            # canonical (which would wrongly merge pad inputs with FF outputs).
            if is_east and col + hops > max_col:
                if col == max_col:
                    mirrored = self._mirror_e_h06e(name)
                    if mirrored:
                        gm = self.rg.globalise_net(row, col, mirrored)
                        if gm.loc.x >= 0 and gm.loc.y >= 0:
                            # Anchor at max_col, not col-N, to match H06W{M} local refs.
                            return (col, gm.loc.y, gm.id)
                    # General right-edge horizontal span (net_merge_gap defect):
                    # an off-right-edge E{N}_H##{E|W}{idx} stub is the same
                    # physical wire as the opposite-direction H## wire of the
                    # same index at max_col (mirror of the top-edge vertical fix,
                    # on the column axis).  Columns are 1-based with no dedicated
                    # left/right PIO tiles, so the stub globalises off-chip; remap
                    # it onto the interior continuation so the net does not dangle.
                    hme = re.match(r'^E\d+_H(\d+)([EW])(\d+)$', name)
                    if hme and hme.group(1) != "06":
                        flip = "W" if hme.group(2) == "E" else "E"
                        cname = f"H{hme.group(1)}{flip}{hme.group(3)}"
                        gc = self.rg.globalise_net(row, max_col, cname)
                        if gc.loc.x >= 0 and gc.loc.y >= 0:
                            return (gc.loc.x, gc.loc.y, gc.id)
                # No valid canonical (off-chip stub or mirror failed).
                return None

            # Symmetric guard for W-direction wires at the left edge.
            if not is_east and wire[0] == 'W' and col - hops < 0:
                if col == 0:
                    # Symmetric mirror: W{N}_H06W{M} → E{N}_H06E{M}
                    mirror_m = re.match(r'^W(\d)_H06W(\d+)$', name)
                    if mirror_m:
                        mirrored = f"E{mirror_m.group(1)}_H06E{mirror_m.group(2)}"
                        gm = self.rg.globalise_net(row, col, mirrored)
                        if gm.loc.x >= 0 and gm.loc.y >= 0:
                            return (gm.loc.x, gm.loc.y, gm.id)
                    # General left-edge horizontal span (net_merge_gap defect):
                    # an off-left-edge W{N}_H##{E|W}{idx} stub is the same
                    # physical wire as the opposite-direction H## wire of the
                    # same index at col 0 (mirror of the top-edge vertical fix,
                    # on the column axis).  Remap it onto that continuation.
                    hmw = re.match(r'^W\d+_H(\d+)([EW])(\d+)$', name)
                    if hmw and hmw.group(1) != "06":
                        flip = "E" if hmw.group(2) == "W" else "W"
                        cname = f"H{hmw.group(1)}{flip}{hmw.group(3)}"
                        gc = self.rg.globalise_net(row, 0, cname)
                        if gc.loc.x >= 0 and gc.loc.y >= 0:
                            return (gc.loc.x, gc.loc.y, gc.id)
                return None

            # Vertical span whose hop runs off the top/bottom edge.
            #
            # The generic walk-back below assumes "the canonical key is the same
            # for every valid origin of the same wire".  For a vertical span that
            # is FALSE: moving the origin moves the destination too, so walking
            # back one row silently returns the NEIGHBOURING wire -- a key two
            # rows from the truth, carrying the wrong direction letter.  One
            # physical span then gets two keys and the net splits.
            #
            # A V-span's N and S names at one tile are the two ends of the same
            # physical wire.  When the hop leaves the die, the wire is simply the
            # one named locally in the opposite direction, at the ORIGINAL tile.
            # Verified on two independent cases at opposite edges: the ident mux
            # select stranded at the top edge (N3_V06N0003 -> V06S0003) and the
            # bottom-edge output pads of pins 45/85/86 (S3_V06N0303 -> V06S0303).
            # This only runs where globalise_net already failed, so it cannot
            # disturb spans that resolve normally.
            mvs = re.match(r'^[NS]\d+_V(\d+)([NS])(\d+)$', name)
            if mvs and ((is_north and row - hops < 0)
                        or (not is_north and wire[0] == 'S'
                            and row + hops > max_row)):
                flip = "S" if mvs.group(2) == "N" else "N"
                bare = f"V{mvs.group(1)}{flip}{mvs.group(3)}"
                gv = self.rg.globalise_net(row, col, bare)
                if gv.loc.x >= 0 and gv.loc.y >= 0:
                    return (gv.loc.x, gv.loc.y, gv.id)

            for delta in range(1, hops + 1):
                if is_east or wire[0] == 'W':
                    probe_col = col - delta if is_east else col + delta
                    probe_row = row
                else:
                    probe_col = col
                    probe_row = row + delta if is_north else row - delta
                if not (0 <= probe_col <= max_col and 0 <= probe_row <= max_row):
                    continue
                g2 = self.rg.globalise_net(probe_row, probe_col, name)
                if g2.loc.x >= 0 and g2.loc.y >= 0:
                    return (g2.loc.x, g2.loc.y, g2.id)

        return None

    def bels_of(self, row, col):
        rc = (row, col)
        if rc in self._bel_cache:
            return self._bel_cache[rc]
        try:
            t = self.rg.tiles[self._pt.Location(col, row)]
        except Exception:
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
        pc = ParsedConfig()
        cur_rc = None
        # Additive-section state.  The `.bram_init` / `.efb_block` sections are
        # emitted AFTER every `.tile` block; `mode` switches the parser out of
        # tile mode so their body lines are captured instead of silently
        # dropped by the tile-mode dispatch below.
        mode = "tile"          # "tile" | "bram" | "efb"
        cur_bram = None        # list currently being filled (points into pc.bram_init)
        cur_efb_sel = None     # sel of the .efb_block being filled
        with open(path) as fh:
            for line in fh:
                s = line.strip()
                # -- additive section headers (may follow the last tile) -------
                mb = BRAM_INIT_RE.match(s)
                if mb:
                    mode, cur_rc = "bram", None
                    cur_bram = []
                    pc.bram_init[int(mb.group(1))] = cur_bram
                    continue
                mf = EFB_BLOCK_RE.match(s)
                if mf:
                    mode, cur_rc = "efb", None
                    cur_efb_sel = int(mf.group(1), 0)   # group(1)=sel, (2)=flags, (3)=len
                    continue
                m = TILE_RE.match(s)
                if m:
                    mode = "tile"
                    # tile_rc is AUTHORITATIVE and the textual R/C in a tile
                    # name is not.  Trellis tile names number columns from 1
                    # ("R2C12:PLC") while routing-graph positions number them
                    # from 0 (that tile is at col 11) -- a naming convention,
                    # not a database error.  Reading coordinates out of the
                    # name shifts every R<r>C<c> tile (all PLC/EBR) one column
                    # right while prefixed tiles (CIB_*, PT*, PB*, PL*, PR*)
                    # stay put, which desynchronises PLC internals from the
                    # surrounding CIB routing chip-wide: FF/LUT outputs stop
                    # merging with the pad nets they drive.  Doing that cost
                    # 438 of 454 corpus targets their equivalence proof (#46).
                    cur_rc = self.tile_rc.get(f"{m.group(1)}:{m.group(2)}")
                    if cur_rc:
                        pc.tile_type[cur_rc] = m.group(2)
                    continue
                # -- additive section bodies -----------------------------------
                if mode == "bram":
                    if s:  # whitespace-separated 9-bit hex words, 8 per line
                        cur_bram.extend(int(tok, 16) for tok in s.split())
                    continue
                if mode == "efb":
                    md = EFB_DATA_RE.match(s)
                    if md:
                        pc.efb_blocks[cur_efb_sel] = [
                            int(tok, 16) for tok in md.group(1).split()
                        ]
                    continue
                if cur_rc is None:
                    continue
                r, c = cur_rc
                # generic enum/word capture (hard IP: PLL, sysCONFIG, EBR) --
                # additive; the specific SLICE/LUT captures below are unchanged.
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
        return pc

    # ---- netlist recovery --------------------------------------------------
    def recover_netlist(self, pc):
        """Build nets + LUT4/FF cells from a ParsedConfig. Net naming order is
        preserved (n1, n2, ... in first-reference order) for stable output."""
        d = Design()
        dsu = d.dsu = DSU()
        src_keys = set()
        skipped = 0
        # JQ{idx} = pad input joint node; JA{idx} = pad output joint node.
        # At right/top/bottom-edge tiles, globalise_net() on the pad-side wire
        # name can return (-1,-1) (invalid) while the routing-side wire resolves
        # correctly. Detect this case: if sink OR source is a JQ/JA name, use
        # pad_fabric_node() as the authoritative canonical key for that side and
        # union it with the resolved routing-side key.
        import re as _re
        _JQ_RE = _re.compile(r'^JQ(\d)$')
        _JA_RE = _re.compile(r'^JA(\d)$')
        def _pad_key_for(r, c, name):
            m = _JQ_RE.match(name)
            if m:
                return self.pad_fabric_node(r, c, chr(ord('A') + int(m.group(1))), 'in')
            m = _JA_RE.match(name)
            if m:
                return self.pad_fabric_node(r, c, chr(ord('A') + int(m.group(1))), 'out')
            return None

        for (r, c, sink, source) in pc.arcs:
            ks = self.gkey(r, c, sink)
            kd = self.gkey(r, c, source)
            # If either side failed to globalise, try pad_fabric_node fallback
            if ks is None:
                ks = _pad_key_for(r, c, sink)
            if kd is None:
                kd = _pad_key_for(r, c, source)
            if ks is None and kd is None:
                skipped += 1
                continue
            if ks is None or kd is None:
                # One side failed to globalise (common for routing wires at
                # right/top/bottom-edge tiles). Add the resolved side as a
                # singleton so it gets a net name even without a union partner.
                k = ks if ks is not None else kd
                dsu.union(k, k)
                skipped += 1
                continue
            dsu.union(ks, kd)
            src_keys.add(kd)
        d.n_arcs = len(pc.arcs)
        d.skipped_arcs = skipped

        # Union EFB output fixed connections.  These are hard-wired EFB→fabric
        # routes not present in the .config arcs.  Reading them from bits.db
        # and unioning them here lets any FF whose D-input wire traces back to
        # an EFB output get a real net name instead of "1'b0".
        # CIB_CFG0 tile location varies by device — look it up from the parsed
        # config rather than hardcoding, so LCMXO2-1200 (col=3) vs other sizes
        # (col=4 or larger) all resolve correctly.
        cfg0_loc = next(
            ((r, c) for (r, c), t in pc.tile_type.items() if t == "CIB_CFG0"),
            (1, 4),
        )
        efb_conns = self.load_efb_fixed_conns()
        d.efb_resolved = self.apply_efb_fixed_conns(
            dsu, efb_conns, cfg_row=cfg0_loc[0], cfg_col=cfg0_loc[1]
        )

        # Union PLC slice-output fast connections (F0..F7 -> adjacent-tile
        # HFxW/HFxE wires).  These always-on direct routes are absent from the
        # .config; without them a slice output that leaves the tile on a
        # fast-connect wire lands on an undriven fabric net, orphaning every cone
        # that reads it (the SPI-readback / miso path, issue #65).
        plc_conns = self.load_plc_fixed_conns()
        plc_tiles = [rc for rc, t in pc.tile_type.items() if t == "PLC"]
        d.plc_fc_applied = self.apply_plc_fixed_conns(dsu, plc_conns, plc_tiles)

        # Carry chain, at CCU2 tiles ONLY.  A carry chain exists only through
        # CCU2 slices, so restricting the unions to those tiles wires up every
        # real chain without merging the dedicated carry wires of the whole
        # device into one net.
        ccu2_tiles = [(r, c) for (r, c, _sl), e in pc.slice_enum.items()
                      if e.get("MODE") == "CCU2"]
        d.plc_carry_applied = self.apply_plc_fixed_conns(
            dsu, self.load_plc_carry_conns(), sorted(set(ccu2_tiles)))

        # Wide-mux tree.  Unlike the carry chain there is no config bit saying
        # a slice uses its muxes, so this must go in at every PLC tile; the
        # wiring is hardwired in silicon regardless, and a mux nothing drives
        # or reads simply leaves an inert net behind.
        d.plc_ofx_applied = self.apply_plc_fixed_conns(
            dsu, self.load_plc_ofx_conns(), plc_tiles)

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

        # ---- degenerate (constant) LUTs ----
        # A LUT whose INIT is all-0 / all-1 computes a constant regardless of its
        # inputs.  Such cells are not emitted as logic, but their fabric output
        # net must resolve to the constant: without this a downstream FF/LUT that
        # reads an all-1 LUT falls through to the "1'b0" default and a constant 1
        # is silently recovered as 0.  Map the DSU root of each constant LUT's F
        # output to the literal here (after all arc/EFB unions, before any net is
        # named) so both LUT-input and FF-input resolution see it.
        const_by_root = {}
        for (r, c, sl, k), init in pc.lut_init.items():
            s = set(init)
            if s not in ({"0"}, {"1"}):
                continue
            # In CCU2 mode F is `LUT4(INIT) XOR carry-in`, so even an all-0 INIT
            # does NOT make F constant -- it makes F track FCI.  Leave these to
            # the CCU2 pass below.
            if pc.slice_enum.get((r, c, sl), {}).get("MODE") == "CCU2":
                continue
            pins = self.bels_of(r, c).get(f"SLICE{sl}.K{k}")
            if not pins:
                continue
            fkey = pins.get("F")
            if fkey is None:
                continue
            dsu.union(fkey, fkey)          # ensure the root exists in the DSU
            const_by_root[dsu.find(fkey)] = "1'b1" if s == {"1"} else "1'b0"

        def resolve(key, default):
            """Net name for key, a constant literal if the key resolves to a
            degenerate (constant) LUT output, or `default` if unconnected."""
            if key is None or not connected(key):
                return default
            root = dsu.find(key)
            if root in const_by_root:
                return const_by_root[root]
            return net_of(key)

        # ---- LUT4s ----
        for (r, c, sl, k), init in pc.lut_init.items():
            if set(init) in ({"0"}, {"1"}):
                continue
            # A CCU2 (carry) slice's F output is NOT the bare LUT4 -- it is
            # `LUT4(INIT) XOR carry-in`.  Emitting it here as a plain LUT4 does
            # not under-connect, it MIS-connects: the recovered logic silently
            # drops the carry term.  The CCU2 pass below models it properly.
            if pc.slice_enum.get((r, c, sl), {}).get("MODE") == "CCU2":
                continue
            pins = self.bels_of(r, c).get(f"SLICE{sl}.K{k}")
            if not pins:
                continue

            def innet(pn):
                return resolve(pins.get(pn), None)

            fkey = pins.get("F")
            z = net_of(fkey) if fkey is not None else None
            d.luts.append({
                "name": f"lut_r{r}c{c}_{sl}k{k}",
                "init": init,
                "a": innet("A"), "b": innet("B"),
                "c": innet("C"), "d": innet("D"),
                "z": z,
                "z_used": fkey is not None and dsu.find(fkey) in d.used_roots,
            })

        plc_tiles = {(r, c) for (r, c, _sl) in pc.slice_enum}
        plc_tiles |= {(r, c) for (r, c, _sl, _k) in pc.lut_init}

        # ---- wide muxes (PFUMX -> OFX0, L6MUX21 -> OFX1) and CCU2 carry ----
        #
        # Runs BEFORE the flip-flop pass, exactly as the plain-LUT pass does:
        # a register fed straight off its paired LUT reads that LUT's F key out
        # of the DSU, and only emitting the cell puts the key there.  Run this
        # after the FF pass instead and every CCU2 sum feeding a register
        # silently resolves to the 1'b0 default.
        #
        # Both are pure SLICE STRUCTURE: no config bit enables them, so their
        # presence is decided entirely by the routing graph (is the OFX output
        # net consumed? is MODE=CCU2?).  Neither was modelled before, which is
        # why a 64:1 constant mux ("read back an ident over SPI") recovered with
        # its output net undriven, and why every counter recovered without its
        # carry term (#46).
        #
        # Semantics are the vendor's, from Lattice's own simulation model
        # (yosys lattice/common_sim.vh, module TRELLIS_COMB):
        #     PFUMX    lut5_mux (.ALUT(F1), .BLUT(F),   .C0(M), .Z(OFX));  -> OFX0 = M ? F1  : F
        #     L6MUX21  lutx_mux (.D0(FXA),  .D1(FXB),   .SD(M), .Z(OFX));  -> OFX1 = M ? FXB : FXA
        #     CCU2:  F   = LUT4(INIT)(A,B,C,D) ^ (INJECT1 ? 0 : FCI)
        #            FCO = (~l4o & (INJECT1 ? 0 : LUT2(INIT[3:0])(A,B))) | (l4o & FCI)
        # and the ALUT/BLUT sense is corroborated by nextpnr's ECP5 packer,
        # which moves PFUMX.ALUT onto the LUT's F1 pin (ecp5/pack.cc).
        #
        # Emitted as pseudo-LUT4 cells -- the same device the distributed-RAM
        # pass above uses -- so no new cell type reaches the schema, load.py,
        # verilog.py or the reachability passes.  A 2:1 mux `Z = C ? B : A` is
        # INIT=0xCACA; `Z = A ^ B` is INIT=0x6666.
        MUX2_INIT = "1100101011001010"   # 0xCACA: Z = C ? B : A
        XOR2_INIT = "0110011001100110"   # 0x6666: Z = A ^ B
        carry_driven = set()             # FCO roots we have emitted a driver for

        def internal_net(tag):
            """Name a net internal to a slice (no fabric wire, hence no DSU
            root).  Keyed off the DSU-root namespace with a marker tuple that
            no (row, col, wire) key can collide with, so it still lands in
            all_nets and keeps the n<k> numbering contiguous."""
            counter[0] += 1
            name = f"n{counter[0]}"
            net_name[("slice_internal", tag)] = name
            return name

        for (r, c) in sorted(plc_tiles):
            bels = self.bels_of(r, c)

            # -- wide muxes --
            # Every slice HAS both muxes, so emitting them unconditionally would
            # add 8 dead cells per PLC tile chip-wide.  A mux is in this design
            # if its OFX output is consumed, and there are two ways to consume
            # it: the switchbox routes it away (an arc source, hence a used
            # root), or -- for OFX0 only -- it feeds an OFX1 mux over the
            # hardwired FXA/FXB tree, which is a fixed_conn and never an arc.
            # Miss the second and a LUT6 recovers with its top mux driven by
            # nothing, which is exactly how the 64:1 ident mux lost `miso`.
            def _ofx_key(sl, k):
                pins = bels.get(f"SLICE{sl}.K{k}")
                ofx = pins.get("OFX") if pins else None
                return pins, ofx

            wanted = set()
            for sl in "ABCD":
                pins, ofx = _ofx_key(sl, 1)
                if ofx is None or dsu.find(ofx) not in d.used_roots:
                    continue
                wanted.add((sl, 1))
                for p in ("FXA", "FXB"):      # what this LUT6's halves need
                    k_in = pins.get(p)
                    if k_in is not None:
                        wanted.add(dsu.find(k_in))
            for sl in "ABCD":
                _pins, ofx = _ofx_key(sl, 0)
                if ofx is not None and (dsu.find(ofx) in d.used_roots
                                        or dsu.find(ofx) in wanted):
                    wanted.add((sl, 0))

            for sl in "ABCD":
                for k, (a_pin, b_pin) in ((0, ("F", "F1")), (1, ("FXA", "FXB"))):
                    if (sl, k) not in wanted:
                        continue
                    pins, ofx = _ofx_key(sl, k)
                    d.luts.append({
                        "name": f"ofx{k}_r{r}c{c}_{sl}",
                        "init": MUX2_INIT,
                        "a": resolve(pins.get(a_pin), "1'b0"),
                        "b": resolve(pins.get(b_pin), "1'b0"),
                        "c": resolve(pins.get("M"), "1'b0"),
                        "d": None,
                        "z": net_of(ofx),
                        "z_used": True,
                    })

            for sl in "ABCD":
                senum = pc.slice_enum.get((r, c, sl), {})

                # -- CCU2 carry --
                if senum.get("MODE") != "CCU2":
                    continue
                for k in (0, 1):
                    init = pc.lut_init.get((r, c, sl, str(k)))
                    pins = bels.get(f"SLICE{sl}.K{k}")
                    if init is None or not pins:
                        continue
                    fkey = pins.get("F")
                    if fkey is None:
                        continue
                    inject = senum.get(f"CCU2.INJECT1_{k}", "NO") == "YES"
                    # The carry-in only exists if something drives it: the
                    # chain head's FCI is unioned to the tile's routing-side
                    # node by a fixed_conn, so it always resolves to SOME net
                    # even when the chain starts here.  Accept it only when an
                    # arc really sources it, or when we emitted the FCO that
                    # feeds it; otherwise the head would read a floating net.
                    fci_key = pins.get("FCI")
                    fci = "1'b0"
                    if fci_key is not None:
                        fr = dsu.find(fci_key)
                        if fr in d.used_roots or fr in carry_driven:
                            fci = resolve(fci_key, "1'b0")
                    # INJECT1 gates the carry out of the SUM only.
                    fci_sum = "1'b0" if inject else fci
                    ins = {p: resolve(pins.get(p), None) for p in "ABCD"}
                    base = f"r{r}c{c}_{sl}k{k}"

                    if fci_sum == "1'b0":
                        l4o = net_of(fkey)          # F == l4o, emit straight out
                    else:
                        l4o = internal_net(f"{base}_l4o")
                    d.luts.append({
                        "name": f"ccu2_{base}_l4",
                        "init": init,
                        "a": ins["A"], "b": ins["B"], "c": ins["C"], "d": ins["D"],
                        "z": l4o,
                        "z_used": True,
                    })
                    if fci_sum != "1'b0":
                        d.luts.append({
                            "name": f"ccu2_{base}_sum",
                            "init": XOR2_INIT,
                            "a": l4o, "b": fci_sum, "c": None, "d": None,
                            "z": net_of(fkey),
                            "z_used": dsu.find(fkey) in d.used_roots,
                        })

                    fcokey = pins.get("FCO")
                    if fcokey is None:
                        continue
                    # COUT = (~prop & gen) | (prop & CIN), i.e. prop ? CIN : gen
                    # -- the same 2:1 mux, selected by prop (== l4o).
                    #
                    # `gen` is the part worth stating precisely, because the
                    # generic Lattice COMB model in yosys's lattice/common_sim.vh
                    # states it differently and following that gives a carry
                    # chain that is silently always 0.  Lattice's OWN MachXO2
                    # CCU2D model (Diamond ispfpga/verilog/data/machxo2/CCU2D.v)
                    # is the authority here:
                    #     y3  = INIT[12 + {B,A}]        <- the HIGH nibble
                    #     gen = INJECT1 ? 1'b1 : ~y3    <- negated, and 1 (not 0)
                    #                                      when INJECT1 is set
                    # Checked against the real counter: INIT=0x0555 with A=cnt[0]
                    # gives sum=~A and cout=A, which is exactly what +1 needs.
                    gen = "1'b1"
                    if not inject:
                        gen = internal_net(f"{base}_gen")
                        # High nibble, inverted; replicated so the LUT4 ignores
                        # C/D.  The init string is MSB-first, so INIT[15:12] is
                        # its first four characters and the nibble repeats.
                        hi = "".join("1" if ch == "0" else "0" for ch in init[:4])
                        d.luts.append({
                            "name": f"ccu2_{base}_gen",
                            "init": hi * 4,
                            "a": ins["A"], "b": ins["B"], "c": None, "d": None,
                            "z": gen,
                            "z_used": True,
                        })
                    carry_driven.add(dsu.find(fcokey))
                    d.luts.append({
                        "name": f"ccu2_{base}_fco",
                        "init": MUX2_INIT,       # Z = C ? B : A
                        "a": gen, "b": fci, "c": l4o, "d": None,
                        "z": net_of(fcokey),
                        "z_used": True,
                    })

        # ---- flip-flops ----
        for (r, c) in sorted(plc_tiles):
            bels = self.bels_of(r, c)
            for sl in "ABCD":
                senum = pc.slice_enum.get((r, c, sl), {})
                for j in (0, 1):
                    pins = bels.get(f"SLICE{sl}.FF{j}")
                    if not pins:
                        continue
                    qkey = pins.get("Q")
                    if qkey is None or dsu.find(qkey) not in d.used_roots:
                        continue
                    # See ff_d_source() for the REG{j}.SD semantics.  The
                    # DI wire never appears in config arcs (F→DI is an
                    # internal fixed path), so the DI case resolves
                    # straight to the paired LUT's F output key.
                    sd = senum.get(f"REG{j}.SD", "1")
                    d_default = "1'b0"
                    if ff_d_source(senum, j) == "F":
                        dkey = bels.get(f"SLICE{sl}.K{j}", {}).get("F")
                        # A used register whose paired LUT slot carries no INIT
                        # word has had that LUT optimized to a constant and
                        # removed; its DI has no logic source and floats to the
                        # slice VCC, so the register loads a constant 1.  (A
                        # constant-0 register is dropped entirely by the vendor
                        # tool, so a materialized register with a bare paired
                        # slot is always the const-1 case.)  Without this the D
                        # falls through to the 1'b0 default and a registered
                        # constant 1 is silently recovered as 0.
                        #
                        # The absent INIT word is the WHOLE signal.  No INIT
                        # word means no LUT, which means nothing drives F --
                        # whether or not the F wire itself shows up in the DSU,
                        # which it often does because some arc names it.  An
                        # earlier `not connected(dkey)` clause required it to be
                        # absent too, so every one of these registers instead
                        # resolved its D to a real but undriven net and read as
                        # 0.  That is what made lut4_all1 / nand4 / notbit08..15
                        # (all constant-1 once D is tied low) fail LEC (#46).
                        # Memory modes are excluded: there the DPRAM pass
                        # synthesises a driver onto F with no INIT word present.
                        if ((r, c, sl, str(j)) not in pc.lut_init
                                and senum.get("MODE") not in ("DPRAM", "RAMW")):
                            dkey, d_default = None, "1'b1"
                    else:
                        dkey = pins.get("M")

                    # net_or == resolve(): a degenerate-constant D/CLK/CE/LSR
                    # source yields its constant literal (e.g. a const-1 LUT
                    # feeding D gives 1'b1, not the 1'b0 fall-through default).
                    net_or = resolve

                    d.ffs.append({
                        "name": f"ff_r{r}c{c}_{sl}{j}",
                        "q": net_of(qkey),
                        "d": net_or(dkey, d_default),
                        "clk": net_or(pins.get("CLK"), "1'b0"),
                        "ce": net_or(pins.get("CE"), "1'b1"),
                        "lsr": net_or(pins.get("LSR"), "1'b0"),
                        "regset": senum.get(f"REG{j}.REGSET", "RESET"),
                        "sd": sd,
                        "gsr": senum.get("GSR", "DISABLED"),
                    })

        # Force net names for all arc endpoints, including pad nodes that only
        # connect to hard IP (EBR write ports, SPI config port) or drive
        # external pins. Without this, their DSU roots exist but net_name has
        # no entry, so pad_net() returns None even though the arc is present.
        for (r, c, sink, source) in pc.arcs:
            for name in (sink, source):
                k = self.gkey(r, c, name)
                if k is not None and k in dsu.p:
                    net_of(k)

        # ---- distributed RAM (DPRAM read + RAMW write) ----
        # MachXO2 distributed RAM uses three adjacent slices at one tile:
        #   SLICEC (MODE=RAMW): write port — D0/D1 are the two write-data bits
        #   SLICEA (MODE=DPRAM): read port for bit 0 — K0.F/K1.F are async read outputs
        #   SLICEB (MODE=DPRAM): read port for bit 1 — K0.F/K1.F are async read outputs
        #
        # The write→read data flow goes through the LUT SRAM cells and is not captured
        # by any config arc or fixed_conn.  We model each RAMW/DPRAM site as a pair of
        # pseudo-LUT entries (INIT=0xAAAA, single-input pass-through) so that
        # reachability correctly flows from RAMW write data through to the DPRAM read
        # outputs consumed by downstream fabric FFs.
        #
        # RAMW.D0 → SLICEA K0.F and K1.F (bit 0 of the stored value)
        # RAMW.D1 → SLICEB K0.F and K1.F (bit 1 of the stored value)
        #
        # This pass runs AFTER net_of() has assigned all canonical net names so that
        # the net numbering is identical to a run without distributed RAM (stable names).
        for (r, c, sl) in pc.slice_enum:
            if pc.slice_enum[(r, c, sl)].get("MODE") != "RAMW":
                continue
            bels_here = self.bels_of(r, c)
            ramw_pins = bels_here.get("SLICEC.RAMW", {})
            # BEL pin mapping confirmed from routing graph (verified at R4C14
            # against known ADC data nets).  The RAMW is 4-bit wide; each bit
            # maps to a separate DPRAM slice for read:
            #   bit 0: RAMW pin "B1" → SLICEA K0/K1 F outputs
            #   bit 1: RAMW pin "D1" → SLICEB K0/K1 F outputs
            #   bit 2: RAMW pin "C1" → SLICEC K0/K1 F outputs
            #   bit 3: RAMW pin "A1" → SLICED K0/K1 F outputs
            for bit, dpram_sl, ramw_pin in (
                (0, "A", "B1"), (1, "B", "D1"), (2, "C", "C1"), (3, "D", "A1")
            ):
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
                    f_net = net_of(f_key)
                    d.luts.append({
                        "name": f"dpram_r{r}c{c}_d{bit}k{k}",
                        "init": "1010101010101010",  # INIT=0xAAAA: F=A (pass-through)
                        "a": d_net, "b": None, "c": None, "d": None,
                        "z": f_net,
                        "z_used": dsu.find(f_key) in d.used_roots,
                    })

        d.all_nets = sorted(set(net_name.values()), key=lambda s: int(s[1:]))

        # Issue #78: Guard against the specific gkey collision that silently fuses
        # a pad-input net with an FF Q net.  The routing graph has many wires that
        # legitimately share a canonical key (hop-prefix aliases, N/S direction-flip
        # pairs at edges, clock-spine variants) — those are NOT bugs.  The actual
        # bug is when a JQ pad-input wire and an FF Q output wire end up with the
        # same canonical key, causing the DSU to fuse pad-side and fabric-side nets.
        # That is directly detectable post-recovery: the fused net appears in both
        # design.ffs (as a Q net) and as the fabric-side of a JQ arc.
        _JQ_collision_re = re.compile(r'^JQ(\d)$')
        ff_q_nets = {ff["q"] for ff in d.ffs if ff.get("q")}
        pad_q_fusions = []
        for (r, c, sink, src) in pc.arcs:
            m_jq = _JQ_collision_re.match(sink)
            if not m_jq:
                continue
            k_src = self.gkey(r, c, src)
            if k_src is None:
                continue
            root = dsu.find(k_src)
            net = net_name.get(root)
            if net and net in ff_q_nets:
                pio = chr(ord('A') + int(m_jq.group(1)))
                pad_q_fusions.append(
                    f"R{r}C{c}:PIO{pio} pad-input fused with FF Q net {net!r}"
                )
        if pad_q_fusions:
            from db import die
            die(
                "gkey canonicalization collision — pad input fused with FF output "
                "(#78):\n" + "\n".join(f"  {msg}" for msg in pad_q_fusions)
            )

        return d

    # ---- pad connectivity --------------------------------------------------
    def arc_endpoint_sets(self, pc):
        """Nodes appearing as a config-arc source / sink. An endpoint counts if
        IT globalises validly even when the other end is a skipped global-spine
        name, so clock/hard-IP pads are not misreported as dangling."""
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
        """Parse CIB_CFG0/bits.db and return (local_wire, efb_port, direction)
        triples for every EFB fixed connection in that tile, BOTH directions.

        prjtrellis writes these lines sink-first --- `BitDatabase.cpp`:

            out << ".fixed_conn " << es.sink << " " << es.source << endl;

        so the COLUMN the `_EFB` port sits in is what states its direction:

            .fixed_conn E2_JF0       JWBDATO0_EFB   EFB is the source -> "out"
            .fixed_conn JWBDATI0_EFB E2_JA0         EFB is the sink   -> "in"

        This function used to read `parts[1]` as the fabric wire and `parts[2]`
        as the EFB port unconditionally, so it could only ever see the first
        form.  Every input-side line has its columns the other way round, which
        is why the recovered EFB interface came out as 17 ports all marked
        "out" and not one input (issue #100).  The old docstring claimed the
        sink ports were "already captured by routing arcs"; they are not ---
        matching JF_RE against the arc sink in CIB_CFG2 yields zero rows,
        because the input side is not routed as arcs at all.  It is here.

        The direction is therefore read off the file's own sink/source
        convention, never inferred from the port's name.  (The names do agree:
        every source-column port is O-suffixed and every sink-column port is
        I-suffixed, which is corroboration, not the rule being applied.)
        """
        db_root = dbroot or DEF_DBROOT
        bits_path = os.path.join(db_root, "MachXO2", "tiledata",
                                 "CIB_CFG0", "bits.db")
        m = _DEVICE_SIZE_RE.search(self.device or "")
        want_size = m.group(1) if m else None

        def _local(wire):
            """Strip the device-size prefix, or None if it is another device's."""
            pm = _EFB_PREFIXED_WIRE_RE.match(wire)
            if not pm:
                return wire
            return pm.group(2) if pm.group(1) == want_size else None

        conns = []
        try:
            with open(bits_path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line.startswith(".fixed_conn "):
                        continue
                    parts = line.split()
                    if len(parts) != 3:
                        continue
                    sink, source = parts[1], parts[2]
                    if source.endswith("_EFB"):
                        efb_port, fabric_wire, direction = source, sink, "out"
                    elif sink.endswith("_EFB"):
                        efb_port, fabric_wire, direction = sink, source, "in"
                    else:
                        continue            # not an EFB connection at all
                    fabric_wire = _local(fabric_wire)
                    if fabric_wire is None:
                        continue            # belongs to a different device size
                    conns.append((fabric_wire, efb_port[:-4], direction))
        except OSError:
            pass
        return conns

    def apply_efb_fixed_conns(self, dsu, efb_conns, cfg_row=1, cfg_col=4):
        """Union EFB fixed connections into the DSU.

        For each (fabric_wire, efb_port, direction) triple from
        load_efb_fixed_conns:
          1. Resolve fabric_wire to a canonical key via gkey(cfg_row, cfg_col, wire).
          2. Use the string efb_port as a synthetic DSU node (it will never
             collide with a real (int,int,RoutingId) tuple key).
          3. Union them so that any fabric net already connected to fabric_wire
             inherits the EFB port label, and vice versa.

        The union itself is direction-agnostic --- it fuses two names for one
        physical node --- so inputs need no separate mechanism, only to stop
        being discarded at parse time.  The direction is carried through so the
        caller can record it.

        Returns {efb_port: direction} for the ports whose fabric-side wire
        globalised to a valid key.
        """
        resolved = {}
        for fabric_wire, efb_port, direction in efb_conns:
            k = self.gkey(cfg_row, cfg_col, fabric_wire)
            if k is not None:
                dsu.union(k, efb_port)
                resolved[efb_port] = direction
        return resolved

    def load_plc_fixed_conns(self, dbroot=None):
        """Parse PLC/bits.db and return the list of (fabric_wire, slice_out)
        `.fixed_conn` pairs that carry a slice output (F0..F7) onto an adjacent
        tile's fast-connect wire (HF0W/HF1W/HF2W and E1_HF4E..E1_HF7E, etc.).

        These direct connections are ALWAYS present (no config bit) and are how a
        slice LUT/FF output reaches a neighbouring tile without a routed pip.
        The .config never lists them, so a signal that leaves a slice on one of
        these fast wires lands on a fabric net with NO recovered driver (fanin=0)
        — orphaning the whole cone that reads it (e.g. the SPI-readback / miso
        path in the MachXO2 round-trip, issue #65).  Unioning them in
        apply_plc_fixed_conns() gives those nets their real slice-output driver.

        Only slice-output sources (F0..F7) are returned; the fixed_conn's other
        endpoint is the fast-connect fabric wire.
        """
        db_root = dbroot or DEF_DBROOT
        bits_path = os.path.join(db_root, "MachXO2", "tiledata", "PLC", "bits.db")
        _F_RE = re.compile(r"^F[0-7]$")
        conns = []
        try:
            with open(bits_path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line.startswith(".fixed_conn "):
                        continue
                    parts = line.split()
                    if len(parts) != 3:
                        continue
                    fabric_wire, endpoint = parts[1], parts[2]
                    if _F_RE.match(endpoint):
                        conns.append((fabric_wire, endpoint))
        except OSError:
            pass
        return conns

    # The CCU2 carry chain is fixed wiring too, and equally absent from
    # `.config`: FCOA_SLICE -> FCIB_SLICE within a tile, FCO -> HFIE -> FCI
    # between tiles.  Without these unions each slice's carry-in defaults to 0
    # and every multi-slice counter recovers with a broken chain (#46).
    _CARRY_RE = re.compile(r"^(?:[EWNS]\d+_)?(?:FCI|FCO|HFIE)")

    # Wide-mux (PFUMX / L6MUX21) wiring.  A slice's OFX0/OFX1 bel pins are
    # F5x_SLICE / FXx_SLICE, but the switchbox knows them as OFX0..OFX7, and the
    # L6MUX21 data inputs FXA/FXB are hardwired to neighbouring slices' OFX0.
    # None of it appears in `.config`, so without these unions a routed wire
    # taken from "OFX1" never reaches the mux bel that drives it -- the mux
    # looks unused and its output net has no driver.
    _OFX_RE = re.compile(
        r"^(?:[EWNS]\d+_)?"
        r"(?:OFX\d+|F5[A-D]?(?:_SLICE)?|FX[AB]?[A-D](?:_SLICE)?"
        r"|HL7W\d+|HF5E\d+)$")

    def _load_plc_conns(self, pattern, dbroot=None):
        """`.fixed_conn` pairs of PLC/bits.db whose BOTH endpoints match."""
        db_root = dbroot or DEF_DBROOT
        bits_path = os.path.join(db_root, "MachXO2", "tiledata", "PLC", "bits.db")
        conns = []
        try:
            with open(bits_path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line.startswith(".fixed_conn "):
                        continue
                    parts = line.split()
                    if len(parts) != 3:
                        continue
                    sink, source = parts[1], parts[2]
                    if pattern.match(sink) and pattern.match(source):
                        conns.append((sink, source))
        except OSError:
            pass
        return conns

    def load_plc_carry_conns(self, dbroot=None):
        """`.fixed_conn` pairs of PLC/bits.db that form the CCU2 carry chain."""
        return self._load_plc_conns(self._CARRY_RE, dbroot)

    def load_plc_ofx_conns(self, dbroot=None):
        """`.fixed_conn` pairs of PLC/bits.db that wire the wide-mux tree."""
        return self._load_plc_conns(self._OFX_RE, dbroot)

    def apply_plc_fixed_conns(self, dsu, plc_conns, plc_tiles):
        """Union the PLC slice-output fast connections into the DSU.

        For every PLC tile (row, col) and every (fabric_wire, slice_out) pair
        from load_plc_fixed_conns, resolve BOTH endpoints to canonical keys via
        gkey() at that tile and union them.  gkey() globalises the directional
        wire name (e.g. E1_HF6E0001 -> the HF6E0001 node in the east neighbour)
        and the slice-output wire (F6), so the union fuses the neighbour's
        fast-connect net onto the slice output's net.  Both endpoints must
        globalise to a valid location; edge tiles whose neighbour falls off-chip
        simply resolve to None and are skipped.

        Returns the number of unions actually applied.
        """
        applied = 0
        for (r, c) in plc_tiles:
            for fabric_wire, slice_out in plc_conns:
                kw = self.gkey(r, c, fabric_wire)
                kf = self.gkey(r, c, slice_out)
                if kw is not None and kf is not None:
                    dsu.union(kw, kf)
                    applied += 1
        return applied

    def pad_fabric_node(self, row, col, pio, direction):
        """Fabric joint node for a PIO pad: input -> JQ{idx}, output -> JA{idx},
        idx = A:0 B:1 C:2 D:3. `direction` in {'in','out'}.

        Right-edge PIOs (PIC_R0) store JA/JQ in the PIO tile itself.
        Bottom-edge PIOs (PIC_B0) store them in the CIB tile one row above.
        Top-edge PIOs (PIC_T0) store them in the CIB tile one row below.
        We detect the edge by comparing row to the chip boundary and try
        the CIB-adjacent row when the PIO is on the top or bottom edge.
        """
        idx = ord(pio) - ord("A")
        name = f"JQ{idx}" if direction == "in" else f"JA{idx}"
        max_row = self.chip.get_max_row()
        # For bottom-edge PIOs the JA/JQ arc lives in the CIB one row above;
        # for top-edge PIOs it lives one row below.
        if row == max_row:
            probe_row = row - 1
        elif row == 0:
            probe_row = row + 1
        else:
            probe_row = row
        return self.gkey(probe_row, col, name)


# ---- Verilog emission (board-agnostic) -------------------------------------
# Recovered-logic primitive wrappers.  These use NON-colliding names with local
# behavioural definitions so a vendor synthesiser (Diamond LSE) compiles the
# recovered logic instead of shadowing it with a library cell of the same name:
#   * "LUT4" already ships in LSE with a different interface (no INIT) -> collides;
#   * "MACHXO2_FF" is not a real Lattice cell at all -> undefined.
# RLUT4 infers a LUT from its INIT truth table; RFF infers a fabric register.
# The LUT INIT is indexed {D,C,B,A} == A + 2B + 4C + 8D, matching the raw
# `.config` A-LSB word convention (so int(init, 2) is used verbatim, NOT
# reversed).
_RECOVERED_PRIM_LIB = (
    "module RLUT4 #(parameter [15:0] INIT = 16'h0000)\n"
    "             (input A, B, C, D, output Z);\n"
    "  assign Z = INIT[{D, C, B, A}];\n"
    "endmodule\n\n"
    "module RFF #(parameter REGSET = \"RESET\", parameter SD = \"0\",\n"
    "             parameter GSR = \"DISABLED\")\n"
    "            (input CLK, CE, LSR, D, output reg Q);\n"
    "  localparam RINIT = (REGSET == \"SET\") ? 1'b1 : 1'b0;\n"
    "  initial Q = RINIT;\n"
    "  always @(posedge CLK) if (LSR) Q <= RINIT; else if (CE) Q <= D;\n"
    "endmodule\n\n"
)


def write_netlist_verilog(design, out_path, target, source,
                          module_name="recovered_netlist", ports=None):
    """Emit the recovered netlist as synthesisable Verilog.

    `ports`: optional list of {name, direction in {input,output,inout}, net}
    promoting used pads to top-level module ports wired to their fabric net.
    Without ports every net is internal, giving the design no I/O boundary --
    the vendor tool then prunes the whole thing.  Pass the used-pad ports (see
    used_pad_ports()) so pads are observable and the design survives synthesis.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    n_lut, n_ff = len(design.luts), len(design.ffs)
    ports = [p for p in (ports or []) if p.get("net")]
    net_set = set(design.all_nets)
    with open(out_path, "w") as fh:
        fh.write("// Recovered STRUCTURAL netlist (pass 2: LUT4 + FF) for the\n")
        fh.write(f"// {target}.\n")
        fh.write(f"// Source: {source}\n")
        fh.write("// Nets recovered by union-find over %d routing arcs;\n"
                 % design.n_arcs)
        fh.write("// slice bel pins remapped across fixed '_SLICE' pips.\n")
        fh.write("// NOTE: functionally-equivalent primitives, not vendor "
                 "RTL.\n\n")

        fh.write(_RECOVERED_PRIM_LIB)

        if ports:
            fh.write("module %s(\n" % module_name)
            fh.write(",\n".join("  %s %s" % (p.get("direction", "input"),
                                             p["name"]) for p in ports))
            fh.write("\n);\n\n")
        else:
            fh.write("module %s;\n\n" % module_name)

        fh.write("  // %d recovered nets\n" % len(design.all_nets))
        for n in design.all_nets:
            fh.write("  wire %s;\n" % n)

        if ports:
            fh.write("\n  // top-level pad ports wired to recovered fabric nets\n")
            for p in ports:
                net = p["net"]
                if net not in net_set:
                    fh.write("  wire %s;\n" % net)
                    net_set.add(net)
                if p.get("direction") == "output":
                    fh.write("  assign %s = %s;\n" % (p["name"], net))
                else:                       # input / inout drive the fabric net
                    fh.write("  assign %s = %s;\n" % (net, p["name"]))

        fh.write("\n  // %d used LUT4s\n" % n_lut)
        for lt in design.luts:
            a = lt["a"] or "1'b0"
            b = lt["b"] or "1'b0"
            cc = lt["c"] or "1'b0"
            dd = lt["d"] or "1'b0"
            z = lt["z"] or ("%s_z" % lt["name"])
            if not lt["z"]:
                fh.write("  wire %s;\n" % z)
            # A-LSB truth-table order (matches the raw .config INIT word).
            init_hex = format(int(lt["init"], 2), "04x")
            fh.write(
                "  RLUT4 #(.INIT(16'h%s)) %s (.A(%s), .B(%s), .C(%s), "
                ".D(%s), .Z(%s));\n" % (init_hex, lt["name"], a, b, cc, dd, z))

        fh.write("\n  // %d flip-flops\n" % n_ff)
        for ff in design.ffs:
            fh.write(
                "  RFF #(.REGSET(\"%s\"), .SD(\"%s\"), .GSR(\"%s\")) %s "
                "(.CLK(%s), .CE(%s), .LSR(%s), .D(%s), .Q(%s));\n"
                % (ff["regset"], ff["sd"], ff["gsr"], ff["name"],
                   ff["clk"], ff["ce"], ff["lsr"], ff["d"], ff["q"]))

        fh.write("\nendmodule\n")


def write_netlist_json(design, out_path, module_name="recovered_netlist",
                       creator="machxo2_lift", ports=None):
    """Emit the recovered design as a Yosys JSON netlist (RTLIL schema) -- the
    de-facto standard, queryable, round-trippable form. Load it back with
    `yosys -p 'read_json ...; stat'` to treat the recovery as a first-class
    design (formal equivalence, hierarchy, re-synthesis). Net ids are integers
    >=2; "0"/"1" are constant bits; unconnected LUT inputs are tied to 0 to
    match the Verilog emitter, and a LUT with no fabric output gets a private
    net so the cell is never dropped.

    `ports`: optional list of {name, direction in {input,output,inout}, net,
    attributes} promoting used pads to top-level module ports, wired to their
    fabric net. This keeps the file valid Yosys JSON while making it a complete
    boundary design."""
    netid = {}
    nxt = [2]

    def new_id():
        i = nxt[0]
        nxt[0] += 1
        return i

    for n in design.all_nets:
        netid[n] = new_id()

    def bit(sig, unconnected="x"):
        if sig is None:
            return unconnected
        if sig == "1'b0":
            return "0"
        if sig == "1'b1":
            return "1"
        if sig not in netid:               # private/implicit net
            netid[sig] = new_id()
        return netid[sig]

    cells = {}
    for lt in design.luts:
        z = lt["z"] if lt["z"] is not None else f"{lt['name']}_z"
        # A-LSB truth-table order (matches the raw .config INIT word); MSB-first
        # bit string as Yosys expects.  NOT reversed -- reversing inverts the
        # truth table vs the {D,C,B,A}-indexed convention.
        init = format(int(lt["init"], 2), "016b")
        cells[lt["name"]] = {
            "hide_name": 0,
            "type": "LUT4",
            "parameters": {"INIT": init},
            "port_directions": {"A": "input", "B": "input", "C": "input",
                                "D": "input", "Z": "output"},
            "connections": {
                "A": [bit(lt["a"], "0")], "B": [bit(lt["b"], "0")],
                "C": [bit(lt["c"], "0")], "D": [bit(lt["d"], "0")],
                "Z": [bit(z)],
            },
        }
    for ff in design.ffs:
        cells[ff["name"]] = {
            "hide_name": 0,
            "type": "MACHXO2_FF",
            "parameters": {"REGSET": ff["regset"], "SD": ff["sd"],
                           "GSR": ff["gsr"]},
            "port_directions": {"CLK": "input", "CE": "input", "LSR": "input",
                                "D": "input", "Q": "output"},
            "connections": {
                "CLK": [bit(ff["clk"])], "CE": [bit(ff["ce"])],
                "LSR": [bit(ff["lsr"])], "D": [bit(ff["d"])],
                "Q": [bit(ff["q"])],
            },
        }

    netnames = {}
    for n in design.all_nets:
        netnames[n] = {"hide_name": 0, "bits": [netid[n]], "attributes": {}}

    mod_ports = {}
    for p in (ports or []):
        b = bit(p.get("net"))
        mod_ports[p["name"]] = {
            "direction": p.get("direction", "input"),
            "bits": [b],
        }
        # also surface the port as a named net so queries can see it
        nm = p["name"]
        if nm not in netnames:
            netnames[nm] = {"hide_name": 0, "bits": [b],
                            "attributes": p.get("attributes", {})}

    doc = {
        "creator": creator,
        "modules": {
            module_name: {
                "attributes": {"top": "00000000000000000000000000000001"},
                "ports": mod_ports,
                "cells": cells,
                "netnames": netnames,
            }
        },
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    return doc


def pad_net(design, lift, row, col, pio, direction):
    """Net name carrying a pad's fabric signal, or None if the pad node was not
    unioned into a named net (e.g. it only routes to unmodelled hard IP)."""
    key = lift.pad_fabric_node(row, col, pio, direction)
    if key is None or key not in design.dsu.p:
        return None
    return design.net_name.get(design.dsu.find(key))


def used_pad_ports(design, lift, device, dbroot=DEF_DBROOT):
    """Top-level module ports for every PIO pad that carries a named fabric net.

    Returns a list of {name, direction, net} suitable for write_netlist_verilog
    / write_netlist_json.  Package-independent: enumerates PIO sites from the
    device iodb and keeps those whose input (JQ) or output (JA) joint node
    unioned into a named net.  A pad is emitted as an output when its net is
    driven inside the fabric (a LUT Z or FF Q) and as an input otherwise, so an
    input port never fights an internal driver.  Nets are de-duplicated so a net
    surfacing at several sites yields one port."""
    try:
        iodb = load_iodb(device, dbroot=dbroot)
    except Exception:
        return []
    driven = {lt["z"] for lt in design.luts if lt["z"]}
    driven |= {ff["q"] for ff in design.ffs if ff["q"]}
    ports, seen = [], set()
    for m in iodb.get("pio_metadata", []):
        r, c, pio = m.get("row"), m.get("col"), m.get("pio")
        if r is None or c is None or pio is None:
            continue
        onet = pad_net(design, lift, r, c, pio, "out")
        inet = pad_net(design, lift, r, c, pio, "in")
        base = f"pad_r{r}c{c}{pio}"
        if onet and onet in driven and onet not in seen:
            seen.add(onet)
            ports.append({"name": base + "_o", "direction": "output",
                          "net": onet})
        elif inet and inet not in driven and inet not in seen:
            seen.add(inet)
            ports.append({"name": base + "_i", "direction": "input",
                          "net": inet})
    return ports


def scan_unknown_bits(config_path, tile_rc=None):
    """Tally `unknown:` lines per tile type straight from a .config. Returns
    {"total": N, "by_tiletype": {type: count}, "lines": [...] }. These are bits
    set in the bitstream that Trellis cannot name -- the explicit edges of what
    the recovery actually knows."""
    by_type = defaultdict(int)
    total = 0
    samples = []
    cur_type = None
    with open(config_path) as fh:
        for line in fh:
            m = TILE_RE.match(line.strip())
            if m:
                cur_type = m.group(2)
                continue
            if line.startswith("unknown:"):
                total += 1
                by_type[cur_type or "?"] += 1
                if len(samples) < 40:
                    samples.append({"tile_type": cur_type,
                                    "line": line.strip()})
    return {"total": total, "by_tiletype": dict(by_type), "lines": samples}


def write_facts_json(out_path, provenance, resources, hardip, pads, unknowns):
    """Sidecar 'known facts' file for everything that is NOT a netlist object:
    provenance, resource totals, hard IP (PLL ratios / EBR / sysCONFIG), the
    full pad table, and the unknown-bit accounting that marks where the recovery
    is still guessing. JSON so it stays diffable and queryable."""
    doc = {
        "provenance": provenance,
        "resources": resources,
        "hard_ip": hardip,
        "pads": pads,
        "unknown_bits": unknowns,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    return doc


def lift_netlist(config_path, out_path, device, target, source,
                 module_name="recovered_netlist", build_dir=DEF_BUILD_DIR,
                 dbroot=DEF_DBROOT):
    """Convenience: parse a config and write the structural netlist Verilog.
    Returns (lift, parsed_config, design) for further analysis."""
    lift = MachXO2Lift(device, build_dir, dbroot)
    pc = lift.parse_config(config_path)
    design = lift.recover_netlist(pc)
    # Promote used pads to top-level ports so the emitted module has an I/O
    # boundary (a port-less module gets pruned by the vendor tool).
    ports = used_pad_ports(design, lift, device, dbroot=dbroot)
    write_netlist_verilog(design, out_path, target, source, module_name,
                          ports=ports)
    return lift, pc, design


# ---- package pinout (device/package-generic, from Trellis iodb.json) --------
def load_iodb(device, family="MachXO2", dbroot=DEF_DBROOT):
    """Load the Trellis IO database for a device. `packages` maps physical
    pin/ball -> site {row,col,pio}; `pio_metadata` maps a site -> {bank,
    function, ...}. Nothing board-specific lives here."""
    with open(os.path.join(dbroot, family, device, "iodb.json")) as fh:
        return json.load(fh)


def pinout(iodb, package):
    """Full physical pinout for one package: list of dicts
    {pin, row, col, pio, bank, function} for every mapped pad."""
    meta_by_site = {(m["row"], m["col"], m["pio"]): m
                    for m in iodb.get("pio_metadata", [])}
    rows = []
    for pin, site in iodb["packages"][package].items():
        r, c, pio = site["row"], site["col"], site["pio"]
        meta = meta_by_site.get((r, c, pio), {})
        rows.append({
            "pin": pin, "row": r, "col": c, "pio": pio,
            "bank": meta.get("bank"),
            "function": meta.get("function", ""),
        })
    return rows


def classify_pin(function, in_conn, out_conn):
    """Bucket a pad by what it is ACTUALLY connected to. fabric = wired to a
    config arc (hard fact); the rest are inferred from the dedicated function
    name (the hard-IP target the pad routes to via a dedicated path)."""
    if in_conn or out_conn:
        return "fabric"
    f = (function or "").upper()
    if "GPLL" in f:
        return "pll"            # PLL reference / feedback
    if f in ("CSSPIN", "SN"):
        return "spi_cfg"        # sysCONFIG slave-SPI
    if "PCLK" in f or "SDA" in f or "SCL" in f:
        return "clock"          # primary-clock pad / I2C, dedicated route
    return "unused"             # no fabric arc, no dedicated function


# ---- basic resource usage (device-generic) ---------------------------------
# Fabric capacity per device (LUT4s and registers). Each MachXO2 PFU slice
# carries 2 LUT4 + 2 registers, so #LUT4 == #registers for the array. `ebr` is
# the number of 9-kbit EBR blocks, `pll` the number of sysCLOCK PLLs.
DEVICE_CAPACITY = {
    "LCMXO2-256":  {"lut4": 256,  "ff": 256,  "ebr": 0,  "pll": 0},
    "LCMXO2-640":  {"lut4": 640,  "ff": 640,  "ebr": 2,  "pll": 1},
    "LCMXO2-1200": {"lut4": 1280, "ff": 1280, "ebr": 7,  "pll": 1},
    "LCMXO2-2000": {"lut4": 2112, "ff": 2112, "ebr": 8,  "pll": 1},
    "LCMXO2-4000": {"lut4": 4320, "ff": 4320, "ebr": 10, "pll": 2},
    "LCMXO2-7000": {"lut4": 6864, "ff": 6864, "ebr": 26, "pll": 2},
}


def resource_summary(design, device=None):
    """Basic 'what is used' counts from a recovered Design. Liveness/cone
    pruning is a separate, later pass -- these are raw used-resource totals."""
    luts, ffs = design.luts, design.ffs
    cap = DEVICE_CAPACITY.get(device) if device else None
    return {
        "device": device,
        "lut4_used": len(luts),
        "lut4_driving_fabric": sum(1 for lt in luts if lt["z_used"]),
        "ff_used": len(ffs),
        "nets": len(design.all_nets),
        "lut4_capacity": cap["lut4"] if cap else None,
        "ff_capacity": cap["ff"] if cap else None,
        "ebr_capacity": cap["ebr"] if cap else None,
        "pll_capacity": cap["pll"] if cap else None,
    }


# ---- liveness / cone-of-influence (device-generic) -------------------------
_LUT_WEIGHTS = {"a": 1, "b": 2, "c": 4, "d": 8}


def lut_dependence(init_str):
    """Which of A,B,C,D a LUT4 truth table FUNCTIONALLY depends on. A routed
    input the INIT ignores is vacuous (the cell would compute the same logic
    without it). init bits are MSB-first; value bit p = f(p), p = A+2B+4C+8D."""
    v = int(init_str, 2)   # MSB-first string -> bit p = f(p); no reversal (#63)
    dep = set()
    for name, w in _LUT_WEIGHTS.items():
        for p in range(16):
            if (p & w) == 0 and ((v >> p) & 1) != ((v >> (p ^ w)) & 1):
                dep.add(name)
                break
    return dep


def _is_const(net):
    return isinstance(net, str) and net.startswith("1'b")


def analyze_liveness(design, primary_in=None, primary_out=None):
    """Forward controllability + backward observability over the LUT/FF graph,
    cutting at registers. Answers 'does this logic actually do something'
    rather than merely 'is it routed'. primary_in/out are net-name sets for the
    package boundary (pad nets). Caveat: nets that only feed UNMODELLED hard IP
    (EBR/PLL) have no observability sink here, so logic feeding them alone may
    read as unobservable -- flagged, not asserted."""
    primary_in = set(primary_in or [])
    primary_out = set(primary_out or [])
    luts, ffs = design.luts, design.ffs

    dep = {}
    vacuous = 0
    net_fanout = defaultdict(int)
    for lt in luts:
        d = lut_dependence(lt["init"])
        dep[lt["name"]] = d
        for k in ("a", "b", "c", "d"):
            net = lt[k]
            if net is None:
                continue
            if k in d:
                net_fanout[net] += 1
            else:
                vacuous += 1
    for ff in ffs:
        if not _is_const(ff["d"]):
            net_fanout[ff["d"]] += 1

    # observability: backward from primary outputs AND every register input
    # (cutting at FFs makes each FF input a genuine observation endpoint -- a
    # value that gets stored is observed, even if its Q is later unused).
    observable = set(primary_out)
    for ff in ffs:
        for key in ("d", "clk", "ce", "lsr"):
            net = ff[key]
            if net and not _is_const(net):
                observable.add(net)
    changed = True
    while changed:
        changed = False
        for lt in luts:
            if lt["z"] in observable:
                for k in dep[lt["name"]]:
                    net = lt[k]
                    if net and net not in observable:
                        observable.add(net)
                        changed = True
        for ff in ffs:
            if ff["q"] in observable:
                for key in ("d", "clk", "ce", "lsr"):
                    net = ff[key]
                    if net and not _is_const(net) and net not in observable:
                        observable.add(net)
                        changed = True

    # controllability: forward from primary inputs + FF outputs (+ constants).
    controllable = set(primary_in)
    controllable.update(ff["q"] for ff in ffs)
    changed = True
    while changed:
        changed = False
        for lt in luts:
            z = lt["z"]
            if not z or z in controllable:
                continue
            ok = True
            for k in dep[lt["name"]]:
                net = lt[k]
                if net is None or _is_const(net):
                    continue
                if net not in controllable:
                    ok = False
                    break
            if ok:
                controllable.add(z)
                changed = True

    live_lut = sum(1 for lt in luts if lt["z"] in observable)
    live_ff = sum(1 for ff in ffs if ff["q"] in observable)
    return {
        "dependence": dep,
        "vacuous_lut_inputs": vacuous,
        "observable": observable,
        "controllable": controllable,
        "net_fanout": dict(net_fanout),
        "lut_live": live_lut,
        "lut_dead": len(luts) - live_lut,
        "ff_live": live_ff,
        "ff_dead": len(ffs) - live_ff,
    }


def net_liveness(live, net):
    """Per-net verdict from an analyze_liveness result: (fanout, is_live).
    is_live = reachable from a primary input AND observable at a primary
    output (i.e. on a real input->output path through functional logic)."""
    if net is None:
        return 0, False
    fan = live["net_fanout"].get(net, 0)
    is_live = net in live["observable"] and net in live["controllable"]
    return fan, is_live


# ---- internal hard-IP usage (device-generic) -------------------------------
_PLL_OUTPUTS = ("CLKOP", "CLKOS", "CLKOS2", "CLKOS3")


def hardip_summary(pc):
    """Enumerate configured internal hard IP from a ParsedConfig: sysCLOCK
    PLLs, sysCONFIG (slave-SPI / GSR), and EBR9K block-RAM instances. These
    have no fabric pad of their own; they are read straight from the tile
    enum/word config. MachXO2-generic (keys off tile-type names)."""
    plls, ebr, sysconfig = [], [], {}
    for (r, c), ttype in sorted(pc.tile_type.items()):
        en = pc.enums.get((r, c), {})
        if "GPLL" in ttype:
            wd = pc.words.get((r, c), {})
            plls.append({
                "loc": f"R{r}C{c}", "tile": ttype,
                "mode": en.get("MODE", "?"),
                "wishbone": en.get("PLL_USE_WB", "DISABLED") == "ENABLED",
                "outputs": [o for o in _PLL_OUTPUTS
                            if en.get(f"{o}_ENABLE") == "ENABLED"],
                # divider/phase words: output:input frequency RATIOS are known;
                # absolute Hz is NOT (the input crystal is off-chip, not in the
                # bitstream). Bits are MSB-first; value = int(bits, 2).
                "dividers": {k: int(v, 2) for k, v in wd.items()
                             if "DIV" in k or "CPHASE" in k},
            })
        elif ttype.startswith("CFG"):
            for k, v in en.items():
                if "SLAVE_SPI_PORT" in k:
                    sysconfig["slave_spi"] = v
                elif "GSR" in k:
                    sysconfig["gsr"] = v
        elif ttype == "EBR1" and any(k.startswith("EBR") for k in en):
            widths = [int(v) for k, v in en.items()
                      if "DATA_WIDTH" in k and v.isdigit()]
            mode = en.get("EBR.MODE")
            if not mode:                      # tool omits MODE at its default
                mode = "DP8KC?"
            ebr.append({
                "loc": f"R{r}C{c}", "mode": mode,
                "width": max(widths) if widths else None,
                "regmode": en.get("EBR.REGMODE_A", "NOREG"),
            })
    return {"plls": plls, "sysconfig": sysconfig, "ebr": ebr}
