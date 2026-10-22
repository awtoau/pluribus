#!/usr/bin/env python3
"""Altera/Intel Cyclone V lifter — first slice, e50f die only (issue: Cyclone V
support for the DJI Lightbridge module-2001 investigation).

Completely different vendor/architecture from every other pluribus lifter:
ALM-based LAB fabric (not Lattice PFU/slice), M10K block RAM (not EBR), DSP
blocks, no EFB.  Project Mistral (Ravenslofty/mistral, C++,
https://github.com/Ravenslofty/mistral) is the reference decoder — there is
no Lattice-style prjtrellis equivalent for this vendor.

INPUT FORMAT — DECISION, NOT A PERMANENT DEPENDENCY
----------------------------------------------------
parse_config() reads Mistral's `.bt` text decompile format (mistral-cv's
`decomp` command) for now. A separate concurrent effort is building a native
Rust decoder + device-db-style schema table for Cyclone V; at the time this
was written neither had landed (checked: no rust/ or Cargo.toml in this repo,
no device_fingerprints-style CycloneV table in schema.py, no
cyclonev_db_import.py in scripts/). Swap the source once that lands — same
parse_config() contract, same Design output. Keeping the .bt grammar isolated
in parse_config() (this is the only place that reads the file) makes that
swap a localised change.

.bt grammar (from mistral-cv/main.cc:decompile, read directly rather than
guessed):
  m <model>                        device/model name
  o <MUX_NAME> <value>             global option (chip-wide mux/bool/num/ram)
  r <src> <dst> [; pad [pad]]      one resolved routing arc, src drives dst
  s <node> <value> [; pad]         one non-default cell config setting
  i <node> <value> [; pad [; alt]] one inverter/polarity bit on a routing node

A "node" (Mistral's pnode, when the fuzzer could resolve one, else its raw
rnode) is BLOCK.x.y[.bi][:PORT[.pi]] — bi is a block-local sub-index (e.g. the
ALM number inside a LAB), pi is a port sub-index (e.g. LUT_MASK.3's "3", or
DATAIN.1's "1"). See cv-rmux.cc pnode_coords::to_string / rnode_coords::to_string
for the authoritative grammar; _NODE_RE below encodes exactly that.

FABRIC SCOPE — LUT/FF/ROUTING ONLY, e50f (5CEBA4U19C8)
-------------------------------------------------------
Mirrors the ECP5 lifter's original slice ("LUT4/FF/routing/pad recovery").
Cyclone V's ALM is structurally a LUT6 that fractures into two outputs
(F0/F1) sharing some inputs — Mistral stores this as one 64-bit LUT_MASK per
ALM (`s LAB.x.y:LUT_MASK.<alm> <hi32>.<lo32>`), 10 ALMs/LAB on e50f. This
recovers as a genuine LUT5 pair (5 inputs: A,B,C,D + one of E0/E1 depending on
which half), NOT a LUT4 — see SCHEMA FIT below.

Each ALM also has up to 4 registers (FFT0/FFT1/FFT1L top-half,
FFB0/FFB1/FFB1L bottom-half — the "L" variants are the second register in a
packed pair). Those recover into the existing generic `ffs` table unchanged;
nothing about a flip-flop's d/q/clk/ce/lsr shape is LUT-width-dependent.

OUT OF SCOPE (explicitly, not a gap to silently fill):
  * M10K block-RAM contents and DSP block config — upstream-Mistral unknown,
    confirmed this session; not a pluribus modelling gap.
  * HPS (hard processor system), PLLs/FPLL, HMC/DQS16 (hard memory
    controller/IO), CMUX* clock muxes, serial/deserial (SERPAR) — all
    hard-IP blocks with their own `s`-line settings in the .bt but no
    cells/nets semantics attempted here.
  * Carry chains / ALM arithmetic mode (ARITH_SEL=ADDER etc) — recorded in
    the .bt (`s LAB.x.y:ARITH_SEL.<alm>`) but not modelled; an ALM in ADDER
    mode will currently just recover its LUT_MASK literally, same as any
    other ALM. No adder/carry netlist is synthesised (c.f. MachXO2's CCU2
    pass, which this lifter does not have an equivalent of yet).
  * Pads: GPIO DATAIN/DATAOUT nodes are visible in the .bt and
    pad_fabric_node() resolves them, but there is no board.toml / pinout
    table for any real Cyclone V board in this repo (CLAUDE.md: pluribus
    stores no board data) — this is engine-only.

SCHEMA FIT — LUT5, UNIFIED INTO `luts`
---------------------------------------
schema.py's `luts` table is now width-generic: `init` is `String(32)` and a
5th input column `e` (NULL for every 4-input family) carries a Cyclone V ALM
half's E0/E1 pin. `recover_netlist()` appends ALM-half LUT5 cells directly to
`Design.luts` (same row shape every other family uses: name/init/a/b/c/d/e/z),
with `init` as the 32-char MSB-first binary string `load.py`'s classify_lut()
expects (converted from the raw `init32` hex here, once, in the lifter — the
fn classification itself stays in load.py, not duplicated). There is no more
separate `Design.alm_luts` list.
"""

import re
from collections import defaultdict

# One regex for every node form main.cc's pnode_coords/rnode_coords::to_string
# can emit: BLOCK.x.y[.bi][:PORT[.pi]], or the 4-field rnode fallback
# TYPE.xxx.yyy.zzzz when no pnode exists for that routing node.
_NODE_RE = re.compile(
    r"^(?P<block>[A-Z0-9_]+)\.(?P<x>\d+)\.(?P<y>\d+)"
    r"(?:\.(?P<bi>\d+))?"
    r"(?::(?P<port>[A-Za-z0-9_]+)(?:\.(?P<pi>\d+))?)?$"
)

_R_LINE_RE = re.compile(r"^r\s+(\S+)\s+(\S+)")
_S_LINE_RE = re.compile(r"^s\s+(\S+)\s+(\S+)")
_I_LINE_RE = re.compile(r"^i\s+(\S+)\s+(\S+)")
_O_LINE_RE = re.compile(r"^o\s+(\S+)\s+(\S+)")
_M_LINE_RE = re.compile(r"^m\s+(\S+)")


class CVNode:
    """Parsed Mistral node: BLOCK.x.y[.bi][:PORT[.pi]].

    Immutable, hashable, used directly as a DSU key and as a dict key — no
    string reformatting needed, __str__ round-trips to the original text
    (modulo zero-padding, which to_string() always emits anyway).
    """

    __slots__ = ("block", "x", "y", "bi", "port", "pi")

    def __init__(self, block, x, y, bi, port, pi):
        self.block = block
        self.x = x
        self.y = y
        self.bi = bi          # block-instance index (e.g. ALM #), or None
        self.port = port      # port name, or None for a bare block/rnode ref
        self.pi = pi          # port-instance index, or None

    def __repr__(self):
        return self.to_string()

    def to_string(self):
        b = f"{self.block}.{self.x:03d}.{self.y:03d}"
        if self.bi is not None:
            b += f".{self.bi}"
        if self.port is not None:
            b += f":{self.port}"
            if self.pi is not None:
                b += f".{self.pi}"
        return b

    def __eq__(self, other):
        return isinstance(other, CVNode) and (
            self.block, self.x, self.y, self.bi, self.port, self.pi
        ) == (other.block, other.x, other.y, other.bi, other.port, other.pi)

    def __hash__(self):
        return hash((self.block, self.x, self.y, self.bi, self.port, self.pi))

    def tile_key(self):
        """(block, x, y) — groups nodes by physical tile, ignoring bi/port."""
        return (self.block, self.x, self.y)


def parse_node(text):
    """Parse one Mistral node string into a CVNode, or raise ValueError."""
    m = _NODE_RE.match(text)
    if not m:
        raise ValueError(f"unparseable Cyclone V node: {text!r}")
    return CVNode(
        m["block"], int(m["x"]), int(m["y"]),
        int(m["bi"]) if m["bi"] is not None else None,
        m["port"],
        int(m["pi"]) if m["pi"] is not None else None,
    )


def _strip_comment(rest):
    """Split 'value ; pad1 [; pad2]' trailer on the first ' ; '."""
    if " ; " in rest:
        return rest.split(" ; ", 1)[0].rstrip()
    return rest.rstrip()


class ParsedConfig:
    """Raw contents of a Mistral `.bt` decompile, before netlist recovery."""

    def __init__(self):
        self.device = None                 # the die/model from the "m" line
        self.options = {}                  # global mux name -> raw value string
        self.arcs = []                      # list of (CVNode src, CVNode dst)
        self.settings = defaultdict(dict)   # tile_key -> {(mux,idx): value}
        self.inverters = {}                 # CVNode -> int (0/1)
        self.n_arc_lines = 0
        self.n_setting_lines = 0
        self.n_inverter_lines = 0
        self.n_unparsed_lines = 0


class Design:
    """Recovered structural netlist.

    `luts`/`ffs`/`nets`/`net_fanout` match every other lifter's shape exactly.
    `luts` entries carry a 5th input `e` (ALM-half E0/E1) and a 32-char init
    string — the row shape schema.py's widened `luts` table now accepts
    directly; see the module docstring's SCHEMA FIT section.
    """

    def __init__(self):
        self.luts = []          # [{name, init, a,b,c,d,e, z, z_used}]
        self.ffs = []
        self.net_name = {}
        self.all_nets = []
        self.dsu = None
        self.used_roots = set()
        self.n_arcs = 0
        self.skipped_arcs = 0
        self.tile_counts = {}        # block type -> tile count seen in .bt
        self.n_alms_configured = 0   # LABs/MLABs with >=1 non-default LUT_MASK


class DSU:
    """Union-find over CVNode keys (same shape as every other lifter's DSU)."""

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


# ALM-half input pin names, by half.  Each ALM half is a 5-LUT: the four
# shared inputs A/B/C/D plus E0 (bottom half) or E1 (top half) — confirmed
# against the .bt: BMODE.<alm>/TMODE.<alm> name E_1/F_1 feedback sources per
# half, and LUT_MASK.<alm> is 64 bits (hi32.lo32), i.e. two 32-bit (5-input)
# truth tables packed together, low half first.
_ALM_HALF_INPUTS = {
    "bottom": ("A", "B", "C", "D", "E0"),
    "top":    ("A", "B", "C", "D", "E1"),
}
# ALM output/register port names per half (from the .bt port_type_names seen
# on LAB/MLAB nodes: F0/F1 combinational, FFB0/FFB1/FFB1L/FFT0/FFT1/FFT1L
# registered).
_ALM_HALF_COMB_OUT = {"bottom": "F0", "top": "F1"}
_ALM_HALF_FF_OUT = {
    "bottom": ("FFB0", "FFB1", "FFB1L"),
    "top":    ("FFT0", "FFT1", "FFT1L"),
}

_LAB_LIKE_BLOCKS = ("LAB", "MLAB")


class CycloneVLift:
    """Mistral-`.bt`-backed lifter for one Cyclone V die: e50f (5CEBA4U19C8).

    Scope: LUT/FF/routing recovery only.  See module docstring for the full
    in/out-of-scope breakdown and the schema-fit note on LUT5 vs LUT4.
    """

    has_efb = False       # Cyclone V has no EFB (Lattice-specific hard block)
    has_ebr = False       # M10K content decode is out of scope here (upstream unknown)
    has_iologic = False   # GPIO IOLOGIC config (DDIO etc) not modelled

    _SUPPORTED_DEVICES = {"5CEBA4U19C8"}
    _DIE = "e50f"

    def __init__(self, device, **_kwargs):
        if device not in self._SUPPORTED_DEVICES:
            raise ValueError(
                f"CycloneVLift: device {device!r} not supported. "
                f"This first slice covers only {sorted(self._SUPPORTED_DEVICES)} "
                f"(die {self._DIE}) — the die with confirmed working Mistral "
                f"decode data. Extending to other Cyclone V dies needs their "
                f"own ALM/LAB geometry check against Mistral, not assumed."
            )
        self.device = device
        self.family = "cyclonev"

    # ---- parsing ------------------------------------------------------------
    def parse_config(self, path):
        """Parse a Mistral `.bt` decompile file into a ParsedConfig.

        Lenient by design on routing (`r`) lines the way every other lifter's
        arc list is: a .bt is already a resolved/filtered dump (mistral-cv
        drops unresolved routes to stderr as "Source unknown on rnode ..."
        rather than writing them), so no retry/recovery logic is needed here,
        only straight parsing. A line we cannot parse is tallied and skipped
        rather than aborting the whole file, so one bad line in a 360K-line
        dump does not lose the rest of the design — but a HIGH count signals
        the grammar assumption is wrong and should fail loud at the caller.
        """
        pc = ParsedConfig()
        with open(path) as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if not line:
                    continue
                tag = line[0]
                try:
                    if tag == "m":
                        m = _M_LINE_RE.match(line)
                        if m:
                            pc.device = m.group(1)
                        continue
                    if tag == "o":
                        m = _O_LINE_RE.match(line)
                        if m:
                            pc.options[m.group(1)] = _strip_comment(m.group(2))
                        continue
                    if tag == "r":
                        m = _R_LINE_RE.match(line)
                        if not m:
                            pc.n_unparsed_lines += 1
                            continue
                        src = parse_node(_strip_comment(m.group(1)))
                        dst = parse_node(_strip_comment(m.group(2)))
                        pc.arcs.append((src, dst))
                        pc.n_arc_lines += 1
                        continue
                    if tag == "s":
                        m = _S_LINE_RE.match(line)
                        if not m:
                            pc.n_unparsed_lines += 1
                            continue
                        node = parse_node(m.group(1))
                        value = _strip_comment(m.group(2))
                        pc.settings[node.tile_key()][(node.port, node.pi)] = value
                        pc.n_setting_lines += 1
                        continue
                    if tag == "i":
                        m = _I_LINE_RE.match(line)
                        if not m:
                            pc.n_unparsed_lines += 1
                            continue
                        node = parse_node(_strip_comment(m.group(1)))
                        pc.inverters[node] = int(_strip_comment(m.group(2)))
                        pc.n_inverter_lines += 1
                        continue
                    # unknown tag (e.g. a future mistral-cv addition) — skip,
                    # do not die: this file format is explicitly provisional
                    # (see module docstring) and a new line kind upstream is
                    # not this lifter's problem to reject.
                    pc.n_unparsed_lines += 1
                except ValueError:
                    pc.n_unparsed_lines += 1
        return pc

    # ---- routing-arc endpoint sets (for pad-connectivity probing) ---------
    def arc_endpoint_sets(self, pc):
        """Return (sources, sinks): the set of CVNode keys that appear as an
        arc source / sink anywhere in the design. Mirrors every other
        lifter's arc_endpoint_sets() — used by callers (e.g. load.py's pad
        probe) to test "is this bel pin actually connected".
        """
        sources = {src for (src, _dst) in pc.arcs}
        sinks = {dst for (_src, dst) in pc.arcs}
        return sources, sinks

    # ---- recovery ------------------------------------------------------------
    def recover_netlist(self, pc):
        d = Design()
        d.dsu = dsu = DSU()

        for (src, dst) in pc.arcs:
            dsu.union(src, dst)

        tile_counts = defaultdict(int)
        for tile_key in pc.settings:
            tile_counts[tile_key[0]] += 1
        d.tile_counts = dict(tile_counts)

        net_name = d.net_name
        counter = [0]

        # Precomputed once: a LAB has 10 ALMs and this set is consulted twice
        # per ALM-half plus once per register port below. Recomputing
        # {dsu.find(s) for s in arcs} inside that loop would be O(arcs x alms)
        # — with ~70k arcs and thousands of ALMs on e50f that is minutes, not
        # seconds, for no reason: the arc set does not change during recovery.
        source_roots = {dsu.find(src) for (src, _dst) in pc.arcs}

        def net_of(node):
            root = dsu.find(node)
            if root not in net_name:
                counter[0] += 1
                net_name[root] = f"n{counter[0]}"
            return net_name[root]

        def bel_pin(tile_key, bi, port):
            """Resolve a bel pin to its net name via the arc-union DSU.

            The .bt carries no separate 'fixed connection' layer the way
            MachXO2's bel-pin-to-switchbox bridge does — Mistral already
            resolves bel pins to real routing nodes (pnode_to_string), so the
            node IS the DSU key directly; no suffix-stripping bridge needed.
            """
            node = CVNode(tile_key[0], tile_key[1], tile_key[2], bi, port, None)
            return net_of(node)

        # ---- ALM LUT-halves (LAB/MLAB only) ----
        for tile_key, kv in sorted(pc.settings.items()):
            block = tile_key[0]
            if block not in _LAB_LIKE_BLOCKS:
                continue
            alm_masks = {}  # alm_idx -> "hi32.lo32" string
            for (mux, idx), value in kv.items():
                if mux == "LUT_MASK" and idx is not None:
                    alm_masks[idx] = value
            if alm_masks:
                d.n_alms_configured += 1
            for alm_idx, mask in sorted(alm_masks.items()):
                if "." not in mask:
                    continue  # malformed — skip rather than guess
                hi32, lo32 = mask.split(".", 1)
                try:
                    full = (int(hi32, 16) << 32) | int(lo32, 16)
                except ValueError:
                    continue
                for half, bitshift in (("bottom", 0), ("top", 32)):
                    init32 = (full >> bitshift) & 0xFFFFFFFF
                    # Skip an all-zero half: on real designs this is simply
                    # an unused ALM half (the other half, or neither, is
                    # packed in), not a constant-0 driver worth emitting —
                    # same "skip the degenerate case" convention anlogic_lift
                    # uses for all-0/all-1 LUTs.
                    if init32 == 0:
                        continue
                    # Port names are literal strings as the .bt writes them
                    # ("A", "B", "C", "D", "E0", "E1") — no separate port
                    # sub-index (.pi) on these pins, confirmed against the
                    # sample dump, so bel_pin's pi stays None throughout.
                    inputs = _ALM_HALF_INPUTS[half]
                    pins = {p: bel_pin(tile_key, alm_idx, p) for p in inputs}
                    z = bel_pin(tile_key, alm_idx, _ALM_HALF_COMB_OUT[half])
                    cell = f"alm_{block.lower()}_r{tile_key[1]}c{tile_key[2]}_a{alm_idx}_{half}"
                    # init32 bit p already = f(p) (straight extraction above,
                    # no reversal) -- format(..., '032b') is MSB-first text
                    # whose int(_, 2) round-trips to the same integer, which
                    # is exactly the convention load.py's classify_lut() /
                    # lut_dependence() require (#63).
                    d.luts.append({
                        "name": cell,
                        "init": format(init32, "032b"),
                        "a": pins["A"], "b": pins["B"], "c": pins["C"], "d": pins["D"],
                        "e": pins["E0"] if half == "bottom" else pins["E1"],
                        "z": z,
                        "z_used": dsu.find(
                            CVNode(block, tile_key[1], tile_key[2], alm_idx,
                                   _ALM_HALF_COMB_OUT[half], None)
                        ) in source_roots,
                    })

                    # ---- registers fed by this half ----
                    for ff_port in _ALM_HALF_FF_OUT[half]:
                        q_node = CVNode(block, tile_key[1], tile_key[2], alm_idx, ff_port, None)
                        q_root = dsu.find(q_node)
                        if q_root not in source_roots:
                            continue  # unused register output, skip (same convention as MachXO2 d.used_roots gate)
                        d.ffs.append({
                            "name": f"ff_{block.lower()}_r{tile_key[1]}c{tile_key[2]}_a{alm_idx}_{ff_port.lower()}",
                            "q": net_of(q_node),
                            # D source, clock, clear/load selects are all
                            # MUX-encoded in further `s` settings
                            # (xCLK_SEL/xCLR_SEL/xMODE.<alm> etc) that this
                            # first slice does not decode — see module
                            # docstring's out-of-scope list (ALM arithmetic/
                            # register-mode decode). Recording the Q net
                            # (which IS a real routing node) without a
                            # resolved D/CLK is an honest under-connection,
                            # not a guess.
                            "d": None, "clk": None, "ce": None, "lsr": None,
                            "dtype": "cyclonev_alm_reg",
                        })

        d.all_nets = sorted(set(net_name.values()), key=lambda s: int(s[1:]))
        d.n_arcs = len(pc.arcs)
        return d

    # ---- EFB hooks: genuinely N/A for this family (no EFB on Cyclone V) ----
    def load_efb_fixed_conns(self, dbroot=None):
        """Cyclone V has no EFB (that is a Lattice MachXO2 hard-IP concept).
        Returns an empty mapping, same convention as ecp5_lift/gowin_lift/
        anlogic_lift for families without one.
        """
        return {}

    def apply_efb_fixed_conns(self, dsu, efb_conns, cfg_row=None, cfg_col=None):
        """No-op counterpart to load_efb_fixed_conns (see there)."""
        return {}

    # ---- pad / bel lookups --------------------------------------------------
    def pad_fabric_node(self, row, col, pio, direction):
        """Fabric node for a GPIO pad.

        Cyclone V's GPIO block has DATAIN (pad -> fabric) and DATAOUT
        (fabric -> pad) ports, each with a sub-index (`pio`) for the multiple
        pins packed per GPIO tile (seen in the .bt as e.g.
        `GPIO.023.000.2:DATAIN.3`). `row`/`col` here are Mistral's (x, y);
        `pio` is the port sub-index (pi), NOT a PIOA..D letter the way
        Lattice lifters use it — Cyclone V's GPIO numbering is purely
        integer-indexed, there is no A/B/C/D convention in this vendor's
        bitstream.
        """
        port = "DATAIN" if direction == "in" else "DATAOUT"
        return CVNode("GPIO", row, col, None, port, pio)

    def bels_of(self, row, col):
        """All bel-pin nodes at (row, col), grouped like every other lifter's
        bels_of(): {bel_name: {pin_name: <value>}}.

        NOT IMPLEMENTED for this first slice — recover_netlist() above
        resolves ALM pins directly from pc.settings/pc.arcs rather than via a
        bels_of() indirection (there is no separate bel-pin-to-switchbox
        bridge layer in the .bt the way MachXO2/ECP5 need one; Mistral's own
        pnode resolution already does that). Returns {} rather than raising,
        so a generic caller that probes bels_of() speculatively (as load.py's
        pad-connectivity check does) degrades to "nothing found" instead of
        crashing.
        """
        return {}
