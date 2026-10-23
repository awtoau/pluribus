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
`decomp` command) for now. A separate effort has since landed a native Rust
codec (`rust/bluebird/`) + `cv_dies`/`cv_pram_strips` schema tables + importer
(`scripts/cyclonev_db_import.py`) for Cyclone V's bitstream CRAM framing — but
NOT yet the package/pinout table or routing-node tables (see
docs/bluebird.md "Known gaps": "Package/pinout tables (e50f-pkg.txt):
not imported"). So `.bt` text remains the only source of real package-pin
names in this project; swap it for the Rust decoder's own pin data once that
lands — same parse_config() contract, same Design.pads output. Keeping the
.bt grammar isolated in parse_config() (this is the only place that reads the
file) makes that swap a localised change.

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
  * Pads: GPIO DATAIN/DATAOUT nodes are visible in the .bt, pad_fabric_node()
    resolves a fabric node for one, and recover_pads() now also recovers the
    REAL PACKAGE PIN NAME where Mistral's own pin table covers that ball
    (see PIN RECOVERY below) — but there is still no board.toml for any real
    Cyclone V board in this repo (CLAUDE.md: pluribus stores no board data
    without one), so `Design.pads` is engine-only data with nowhere to
    attach a board-level pinout TSV yet. This is genuinely vendor/engine
    data though (which die ball is which), same status as Lattice's
    device-db pinout tables — not board-specific.

PIN RECOVERY — REAL PACKAGE PIN NAMES FROM `.bt` TRAILING COMMENTS
--------------------------------------------------------------------
Mistral annotates a GPIO-touching r/s/i line with the real BGA package pin
name as a trailing `; <pin>` comment whenever its pinout table covers that
ball (`; AA10`, `; Y3`, etc — UFBGA row-letter+column-number coordinates,
5CEBA4U19C8/U19 package). `_trailing_pin()` extracts it from the unmatched
tail each line regex leaves after its required fields; `recover_pads()`
turns the result into `Design.pads` (pad_map-shaped records). Every claim
below was checked against a real decompile (DJI m2001 firmware, read-only
format reference per project scope — no DJI bytes/netlist committed here):
359,956-line `.bt`, 4,858 pin-annotated lines.

  * PIN IDENTITY IS (GPIO tile, bi) — not port, not pi, not line kind.
    Grouping every annotated GPIO node by (x,y,bi) across r/s/i lines and
    every port (DATAIN/DATAOUT/CLKIN/CLKOUT/OEIN/CEIN/CEOUT/ACLR/SCLR/
    BSLIPMAX) gives a CLEAN BIJECTION: 224 distinct (tile,bi) keys, 224
    distinct pin names, zero conflicts either direction. Enforced live by
    `_record_pin_annotation` (raises PinRecoveryError on a mismatch), not
    just checked once offline.
  * pad_fabric_node()'s pre-existing CVNode construction put the `pio`
    argument into the `.pi` slot with `bi=None` — WRONG for Cyclone V, fixed
    in this change (see its docstring): a real `.bt` GPIO node always has
    its block-local sub-index as `bi` (right after x.y, before the colon),
    confirmed zero `GPIO.x.y:PORT.n`-shaped (bi-less) DATAIN/DATAOUT lines
    exist in the sample. This bug was latent/undetected because nothing
    exercises pad_fabric_node() against real data for this family yet
    (load_cyclonev() bypasses load.py's generic pad-probing core entirely).
  * DIRECTION IS UNAMBIGUOUS FROM PORT NAME, not arc position: DATAIN (and
    BSLIPMAX) are the arc SOURCE in 100% of occurrences (1,108/1,108);
    CLKIN/CLKOUT/DATAOUT/OEIN/CEIN/CEOUT/ACLR/SCLR are the arc SINK in 100%
    of occurrences. Matches pad_fabric_node()'s documented convention
    exactly (DATAIN = pad->fabric, DATAOUT = fabric->pad). recover_pads()
    reads direction off which port is present, which is simpler than and
    consistent with reading arc src/dst position.
  * NOT EVERY (tile,bi) IS ANNOTATED: 48/272 GPIO (tile,bi) keys seen in
    real routing have no pin comment anywhere. This is NOT correlated with
    port kind (CLKIN/CLKOUT-only keys are annotated at 86% (61/71), about
    the same rate as DATAIN/DATAOUT-bearing keys at 81% (163/201) — the
    task's a-priori hypothesis that unannotated==clock-passthrough does NOT
    hold). It IS correlated with location: every one of the 12 unannotated
    tiles sits in two y-bands (014-017, 029-031, 033) on BOTH edge columns
    (x=000 and x=054), each 100% unannotated (0 of dozens of lines per
    tile) while immediately adjacent tiles (y 018-021) are ~97% annotated.
    Read as Mistral's own pinout table having no ball for those whole GPIO
    banks on this die/package (plausibly unbonded, or a gap in the table) —
    not a pluribus modelling gap. These rows are kept with pin=None, not
    dropped.
  * MULTI-pi TAPS: 123/195 annotated DATAIN (tile,bi) keys have more than
    one distinct DATAIN.pi in real routing, and EVERY one of those connects
    to a DIFFERENT fabric net per pi (0/123 cases where multiple pi
    converge on the same net) — a real one-physical-pin/several-logical-
    taps situation, not redundant re-derivation. pad_map's single
    net_in/net_out column cannot represent more than one tap; recover_pads()
    keeps the lowest-pi tap as net_in/net_out and records n_datain_taps/
    n_dataout_taps on each pad row so this lossiness is visible rather than
    silent. DATAOUT multi-pi is much rarer (6/55 keys).
  * DIFFERENTIAL PAIRS: `USE_PSEUDO_DIFF_OUTPUT.<bi>`/`USE_DIFF_OUTPUT`/
    `LVDS_BUFFER_USED` settings confirm differential-capable pins are
    per-(tile,bi), each resolving to its OWN distinct ball (e.g.
    `GPIO.044.000:USE_PSEUDO_DIFF_OUTPUT.0 1 ; V15` is bi=0 only; its
    plausible partner bi=1 is a separate ball "U15"). Keying on (tile,bi)
    with no special-case code already gives "two independent pad_map rows,
    one per physical pin" — the schema-correct answer. NOT CONFIRMED,
    though: Mistral never tags which bi is a pair's P vs N, and checking
    row/column adjacency of same-tile bi-pairs across the whole sample found
    only a weak pattern (bi(0,1): 20/56 same-row-adjacent-column; bi(2,3):
    28/56) — consistent with physically neighbouring balls in general, not
    specifically proven as P/N siblings. State this as open, not settled.
  * NON-GPIO PIN COMMENTS: 3,721 pin-annotated r/s/i lines in the sample
    touch a non-GPIO node — all HMC (hard memory controller), confirmed by
    direct grep. HMC is explicitly out of scope for this lifter (no bel
    model for it at all) so these are counted
    (`n_pin_comments_non_gpio`) and excluded from `pin_annotations`, not
    silently merged into the GPIO pin table.
  * 'i' LINES CAN CARRY A SECOND ';'-FIELD: 104/790 annotated i-lines have
    a second ' ; ' introducing an alternate node reference (a hard-IP PHY
    alias, e.g. "; B8 ; HMC.011.045:PHYDDIOADDRDOUT.52 GPIO...DATAOUT.0"),
    never a second pin name (0/1610 r-lines, 0/2458 s-lines ever have a
    second ' ; '). `_trailing_pin()` takes only the first field.
  * SCHEMA FIT (PINS) — REAL MISMATCH, NOT RESOLVED HERE: `pad_map.pin` is
    `Integer NOT NULL` (schema.py); Cyclone V's recovered pin identity is a
    BGA coordinate string ("AA10"), not a number. Every existing lifter
    that populates `pad_map` (MachXO2 from its iomap TSV, GOWIN from
    apicula's `db.pinout`) puts a genuine numeric pin NUMBER there — no
    existing family stores a letter-coded identity in that column, so this
    is not a convention to just follow. `Design.pads` here carries the BGA
    name in BOTH `pin` and `label` (pad_map-shaped, ready to insert) but
    whoever wires it into the DB must first resolve: widen `pad_map.pin` to
    Text (a real DDL change — schema.py owns all DDL, not a lifter's call to
    make unilaterally), or leave `pin` NULL and rely on `label` alone (every
    other family treats `pin` as load-bearing for the UNIQUE(bitstream,pin)
    constraint, so NULL-everywhere would defeat that per board). Flagged for
    a decision, not guessed at.

SCHEMA FIT — ALM-HALF LUT (a-f), UNIFIED INTO `luts`
----------------------------------------------------
- `luts.init` is the 64-char MSB-first table of one ALM half over its six inputs a-f
  (Quartus data port order); `e`/`f` columns are NULL for the 4-input families.
- Letter -> source per half mode: docs/cyclonev-postfit-oracle.md, `_port_pins()`.
  Constant/unrouted letters are "1'b0" and the table is folded so it does not depend on them.
- Registers: one `ffs` row per physical register (half, slot); control sources are kept in
  `Design.ffs[i]["ctl"]` (oracle-checked, see `_ff_controls()`); `d/clk/ce` are written to the
  DB only for plain posedge D flops (no polarity/clear columns exist).
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


# Package-pin-name comment: a BGA row-letter(s) + column-number coordinate,
# e.g. "AA10", "Y3", "C1". Confirmed against a real decompile (DJI m2001,
# 5CEBA4U19C8, 359,956 lines) that every one of the 4,858 trailing pin
# comments in that file matches this shape -- no other comment form appears
# on r/s/i lines in this family's .bt output.
_PIN_RE = re.compile(r"^[A-Z]+[0-9]+$")


def _trailing_pin(line, match_end):
    """Extract the package-pin-name comment trailing a parsed .bt line, or None.

    WHY THIS EXISTS, NOT A WIDER FIELD REGEX
    -----------------------------------------
    _R_LINE_RE/_S_LINE_RE/_I_LINE_RE each match only their declared
    whitespace-delimited fields (\\S+ each) -- none of them anchor to
    end-of-line, so a trailing ' ; AA10' is simply left unconsumed after
    `.match()` returns. This reads exactly that unconsumed tail
    (`line[match_end:]`) rather than widening the field regexes to capture
    it -- the minimal-diff point: the grammar these regexes encode for the
    *required* fields does not change at all.

    GRAMMAR, CONFIRMED AGAINST A REAL DECOMPILE (not assumed)
    -----------------------------------------------------------
    DJI m2001, 5CEBA4U19C8, 359,956-line `.bt`, 4,858 pin-annotated lines:
      r <src> <dst> ; <pin>                   -- 1,610 annotated, ALWAYS one ' ; '
      s <node> <value> ; <pin>                -- 2,458 annotated, ALWAYS one ' ; '
      i <node> <value> ; <pin> [; <alt-node>] -- 790 annotated; 104 of those
                                                  have a SECOND ' ; '
    The second ' ; ' on an 'i' line is an alternate node reference for a
    hard-IP PHY alias, e.g.:
      i HMC.011.045:IOINTADDRDOUT.52 1 ; B8 ; HMC.011.045:PHYDDIOADDRDOUT.52 GPIO.010.045.3:DATAOUT.0
    -- NOT a second pin name: that trailing text is a full
    `BLOCK.x.y.bi:PORT.pi` node reference (colon/dot grammar), never a bare
    BGA coordinate. 0/1610 r-lines and 0/2458 s-lines in the sample ever
    carry a second ' ; ', so only 'i' lines need the second-field strip.
    Only the FIRST ';'-field is treated as the pin; anything after a second
    ';' is discarded.

    SECOND FORM, NOT IN THE e50f REFERENCE SAMPLE BUT SEEN FORCING OTHER
    DIES (cross-die plausibility work, awto-dji#3): an 'i' line with ONLY
    ONE ' ; ', whose single field is itself an alt-node reference, no pin
    at all:
      i HMC.023.000:IOINTDQDOUT.116 0 ; HMC.023.000:PHYDDIODQDOUT.116 GPIO.055.000.2:DATAOUT.0
    Confirmed this is not die-specific noise: the SAME form appears
    forcing the confirmed-good e50f sample (m2001) against gt75f. More
    HMC tiles on a die apparently means more of these no-pin HMC-internal
    aliases. Detected by: the one field doesn't match _PIN_RE AND contains
    a ':' (node grammar) -- treated as "no pin on this line", same as no
    ' ; ' at all, not a grammar-break.
    """
    tail = line[match_end:]
    if " ; " not in tail:
        return None
    pin = tail.split(" ; ", 1)[1].strip()
    if " ; " in pin:          # 'i' line's second field (alt-node) -- drop it
        pin = pin.split(" ; ", 1)[0].strip()
    if not pin:
        return None
    if ":" in pin and not _PIN_RE.match(pin):
        # Single-field alt-node form (see SECOND FORM above): this whole
        # token is a BLOCK.x.y.bi:PORT.pi node reference, not a pin at
        # all -- no board-level pin on this line, not a grammar break.
        return None
    if not _PIN_RE.match(pin):
        # Fail loud rather than silently accept or silently drop: every one
        # of the 4,858 pin comments in the reference sample matches this
        # shape, so a non-matching one means the grammar assumption just
        # broke (a new Mistral comment form, a differently-shaped package)
        # -- exactly the kind of thing that must not pass through as a
        # plausible-looking pin name. Same PinRecoveryError convention:
        # this is a data-integrity signal, not a line to tally and skip.
        raise PinRecoveryError(
            f"pin comment {pin!r} does not match the BGA "
            f"letters+digits shape (_PIN_RE) seen in every annotated line "
            f"of the reference sample -- grammar assumption may be stale."
        )
    return pin


# BGA row-letter sequence skips I, O, Q, S, X, Z (standard JEDEC convention --
# those letters are omitted because they're easily confused with digits/other
# letters on a silkscreen). Confirmed against the real reference sample: every
# row letter seen (A..Y plus AA, AB) is in this sequence, none skipped are
# present. _bga_row_rank() is position-in-this-sequence, not raw alphabet
# index, so e.g. "J" (8th letter, but 7th in this sequence since I is skipped)
# ranks correctly relative to "H" and "K".
_BGA_ROW_LETTERS = "ABCDEFGHJKLMNPRTUVWY"  # single-letter rows, in order


def _bga_row_rank(letters):
    """Rank of a (possibly double-letter) BGA row label within the JEDEC
    skip-I/O/Q/S/X/Z sequence: A=0, B=1, ..., Y=19, AA=20, AB=21, ...

    Double-letter rows continue the SAME skip-sequence two-up, matching how
    real BGA packages extend past Y (seen in the reference sample: AA, AB
    follow Y, not a restart of A-Z). Raises on anything outside the confirmed
    alphabet rather than guessing -- an unrecognised letter means the
    assumption needs re-checking against new data, not silent coercion.
    """
    n = len(_BGA_ROW_LETTERS)
    if len(letters) == 1:
        idx = _BGA_ROW_LETTERS.find(letters)
        if idx < 0:
            raise PinRecoveryError(
                f"BGA row letter {letters!r} not in the confirmed JEDEC "
                f"skip-I/O/Q/S/X/Z sequence {_BGA_ROW_LETTERS!r} -- "
                f"grammar assumption may be stale for this package."
            )
        return idx
    if len(letters) == 2:
        first, second = letters[0], letters[1]
        fi, si = _BGA_ROW_LETTERS.find(first), _BGA_ROW_LETTERS.find(second)
        if fi < 0 or si < 0:
            raise PinRecoveryError(
                f"BGA row letters {letters!r} not in the confirmed JEDEC "
                f"sequence -- grammar assumption may be stale."
            )
        # AA/AB/... continues the single-letter run: after Y (rank n-1) comes
        # AA (rank n), AB (rank n+1), etc -- confirmed: the reference sample
        # has no gap between Y and AA, and no "BA"/"CA" double-letter rows.
        return n + fi * n + si
    raise PinRecoveryError(
        f"BGA row label {letters!r} is neither one nor two letters -- "
        f"grammar assumption may be stale."
    )


def bga_pin_to_int(pin):
    """Stable integer surrogate for a BGA pin name, for pad_map.pin (Integer
    NOT NULL -- Cyclone V's real pin identity is a letters+digits BGA string,
    which doesn't fit that column; decision: keep pin Integer, encode here,
    carry the real string in pad_map.label).

    pin IS NOT THE REAL PIN IDENTITY -- label IS. Treat the integer purely as
    a DB-internal sort/uniqueness key, same role Gowin's lifter already gives
    this column for its own synthesised ("R{row}C{col}") pin values
    (gowin_lift.py's `"pin": pin, "label": iob.get("pin") or f"R{...}C{...}"`
    -- pin-as-derived-key is an established convention here, not new). No
    code should ever try to decode a Cyclone V `pin` integer back into a BGA
    name -- read `label` instead. This also means the encoding scheme is
    vendor/family-specific and NOT portable: a future Altera family with a
    different package convention (or a non-BGA one) needs its OWN encoder,
    not a reuse of this row_rank*1000+col scheme -- there is no shared
    cross-vendor meaning to `pad_map.pin`'s integer value, only a per-family
    "however that lifter chose to make it unique" contract. If a genuine
    cross-family pin-identity comparison is ever needed, it must go through
    `label` (text) comparison, never `pin` (int) comparison.

    Encoding: row_rank * 1000 + column_number. 1000 is a safe multiplier --
    the reference sample's real column numbers top out at 22 (e50f's U19
    package), orders of magnitude under 1000, and even a much bigger
    Cyclone V package (the largest, U23) tops out at 23. Stable and
    collision-free by construction for THIS encoding: distinct (row, col)
    pairs always produce distinct integers for any column count under 1000,
    and the same pin name always encodes to the same integer (no hashing,
    no randomness) -- verified against all 224 real pin names in the
    reference sample, 0 collisions.
    """
    m = _PIN_RE.match(pin)
    if not m:
        raise PinRecoveryError(
            f"{pin!r} does not match the BGA pin shape -- cannot encode."
        )
    letters = re.match(r"^[A-Z]+", pin).group(0)
    digits = pin[len(letters):]
    col = int(digits)
    if col >= 1000:
        raise PinRecoveryError(
            f"pin {pin!r} column {col} >= 1000 -- the row_rank*1000+col "
            f"encoding's safety margin assumption is stale for this "
            f"package, widen the multiplier rather than silently colliding."
        )
    return _bga_row_rank(letters) * 1000 + col


class ParsedConfig:
    """Raw contents of a Mistral `.bt` decompile, before netlist recovery."""

    def __init__(self):
        self.device = None                 # the die/model from the "m" line
        self.options = {}                  # global mux name -> raw value string
        self.arcs = []                      # list of (CVNode src, CVNode dst)
        self.settings = defaultdict(dict)   # tile_key -> {(mux,idx): value}
        self.inverters = {}                 # CVNode -> int (0/1)
        # (block, x, y, bi) -> package pin name ("AA10"), GPIO-block nodes
        # only.  Keyed on (block,x,y,bi) rather than the full CVNode (which
        # also carries port/pi): confirmed against the real sample that the
        # pin identity is a property of the physical ball at that bi within
        # the tile, NOT of which port/pi happened to carry the comment on a
        # given line -- see recover_pads()'s docstring for the empirical
        # check (224 distinct (tile,bi) keys, each with exactly one pin name
        # across every port/pi/line-kind that annotates it, zero conflicts).
        self.pin_annotations = {}
        # Pin comments seen on a non-GPIO block (observed: HMC only, hard
        # memory-controller/IO -- explicitly out of scope for this lifter,
        # see module docstring).  Counted, not silently dropped, so a future
        # reader can see these pin comments exist and were deliberately not
        # captured, rather than conclude the parser missed them.
        self.n_pin_comments_non_gpio = 0
        # Pin comments seen on a GPIO node with bi=None (tile-wide setting,
        # no block-local sub-index) -- not attributable to one physical pin,
        # see _record_pin_annotation's docstring. Also counted, not dropped.
        self.n_pin_comments_bi_less = 0
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

    `pads` follows gowin_lift.py's `Design.pads` convention: a list of dict
    records shaped like `pad_map` columns (pin/label/row/col/pio/direction/
    net_in/net_out). See recover_pads()'s docstring for the Cyclone V
    package-pin recovery this first populates, and the module docstring's
    PIN RECOVERY section for the full edge-case writeup.
    """

    def __init__(self):
        self.luts = []          # [{name, init, a,b,c,d,e, z, z_used}]
        self.ffs = []
        self.pads = []           # [{pin, label, row, col, pio, direction, net_in, net_out}]
        self.net_name = {}
        self.all_nets = []
        self.dsu = None
        self.used_roots = set()
        self.n_arcs = 0
        self.skipped_arcs = 0
        self.tile_counts = {}        # block type -> tile count seen in .bt
        self.n_alms_configured = 0   # LABs/MLABs with >=1 non-default LUT_MASK
        self.unmodelled_halves = defaultdict(int)   # half mode -> count (RAM/ROM/BMNONE, not lifted)
        # Pad-recovery diagnostics (see recover_pads()) -- populated whenever
        # recover_netlist() calls it, kept on Design so callers/selftest can
        # report them without re-deriving from pc.
        self.n_pads_annotated = 0        # (tile,bi) with a resolved pin name
        self.n_pads_unannotated = 0      # (tile,bi) with GPIO routing but no pin
        self.n_pin_comments_non_gpio = 0  # pin comments on non-GPIO (HMC) nodes
        # (tile,bi) pads where >1 distinct DATAIN.pi/DATAOUT.pi tap resolves
        # to a DIFFERENT fabric net -- pad_map.net_in/net_out can only keep
        # one, so these counts flag where that single column is a lossy
        # summary of a real one-pin/many-taps situation. See recover_pads().
        self.n_pads_multi_datain_tap = 0
        self.n_pads_multi_dataout_tap = 0


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


_LAB_LIKE_BLOCKS = ("LAB", "MLAB")

# Default half modes (a half with no TMODE/BMODE setting line).
_DEFAULT_MODE = {"T": "D_E", "B": "C_E"}

_MODELLED_MODES = {"T": ("E_0", "F_0", "D_E", "D_F"), "B": ("E_1", "F_1", "C_E", "C_F")}

# MLAB LUT bits are stored permuted (nextpnr mistral/lab.cc permute_mlab_init).
_MLAB_PERM = [0, 1, 4, 5, 8, 9, 12, 13, 29, 28, 25, 24, 21, 20, 17, 16,
              2, 3, 6, 7, 10, 11, 14, 15, 31, 30, 27, 26, 23, 22, 19, 18,
              32, 33, 36, 37, 40, 41, 44, 45, 61, 60, 57, 56, 53, 52, 49, 48,
              34, 35, 38, 39, 42, 43, 46, 47, 63, 62, 59, 58, 55, 54, 51, 50]


def _port_pins(half, mode):
    """LUT letter (Quartus data port a..f) -> source token for one ALM half.

    Tokens: LAB input pin (A B C D E0 E1 F0 F1), "FB" (register feedback), "0"/"1" (constant).
    Mode name = <d source>_<e source>: D/C = that pin, E = E pin, F = same-half register
    feedback; e source 0/1 = constant (5-input modes).
    Evidence: docs/cyclonev-postfit-oracle.md (conn.* rows, feedback register = FEEDBACK_SEL slot).
    """
    i = "0" if half == "T" else "1"
    d_src = {"D": "D", "C": "C", "E": "E" + i, "F": "FB"}
    e_src = {"E": "E" + i, "F": "FB", "0": "0", "1": "1"}
    if mode[0] not in d_src or mode[2] not in e_src:
        raise ValueError(f"cyclonev lifter: unknown ALM half mode {mode!r}")
    return {"a": "A", "b": "B", "c": "C" if half == "T" else "D",
            "d": d_src[mode[0]], "e": e_src[mode[2]], "f": "F" + i}


_REG_PIN = {("T", False): "E0", ("T", True): "F1", ("B", False): "E1", ("B", True): "F0"}


# enable input of clock n: clk0 -> DATAIN.2, clk1 -> DATAIN.3, clk2 -> DATAIN.0 (983/983, one candidate each)
_ENA_DIN = {"0": 2, "1": 3, "2": 0}


def _ff_controls(block, tile_key, kv, alm_idx, h, slot, lut_fed, sink_nodes):
    """Control sources of register (half h, slot) as {field: source}; a missing key = not recovered.

    source = ("node", CVNode, inverted) | ("lut", (x,y,alm,half)) | ("const", 0|1).
    `inverted` = the register sees NOT(node), the sense of the Quartus post-fit conn flag.
    Every rule below is backed by a corpus differential, 0 exceptions, and fuzz doc items 6-8
    (docs/cyclonev-postfit-oracle.md "Register controls"):
      clk   : {T,B}CLK_SEL names the register PAIR {T0,B1} / {T1,B0} (crossed, not the half);
              source = CLK<n>_INV bit (1 = clkb, else clka; Mistral label swapped, fuzz item 6),
              clka = CLKIN.0 (CLKA_SEL DIN0 -> DATAIN.0), clkb = CLKIN.1 (CLKB_SEL DIN1 -> DATAIN.1);
              negedge = CLK<n>_SEL == CLKB.
      ena   : EN<n>_EN == 0 -> constant 1; else DATAIN.{2,3,0} for clk{0,1,2}, active-low iff
              EN<n>_NINV != 0 (polarity from fuzz item 7; no inverted enable in the corpus).
      clrn  : ACLR0_SEL == ACLR0 -> constant 1 (idle); else DATAIN.3, `!` iff ACLR0_INV == 1.
      sclr  : half SCLR_DIS == 1 -> constant 0; else LAB SCLR_SEL (default DATAIN.3, DIN1 -> DATAIN.1),
              constant 0 when that input is unrouted.
      sload : constant 1 iff the register is pin-fed, else 0 (no sload signal in the corpus).
      d     : LUT-fed -> that half's LUT; pin-fed -> E/F pin per {h}EF_SEL, T: E0/F1, B: E1/F0
              (the F pins are crossed against the LUT halves).
    """
    x, y = tile_key[1], tile_key[2]
    lab = lambda mux: kv.get((mux, None))
    st = lambda mux: kv.get((mux, alm_idx))
    tn = lambda port, pi: CVNode(block, x, y, None, port, pi)
    ctl = {}
    label = "T" if (h, slot) in (("T", 0), ("B", 1)) else "B"
    csel = st(f"{label}CLK_SEL")
    n = csel[3] if csel in ("CLK0", "CLK1", "CLK2") else None
    if n is not None:
        use_b = lab(f"CLK{n}_INV") == "1"
        pick = {(False, None): tn("CLKIN", 0), (False, "DIN0"): tn("DATAIN", 0),
                (True, None): tn("CLKIN", 1), (True, "DIN1"): tn("DATAIN", 1)}
        if block == "MLAB":      # MLAB clka mux: CLKA_SEL GIN2 -> DATAIN.0 (c_shiftreg_{sv,v95,vnd}_1, 1 design)
            pick[(False, "GIN2")] = tn("DATAIN", 0)
        node = pick.get((use_b, lab("CLKB_SEL" if use_b else "CLKA_SEL")))
        if node is not None:
            ctl["clk"] = ("node", node, lab(f"CLK{n}_SEL") == "CLKB")
        if lab(f"EN{n}_EN") == "0":
            ctl["ena"] = ("const", 1)
        else:
            ctl["ena"] = ("node", tn("DATAIN", _ENA_DIN[n]), lab(f"EN{n}_NINV") != "0")
    if st(f"{h}CLR_SEL") != "1":                    # aclr1: no corpus evidence, not recovered
        if lab("ACLR0_SEL") == "ACLR0":
            ctl["clrn"] = ("const", 1)
        else:
            ctl["clrn"] = ("node", tn("DATAIN", 3), lab("ACLR0_INV") == "1")
    if st(f"{h}SCLR_DIS") == "1":
        ctl["sclr"] = ("const", 0)
    elif lab("SCLR_SEL") in (None, "DIN1"):
        node = tn("DATAIN", 1 if lab("SCLR_SEL") == "DIN1" else 3)
        # enabled but its input has no routing = nothing drives it: constant 0 (158/158)
        ctl["sclr"] = ("node", node, lab("SCLR_INV") == "1") if node in sink_nodes else ("const", 0)
    ctl["sload"] = ("const", 0 if lut_fed else 1)
    if lut_fed:
        ctl["d"] = ("lut", (x, y, alm_idx, h))
    else:
        pin = CVNode(block, x, y, alm_idx, _REG_PIN[(h, st(f"{h}EF_SEL") == "F")], None)
        if pin in sink_nodes:
            ctl["d"] = ("node", pin, False)
    return ctl


def _plain_flop(ctl):
    """Posedge D flop with no clear/load and an enable that is constant 1 (or absent source)."""
    clk, clrn, sclr = ctl.get("clk"), ctl.get("clrn"), ctl.get("sclr")
    return (clk is not None and not clk[2] and "d" in ctl and ctl["d"][2:3] != (True,)
            and clrn == ("const", 1) and sclr == ("const", 0) and ctl.get("ena") == ("const", 1))


def _ctl_net(src, net_of, node_of):
    kind, val = src[0], src[1]
    if kind == "const":
        return f"1'b{val}"
    if kind == "node":
        return net_of(val)
    return net_of(node_of(f"{val[3]}COMB"))


def _lut_table(raw, half, mode, mlab, active):
    """64-bit function table (bit v = f(a|b<<1|c<<2|d<<3|e<<4|f<<5)) for one ALM half.

    Stored bits are the inverse of the function; the bottom half sees c/d swapped;
    address = a | b<<1 | j2<<2 | j3<<3 | f<<4 | x5<<5 with x5 = e (E/F e-source) or the mode
    constant, (j2,j3) = (c,d) if x5 == 0 else (d,c); MLAB bits permuted.
    Letters not in `active` (unrouted) are folded to 0: the mask is don't-care there.
    """
    amask = sum(1 << k for k in range(6) if active["abcdef"[k]])
    tt = 0
    for v in range(64):
        a, b, c, d, e, f = (((v & amask) >> k) & 1 for k in range(6))
        if half == "B":
            c, d = d, c
        x5 = e if mode[2] in "EF" else int(mode[2])
        j2, j3 = (c, d) if x5 == 0 else (d, c)
        j = a | b << 1 | j2 << 2 | j3 << 3 | f << 4 | x5 << 5
        if mlab:
            j = _MLAB_PERM[j]
        tt |= (1 - ((raw >> j) & 1)) << v
    return tt


class PinRecoveryError(Exception):
    """A pin-comment grammar assumption broke: either the same GPIO
    (block,x,y,bi) key got two different pin names (see
    _record_pin_annotation), or a pin comment did not match the expected
    BGA letters+digits shape (see _trailing_pin / _PIN_RE).  Deliberately
    NOT a ValueError -- parse_config()'s per-line loop catches ValueError
    to skip one bad line and keep going (ordinary parse leniency, see
    parse_config()'s docstring); either case here is a data-integrity
    signal, not a bad line, and must propagate out rather than being
    silently folded into n_unparsed_lines.
    """


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

    # ---- pin-annotation bookkeeping (shared by r/s/i branches) -------------
    def _record_pin_annotation(self, pc, nodes, pin):
        """Associate a trailing '; <pin>' comment with the GPIO node(s) on
        this line.  `nodes` is a 1- or 2-tuple of CVNode (src+dst for an 'r'
        line, or the single node for an 's'/'i' line).

        ONLY GPIO nodes are recorded (`pc.pin_annotations`); a comment on a
        non-GPIO node (confirmed in the real sample: HMC only, the hard
        memory controller) is tallied in `n_pin_comments_non_gpio` instead of
        being dropped unremarked -- HMC is explicitly out of scope for this
        lifter (module docstring), so its pin data has nowhere to attach yet,
        but a future reader should be able to see it exists rather than
        conclude the parser silently lost it.

        KEY IS (block,x,y,bi), NOT THE FULL NODE -- empirically verified
        -------------------------------------------------------------------
        Checked directly against the real DJI m2001 sample (359,956-line
        .bt, 4,858 pin comments): grouping every annotated GPIO node by
        (x,y,bi) and collecting the pin names seen on ANY port/pi/line-kind
        for that key gives exactly one distinct pin name per key, with zero
        exceptions, across 224 distinct (tile,bi) keys and 224 distinct pin
        names (a clean bijection -- no pin name was ever seen on two
        different (tile,bi), and no (tile,bi) ever showed two different pin
        names). This holds across DATAIN, DATAOUT, CLKIN, CLKOUT, OEIN,
        CEIN, CEOUT, ACLR, SCLR and BSLIPMAX alike -- the physical ball is a
        property of the GPIO tile's sub-pin slot, not of which logical
        signal happens to route through it on a given line. A conflicting
        second pin name at the same (tile,bi) would mean either a real
        multi-ball pin (never observed) or a parser bug; raising
        PinRecoveryError loudly here rather than silently keeping the
        first-seen value is deliberate -- and it is NOT a ValueError, so
        parse_config()'s per-line "skip one bad line" leniency cannot
        swallow it (see PinRecoveryError's own docstring).

        A node with bi=None (e.g. 's GPIO.x.y:DRIVE_STRENGTH.2 ... ; AA2',
        a tile-wide setting with no block-local sub-index at all) is NOT
        pin-identifying on its own and is deliberately NOT stored in
        `pc.pin_annotations` at all -- confirmed empirically that different
        bi-less lines on the SAME tile legitimately carry DIFFERENT pin
        names (e.g. 'DRIVE_STRENGTH.2 ; AA2' and
        'OUTPUT_DUTY_CYCLE_DELAY_FALL.3 ; AA1' on the same GPIO.000.018 --
        each is really about one specific bi via its OWN .pi-style suffix
        on the mux name, the tile-level node string just doesn't expose
        which one). Checked that every bi-less pin IS a subset of that same
        tile's bi'd pins (56/56 tiles, 0 mismatches), so this is consistent
        data, not a parser bug -- just data this parser has no basis to
        attribute to one specific bi, so it is counted
        (`n_pin_comments_bi_less`) and skipped rather than fanned out across
        every sub-pin, which would be a guess.
        """
        for node in nodes:
            if node.block != "GPIO":
                pc.n_pin_comments_non_gpio += 1
                continue
            if node.bi is None:
                pc.n_pin_comments_bi_less += 1
                continue
            key = (node.block, node.x, node.y, node.bi)
            prev = pc.pin_annotations.get(key)
            if prev is not None and prev != pin:
                raise PinRecoveryError(
                    f"conflicting pin annotation at {key}: "
                    f"{prev!r} then {pin!r} -- grammar assumption is wrong, "
                    f"not a real multi-ball pin (never observed in the "
                    f"reference sample); investigate before trusting either."
                )
            pc.pin_annotations[key] = pin

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
                        pin = _trailing_pin(line, m.end())
                        if pin is not None:
                            self._record_pin_annotation(pc, (src, dst), pin)
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
                        pin = _trailing_pin(line, m.end())
                        if pin is not None:
                            self._record_pin_annotation(pc, (node,), pin)
                        continue
                    if tag == "i":
                        m = _I_LINE_RE.match(line)
                        if not m:
                            pc.n_unparsed_lines += 1
                            continue
                        node = parse_node(_strip_comment(m.group(1)))
                        pc.inverters[node] = int(_strip_comment(m.group(2)))
                        pc.n_inverter_lines += 1
                        pin = _trailing_pin(line, m.end())
                        if pin is not None:
                            self._record_pin_annotation(pc, (node,), pin)
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

        src_nodes = {src for (src, _dst) in pc.arcs}

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

        # ---- ALM halves: LUT function, LUT inputs, registers (LAB/MLAB only) ----
        # Mapping evidence: docs/cyclonev-postfit-oracle.md, scripts/cyclonev_lut_pinmap_proof.py.
        sink_nodes = {dst for (_src, dst) in pc.arcs}
        alm_nodes = defaultdict(set)         # (block,x,y) -> ALM indexes touched by routing
        for (src, dst) in pc.arcs:
            for n in (src, dst):
                if n.block in _LAB_LIKE_BLOCKS and n.bi is not None:
                    alm_nodes[n.tile_key()].add(n.bi)
        plans = []                            # (tile_key, alm_idx, {half: plan})
        for tile_key in sorted(set(pc.settings) | set(alm_nodes)):
            block = tile_key[0]
            if block not in _LAB_LIKE_BLOCKS:
                continue
            kv = pc.settings.get(tile_key, {})
            alms = set(alm_nodes.get(tile_key, ())) | {i for (_m, i) in kv if i is not None}
            if any(m == "LUT_MASK" for (m, _i) in kv):
                d.n_alms_configured += 1
            for alm_idx in sorted(alms):
                def st(mux, _kv=kv, _i=alm_idx):
                    return _kv.get((mux, _i))
                raw = (1 << 64) - 1          # no LUT_MASK line = stored all-ones = constant 0
                if st("LUT_MASK") and "." in st("LUT_MASK"):
                    hi32, lo32 = st("LUT_MASK").split(".", 1)
                    raw = (int(hi32, 16) << 32) | int(lo32, 16)
                halves = {}
                for h in "TB":
                    mode = st(f"{h}MODE") or _DEFAULT_MODE[h]
                    if mode not in _MODELLED_MODES[h]:
                        # MLAB RAM/ROM and undecoded patterns (BMNONE): not LUT logic, counted not guessed
                        d.unmodelled_halves[mode] += 1
                        continue
                    node = lambda port, _t=tile_key, _a=alm_idx: CVNode(_t[0], _t[1], _t[2], _a, port, None)
                    fb_slot = 1 if st(f"{h}_FEEDBACK_SEL") == "1" else 0
                    pins = _port_pins(h, mode)
                    # output ports: DFF mux "nlut" = LUT combout, else the register of that slot
                    nlut_ports, reg_ports = [], {0: [], 1: []}
                    for rest, slot in (("0", 0), ("1", 1), ("1L", 1)):
                        port = f"FF{h}{rest}"
                        if node(port) not in src_nodes:
                            continue
                        if (st(f"{h}DFF{rest}") or "REG") == "NLUT":
                            nlut_ports.append(port)
                        else:
                            reg_ports[slot].append(port)
                    uses_fb = "FB" in pins.values()
                    present = {s: bool(reg_ports[s]) or (uses_fb and fb_slot == s) for s in (0, 1)}
                    # register (h,s) is LUT-fed iff the sibling's PKREG bit is clear
                    # (single-register ALMs: d from lcell <=> {h}PKREG{1-s} = 0, no exceptions)
                    lut_fed = {s: present[s] and st(f"{h}PKREG{1 - s}") != "1" for s in (0, 1)}
                    halves[h] = dict(mode=mode, pins=pins, node=node, nlut=nlut_ports,
                                     regp=reg_ports, present=present, fb_slot=fb_slot, lut_fed=lut_fed)
                plans.append((tile_key, alm_idx, raw, kv, halves))

        # the ports of one half carrying the same signal are one net: union before naming
        for tile_key, alm_idx, raw, kv, halves in plans:
            for h, p in halves.items():
                comb = p["node"](f"{h}COMB")
                for port in p["nlut"]:
                    dsu.union(comb, p["node"](port))
                for slot in (0, 1):
                    q = p["node"](f"{h}Q{slot}")
                    for port in p["regp"][slot]:
                        dsu.union(q, p["node"](port))
        source_roots = {dsu.find(src) for (src, _dst) in pc.arcs}

        for tile_key, alm_idx, raw, kv, halves in plans:
            block = tile_key[0]
            is_mlab = block == "MLAB"
            for h, p in halves.items():
                node, pins = p["node"], p["pins"]
                active = {}
                for letter, tok in pins.items():
                    if tok in ("0", "1"):
                        active[letter] = False
                    elif tok == "FB":
                        active[letter] = True
                    else:
                        active[letter] = node(tok) in sink_nodes
                table = _lut_table(raw, h, p["mode"], is_mlab, active)
                arith = kv.get(("ARITH_SEL", alm_idx)) == "ADDER"
                regs_here = [s for s in (0, 1) if p["present"][s]]
                used = bool(p["nlut"]) or any(p["lut_fed"].values()) or (arith and table not in (0, (1 << 64) - 1))
                if used:
                    nets = {}
                    for letter, tok in pins.items():
                        if not active[letter]:
                            nets[letter] = "1'b0"
                        elif tok == "FB":
                            nets[letter] = net_of(node(f"{h}Q{p['fb_slot']}"))
                        else:
                            nets[letter] = net_of(node(tok))
                    d.luts.append({
                        "name": f"alm_{block.lower()}_r{tile_key[1]}c{tile_key[2]}_a{alm_idx}_"
                                f"{'top' if h == 'T' else 'bottom'}",
                        "init": format(table, "064b"),
                        **nets,
                        "z": net_of(node(f"{h}COMB")),
                        "z_used": bool(p["nlut"]),
                        "block": block, "x": tile_key[1], "y": tile_key[2], "alm": alm_idx,
                        "half": h, "mode": p["mode"], "pins": dict(pins),
                        "pin_src": {tok: ("ff", (tile_key[1], tile_key[2], alm_idx, h,
                                               str(p["fb_slot"])))
                                    for tok in pins.values() if tok == "FB"},
                    })
                for slot in regs_here:
                    q_node = node(f"{h}Q{slot}")
                    ctl = _ff_controls(block, tile_key, kv, alm_idx, h, slot, p["lut_fed"][slot], sink_nodes)
                    ff = {
                        "name": f"ff_{block.lower()}_r{tile_key[1]}c{tile_key[2]}_a{alm_idx}_ff{h.lower()}{slot}",
                        "q": net_of(q_node),
                        "d": None, "clk": None, "ce": None, "lsr": None,
                        "dtype": "cyclonev_alm_reg",
                        "block": block, "x": tile_key[1], "y": tile_key[2], "alm": alm_idx,
                        "half": h, "slot": str(slot), "ctl": ctl,
                    }
                    # ffs/verilog.py have no polarity or sync/async-clear columns: only a plain
                    # posedge D flop (no clear/load, enable high or constant) is written to them;
                    # every other register keeps d/clk/ce None (undriven in lifted.v, not guessed).
                    if _plain_flop(ctl):
                        ff["d"] = _ctl_net(ctl["d"], net_of, node)
                        ff["clk"] = _ctl_net(ctl["clk"], net_of, node)
                        ff["ce"] = _ctl_net(ctl["ena"], net_of, node)
                    d.ffs.append(ff)

        d.all_nets = sorted(set(net_name.values()), key=lambda s: int(s[1:]))
        d.n_arcs = len(pc.arcs)
        self.recover_pads(pc, d, net_of)
        return d

    # ---- package-pin recovery (GPIO pads) ----------------------------------
    def recover_pads(self, pc, d, net_of):
        """Build `Design.pads` (pad_map-shaped records) from Mistral's
        trailing package-pin-name comments, collected during parse_config()
        into `pc.pin_annotations` ((block,x,y,bi) -> "AA10"-style name).

        See the module docstring's PIN RECOVERY section for the full
        empirical writeup this method's logic is derived from (every claim
        below was checked against the real DJI m2001 sample, not assumed).
        Summary of what matters for THIS method's logic:

        - The pin name is a property of (GPIO tile, bi) -- confirmed 1:1,
          zero conflicts, across every port/pi/line-kind that annotates it
          (also enforced live, not just checked once: _record_pin_annotation
          raises PinRecoveryError on a real mismatch). So this method keys
          off (x, y, bi), exactly like pad_fabric_node() after its fix above
          -- NOT off individual DATAIN.pi/DATAOUT.pi routing taps, several of
          which commonly multiplex onto the same physical pin (123/195
          annotated (tile,bi) keys have >1 distinct DATAIN.pi in the sample).
        - DATAIN is always the arc SOURCE and DATAOUT always the arc SINK in
          every annotated (and unannotated) GPIO routing line in the sample
          (1,108/1,108 occurrences, zero exceptions) -- matches
          pad_fabric_node()'s documented convention (DATAIN = pad->fabric,
          DATAOUT = fabric->pad) exactly, so direction is read off which
          port name is present, not off arc position.
        - A (tile,bi) with no DATAIN/DATAOUT at all (only CLKIN/CLKOUT/OEIN/
          etc) still gets a pad_map-shaped row IF it has a pin name --
          Mistral itself attaches real package pins to clock-only GPIO
          pins (dedicated clock input/output balls), and dropping them
          would silently discard real pin data. `direction` for such a
          pad is recorded as "unknown" (see below) rather than invented.
        - Pin coverage is NOT port-kind-correlated -- checked directly:
          CLKIN/CLKOUT-only (tile,bi) keys are annotated at about the same
          rate (61/71, 86%) as DATAIN/DATAOUT-bearing ones (163/201, 81%).
          Coverage IS whole-tile-correlated instead: every (x,y) tile at
          y in {014..017, 029..031, 033} on both the x=000 and x=054 edge
          columns is 100% unannotated (0 of its lines, every bi, every
          port) while immediately adjacent tiles (y 018..021 at x=000) are
          ~97% annotated. This is Mistral's package-pinout table having no
          ball for that whole GPIO bank in this specific package/die combo
          (plausibly unbonded in the real BGA, or simply a gap in Mistral's
          table) -- NOT a per-port or per-direction gap. Recorded as
          `pin=None` rows (see below), not silently dropped.
        - Differential pairs: `USE_PSEUDO_DIFF_OUTPUT`/`USE_DIFF_OUTPUT`/
          `LVDS_BUFFER_USED` settings are seen is-a per-(tile,bi) property
          (e.g. `s GPIO.044.000:USE_PSEUDO_DIFF_OUTPUT.0 1 ; V15` is bi=0
          only) with each half of a plausible pair (adjacent bi's, e.g.
          bi=0 "V15" / bi=1 "U15" at that same tile) recovering as its own
          independent (tile,bi) with its OWN distinct ball -- exactly the
          "two independent pad_map rows" shape the task expects, achieved
          automatically by keying on (tile,bi) with no special-case code.
          NOT independently confirmed, though, and stated as such: Mistral
          never tags which bi is the P and which is the N of a pair, and
          checking row/column adjacency of same-tile bi pairs across the
          whole sample found only a WEAK pattern (bi(0,1) pairs: 20/56
          same-row-adjacent-column; bi(2,3) pairs: 28/56) -- consistent with
          physically-neighbouring balls in general, not specifically
          confirmed as P/N differential siblings. This method does not
          attempt to pair bi's into P/N -- it emits one row per (tile,bi),
          which is correct either way (differential or not, pad_map is
          per-physical-pin), and leaves P/N pairing an open question (see
          docs/cyclonev-lifter-status.md).
        - Annotations on a non-GPIO node (confirmed: HMC only, the hard
          memory controller) are OUT OF SCOPE for this method -- HMC is not
          a bel this lifter models at all (module docstring) -- and are
          counted (`d.n_pin_comments_non_gpio`) rather than silently lost;
          `_record_pin_annotation` already filtered them out of
          `pc.pin_annotations` during parsing.

        `d.pads` rows match gowin_lift.py's `Design.pads` shape (and hence
        `pad_map`'s columns): pin/label/row/col/pio/direction/net_in/net_out.
        `pin` here is the BGA pin NAME ("AA10"), not a number -- see the
        module docstring's SCHEMA FIT (PINS) section for why that is a real
        pad_map.pin type mismatch (Integer) flagged for a schema decision,
        not papered over here. `label` carries the same BGA name so the
        pad is still human-identifiable even if `pin` ends up NULL for a
        schema reason outside this method's control.
        """
        # Every (block,x,y,bi) GPIO key that shows up in real ROUTING (pc.arcs
        # only, not pc.settings/pc.inverters) -- this is the authoritative
        # "a pad exists here" set, same role arc_endpoint_sets() plays for
        # other lifters. Deliberately NOT built from 'i' (inverter) lines:
        # an `i GPIO.x.y.bi:DATAOUT.n 1` polarity bit can exist on a port
        # that was never actually wired into an `r` arc (e.g. GPIO.044.000.0
        # in the real sample has 4 DATAOUT inverter lines but 0 DATAOUT
        # arcs) -- counting that as a routed output tap would overstate
        # connectivity that reach.py's own arc-based analysis would not see.
        # A key can appear with bi=None too (tile-wide settings/arcs with no
        # block-local sub-index); those are genuinely not a single pad and
        # are excluded here, same as _record_pin_annotation excludes them
        # from conflict-checking.
        tile_bi_ports = defaultdict(set)   # (x,y,bi) -> {(port, pi, is_src)}
        for (src, dst) in pc.arcs:
            for node, is_src in ((src, True), (dst, False)):
                if node.block != "GPIO" or node.bi is None:
                    continue
                tile_bi_ports[(node.x, node.y, node.bi)].add(
                    (node.port, node.pi, is_src))

        for (x, y, bi), ports in sorted(tile_bi_ports.items()):
            pin = pc.pin_annotations.get(("GPIO", x, y, bi))
            if pin is not None:
                d.n_pads_annotated += 1
            else:
                d.n_pads_unannotated += 1

            # Direction: DATAIN present (always arc src, verified above) ->
            # this pad can be driven FROM the package pin ("in" capable);
            # DATAOUT present (always arc dst) -> "out" capable. A pad can
            # be both (bidir-capable pin used both ways by different pi
            # taps) or neither (clock/control-only pin -- CLKIN/CLKOUT/OEIN/
            # etc with no DATAIN/DATAOUT at all).
            has_datain = any(p == "DATAIN" for (p, _pi, _s) in ports)
            has_dataout = any(p == "DATAOUT" for (p, _pi, _s) in ports)
            if has_datain and has_dataout:
                direction = "bidir"
            elif has_datain:
                direction = "in"
            elif has_dataout:
                direction = "out"
            else:
                # Clock/control-only GPIO pin (CLKIN/CLKOUT/OEIN/CEIN/CEOUT/
                # ACLR/SCLR/BSLIPMAX with no DATAIN/DATAOUT tap on this bi).
                # "unknown" rather than guessing "in" or "out": a dedicated
                # clock pin's own in/out sense is a property this .bt data
                # does not state directly (it's always the arc dst, like
                # DATAOUT, but it is not a DATAOUT port) and guessing would
                # misrepresent it to a downstream board.toml author.
                direction = "unknown"

            # net_in/net_out: pad_map has exactly ONE net_in/net_out column
            # per pad, but a real (tile,bi) frequently has SEVERAL distinct
            # DATAIN.pi (or, rarer, DATAOUT.pi) taps that resolve to
            # DIFFERENT fabric nets -- checked directly against the real
            # sample: of the 123/195 DATAIN (tile,bi) keys with >1 pi,
            # EVERY one of them has a DISTINCT fabric node per pi (0 cases
            # where multiple pi's converge on the same node). This is a
            # genuine representation gap, not a detail to paper over by
            # picking one tap and calling it done: a physical pin can carry
            # several independently-routed logical taps (plausibly
            # different SERDES/DDR phase or delay-chain variants of the one
            # input buffer) and pad_map's single net_in column cannot hold
            # more than one without a schema change (see module docstring's
            # SCHEMA FIT (PINS) section -- flagged alongside the pin-type
            # mismatch, not fixed here). The lowest-numbered pi is kept as
            # the representative net (deterministic, not "first in
            # iteration order") and n_datain_taps/n_dataout_taps record how
            # many were actually seen, so a reader can tell at a glance
            # when net_in/net_out is a lossy summary rather than the only
            # real tap.
            datain_taps = sorted(
                (p_pi, p_name) for (p_name, p_pi, _s) in ports if p_name == "DATAIN")
            dataout_taps = sorted(
                (p_pi, p_name) for (p_name, p_pi, _s) in ports if p_name == "DATAOUT")
            net_in = (net_of(CVNode("GPIO", x, y, bi, "DATAIN", datain_taps[0][0]))
                      if datain_taps else None)
            net_out = (net_of(CVNode("GPIO", x, y, bi, "DATAOUT", dataout_taps[0][0]))
                       if dataout_taps else None)

            # pad_map.pin is Integer NOT NULL, but a BGA name ("AA10") isn't
            # one -- encode via bga_pin_to_int() (stable, collision-free, see
            # its docstring) so the real UNIQUE(bitstream,pin) DB constraint
            # stays meaningful; label carries the human-readable BGA string.
            # Unannotated pads (pin is None) have no DB-facing pin identity
            # at all yet -- load_cyclonev() must skip them for the pad_map
            # insert (no sentinel value invented here; see module docstring).
            d.pads.append({
                "pin": bga_pin_to_int(pin) if pin is not None else None,
                "label": pin if pin is not None else
                       f"GPIO_{x:03d}_{y:03d}_{bi}",
                "row": x, "col": y, "pio": bi,
                "direction": direction,
                "net_in": net_in, "net_out": net_out,
                "n_datain_taps": len(datain_taps),
                "n_dataout_taps": len(dataout_taps),
            })
            if len(datain_taps) > 1:
                d.n_pads_multi_datain_tap += 1
            if len(dataout_taps) > 1:
                d.n_pads_multi_dataout_tap += 1

        d.n_pin_comments_non_gpio = pc.n_pin_comments_non_gpio
        return d.pads

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
        (fabric -> pad) ports. `row`/`col` here are Mistral's (x, y); `pio`
        is the generic cross-lifter "which pin within this tile" parameter
        every other family's pad_fabric_node() takes (ECP5's PIO letter,
        MachXO2's PIOA..D) — for Cyclone V that is the block-local `bi`
        sub-index right after the tile coordinate (e.g. the "2" in
        `GPIO.023.000.2:DATAIN.3`), NOT the port sub-index `pi` after the
        colon (the "3" above). This was fixed from an earlier version that
        put `pio` into the `.pi` slot and left `bi=None` -- that produced a
        node like `GPIO.023.000:DATAIN.2`, which never appears in a real
        decompile (confirmed: grepping the sample .bt for a GPIO node with
        no bi but a DATAIN/DATAOUT port finds zero lines) and is a different
        physical pin from what the caller asked for (bi, not pi, is what
        recover_pads() proved is 1:1 with a physical ball -- see its
        docstring). `pi` (the port instance: DATAIN.0 vs DATAIN.1 etc, which
        multiplexes several routing taps onto the SAME physical pin, see
        module docstring's PIN RECOVERY section) has no slot in this
        generic 4-argument interface at all -- no other family has that
        extra dimension, so there is nowhere to pass it; a caller needing a
        specific `pi` must go around this method, as recover_pads() does.
        """
        port = "DATAIN" if direction == "in" else "DATAOUT"
        return CVNode("GPIO", row, col, pio, port, None)

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
