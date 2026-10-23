# Cyclone V lifter — status

First slice of a fifth pluribus family: Altera/Intel Cyclone V. Not a
Lattice-trellis family — different vendor, different fabric (ALM/LAB,
not PFU/slice). Code: `lifters/cyclonev_lift.py`. Selftest:
`scripts/cyclonev_lift_selftest.py`.

## Scope: one die, e50f (5CEBA4U19C8)

The die behind DJI Lightbridge module m2001. Chosen because it has
confirmed-working Mistral decode data this session (56,337/443k routes
resolved). `CycloneVLift.__init__` hard-rejects any other device string —
extending to another Cyclone V die needs its own ALM/LAB geometry check
against Mistral, not assumed from e50f.

## Implemented

- `parse_config(path)` — reads a Mistral `.bt` decompile (text), tags
  `m`/`o`/`r`/`s`/`i`. One regex (`_NODE_RE`) parses every node form
  Mistral's `pnode_coords`/`rnode_coords::to_string()` emits
  (`BLOCK.x.y[.bi][:PORT[.pi]]`), read directly from
  `mistral-cv/main.cc:decompile` rather than guessed.
- `recover_netlist(pc)` — unions all `r` arcs via DSU, then for every
  LAB/MLAB tile with a non-default `LUT_MASK.<alm>` setting, recovers
  both ALM halves as LUT5 cells (`Design.luts`, unified — see "Schema fit"
  below) plus any register (FFT0/FFT1/FFT1L/FFB0/FFB1/FFB1L) whose Q
  output is actually routed.
- `arc_endpoint_sets`, `pad_fabric_node` (GPIO DATAIN/DATAOUT — fixed this
  session, see "Pin recovery" below), `recover_pads` (real package-pin
  recovery into `Design.pads`, see "Pin recovery" below),
  `load_efb_fixed_conns`/`apply_efb_fixed_conns` (no-ops — no EFB on this
  vendor), `bels_of` (returns `{}` — not needed by this lifter's own
  recovery path, see below).
- Registered in `lifters/trellis_lift.py`'s `TrellisLift()` dispatcher as
  family `"cyclonev"`.

## Proven (scripts/cyclonev_lift_selftest.py, real DJI m2001 firmware)

Ran against a 360k-line `.bt` decompiled from
`awto-dji/firmware/.../m2001.depack.bin` (DJI firmware read only for
format reference per the task scope — no DJI bytes or netlist content
committed to this repo):

- 0 unparsed lines out of 360,016 (70,007 arcs + 288,416 settings + 1,522
  inverters + 10 options + 1 model line).
- 33,336 ALM-half LUT5 cells recovered (1,832 LABs/MLABs with >=1
  configured ALM).
- 11,502 registers recovered (Q net only — see "D/CLK unresolved" below).
- 144,296 distinct nets named.
- No crash, no `db.die()` escape — this script does not touch the
  database at all (see "No board" below).

## Pin recovery: real package-pin names from Mistral's `.bt` comments

Mistral annotates GPIO-touching `r`/`s`/`i` lines with the real BGA package
pin name (`; AA10`, UFBGA U19 coordinates) wherever its own pin table covers
that ball. `lifters/cyclonev_lift.py`'s `_trailing_pin()` extracts it;
`recover_pads()` turns it into `Design.pads` (pad_map-shaped records:
pin/label/row/col/pio/direction/net_in/net_out, plus `n_datain_taps`/
`n_dataout_taps`). `scripts/cyclonev_lift_selftest.py` reports the numbers
below alongside LUT/FF/net counts. Full edge-case detail lives in
`cyclonev_lift.py`'s module docstring (PIN RECOVERY section) — this is a
condensed summary with confidence levels stated per finding.

**Real numbers, same DJI m2001 sample (HIGH confidence — directly measured):**

- 272 distinct GPIO `(tile,bi)` pads seen in real routing; 224 (82.4%) carry
  a resolved package pin name, 48 do not.
- 224 distinct pin names recovered, zero appearing on more than one pad row
  (a clean bijection, enforced live by `PinRecoveryError` — not just checked
  once offline).
- Direction breakdown: 146 `in`, 49 `bidir`, 6 `out`, 71 `unknown` (clock/
  control-only GPIO pins with no DATAIN/DATAOUT routed tap — see module
  docstring for why "unknown" rather than a guessed in/out).
- 123/195 annotated DATAIN pads have more than one distinct `DATAIN.pi` tap
  in real routing, and every one resolves to a DIFFERENT fabric net (0 cases
  of redundant re-derivation) — a genuine one-pin/several-logical-taps
  situation `pad_map`'s single `net_in` column cannot fully represent (see
  "Schema gap" below). 6/55 DATAOUT pads have the same multi-tap shape.
- 3,721 pin-annotated lines touch a non-GPIO node — all `HMC` (hard memory
  controller) by direct grep; out of scope for this lifter (no HMC bel
  model), counted and excluded rather than silently merged into GPIO data.

**Edge cases found and how each is handled (HIGH confidence unless stated):**

1. **Pin identity is `(GPIO tile, bi)`, not port/pi/line-kind.** Checked by
   grouping every annotated GPIO node by `(x,y,bi)` across every port
   (DATAIN/DATAOUT/CLKIN/CLKOUT/OEIN/CEIN/CEOUT/ACLR/SCLR/BSLIPMAX) and
   line kind (`r`/`s`/`i`): exactly one pin name per key, zero conflicts.
2. **A pre-existing bug in `pad_fabric_node()` was found and fixed.** It
   built `CVNode("GPIO", row, col, None, port, pio)` — `pio` into the `.pi`
   slot, `bi` left `None`. Real `.bt` GPIO nodes always carry their
   block-local sub-index as `bi` (confirmed: zero bi-less
   `GPIO.x.y:DATAIN/DATAOUT.n` lines exist in the sample); the method now
   builds `CVNode("GPIO", row, col, pio, port, None)`. Was latent/undetected
   because nothing exercises this method against real Cyclone V data yet
   (`load_cyclonev()` bypasses `load.py`'s generic pad-probing core).
3. **Direction is unambiguous from port name, not arc position.** DATAIN
   (and BSLIPMAX) are the arc source in 100% of 1,108 occurrences;
   CLKIN/CLKOUT/DATAOUT/OEIN/CEIN/CEOUT/ACLR/SCLR are the arc sink in 100%
   of occurrences, with zero exceptions — matches `pad_fabric_node()`'s
   documented DATAIN=pad→fabric / DATAOUT=fabric→pad convention exactly.
4. **Unannotated pads are NOT port-kind-correlated** (disproving the a
   priori hypothesis that they'd be clock-passthrough-only): CLKIN/CLKOUT-
   only `(tile,bi)` keys are annotated at 86% (61/71), about the same rate
   as DATAIN/DATAOUT-bearing keys at 81% (163/201). They ARE
   location-correlated: every GPIO tile at `y` in `{014-017, 029-031, 033}`
   on both edge columns (`x=000`, `x=054`) is 100% unannotated — 0 of
   dozens of lines per tile, every bi, every port — while adjacent tiles
   (`y` 018-021) are ~97% annotated. Read as Mistral's own pinout table
   having no ball for those whole GPIO banks on this die/package (plausibly
   unbonded, or a table gap), not a per-port/per-direction effect.
5. **Differential pairs: pin data confirms per-(tile,bi) ball identity,
   P/N pairing itself is OPEN, not confirmed.** `USE_PSEUDO_DIFF_OUTPUT.0`/
   `USE_DIFF_OUTPUT`/`LVDS_BUFFER_USED` settings are per-bi, and keying
   `Design.pads` on `(tile,bi)` with no special-case code already produces
   "two independent pad_map rows, one per physical pin" for a plausible
   pair (e.g. bi=0 "V15" / bi=1 "U15" at `GPIO.044.000`) — the schema-
   correct answer either way. **MEDIUM/LOW confidence on which bi's form a
   pair**: Mistral never tags P vs N explicitly, and checking row/column
   adjacency of same-tile bi-pairs across the whole sample found only a
   weak pattern (bi(0,1): 20/56 same-row-adjacent-column; bi(2,3): 28/56) —
   consistent with physically neighbouring balls generally, not specifically
   proven as differential siblings. Stated as open, not guessed at.
6. **`i` lines can carry a second `;`-field** (104/790 annotated i-lines):
   an alternate hard-IP node reference, never a second pin name (0/1610
   r-lines, 0/2458 s-lines ever have one). `_trailing_pin()` takes only the
   first field.

**Schema gap — resolved, no schema.py change made:**

`pad_map.pin` is `Integer NOT NULL`; Cyclone V's recovered pin identity is a
BGA coordinate string (`"AA10"`), not a number. Decision (operator): keep
`pad_map.pin` as `Integer` for every family (no DDL change), have the
Cyclone V lifter derive a stable integer surrogate. `bga_pin_to_int()`
(`lifters/cyclonev_lift.py`) encodes `row_rank * 1000 + column_number`
(JEDEC skip-I/O/Q/S/X/Z row sequence, verified collision-free against all
224 real pin names in the reference sample — 224 distinct pins, 224 distinct
encodings, 0 collisions). `label` carries the real BGA string and is the
only field anyone should treat as the pin's real identity — `pin` is a
DB-internal sort/uniqueness key only, same role Gowin's lifter already gives
this column for its own synthesised pin values, not a new convention. The
encoding is Cyclone-V-specific and NOT portable to a future Altera family
with a different package convention — see `bga_pin_to_int()`'s docstring.

## Explicitly out of scope (upstream-Mistral unknowns or deferred — not pluribus gaps)

- **M10K block-RAM contents** — Mistral itself does not decode this;
  confirmed this session. Not attempted here.
- **DSP block config** — Mistral decompiles DSP tiles to named `s DSP.*`
  settings (MODE etc) but does not itself say what they mean operationally.
  A separate fuzz campaign maps Quartus-known DSP operations to those
  settings as ground truth — see `docs/cyclonev-dsp-fuzz-status.md`
  (multiplier modes M9X9/M18X18/M27X27 confirmed; accumulate/systolic modes
  still open). Not wired into this lifter yet.
- **HPS** (hard processor system), **PLLs/FPLL**, **HMC/DQS16** (hard
  memory controller / IO), **CMUX\*** clock muxes, **SERPAR**
  (serial/deserial) — all have `s`-line settings in the `.bt`; none
  modelled into cells/nets.
- **ALM arithmetic/carry mode** (`ARITH_SEL=ADDER` etc) — recorded but not
  synthesised into a carry-chain netlist (no CCU2-style pass yet).
- **Register D/CLK/CE/clear source** — `Design.ffs` entries carry a real Q
  net but `d`/`clk`/`ce`/`lsr` are `None`. Resolving them needs decoding
  the `xCLK_SEL`/`xCLR_SEL`/`xMODE.<alm>` mux settings per ALM, which is
  real work deferred to the next slice, not done here.
- **Pads**: `pad_fabric_node()` resolves GPIO DATAIN/DATAOUT nodes and
  `recover_pads()` recovers real package-pin names into `Design.pads` (see
  "Pin recovery" above), with the `pad_map.pin` schema question resolved
  (`bga_pin_to_int()`, no DDL change). `Design.pads` is still NOT wired into
  `load_cyclonev()`/the database — that insert path itself (a
  `conn.execute(insert(schema.pad_map), ...)` call mirroring how `luts`/`ffs`
  are already inserted) is real follow-on work, not done here. See "No
  board" below for the separate board-level gap (no real Cyclone V board
  exists in-tree, so `chip_ref`/`chip_pin`/`chip_signal` etc. would stay
  NULL even once this is wired up).

## Schema fit: LUT5, unified into `schema.py`'s `luts` table — DONE

Previously flagged as deliberate follow-on work; done this session.

- `schema.py`'s `luts`: `init` widened to `String(32)` (2**5 bits; SQLite
  doesn't enforce `String(N)` length at all — verified directly — Postgres
  does, so this bound is load-bearing there), plus a new `e` column
  (NULL for every 4-input family) for the ALM-half's E0/E1 pin.
- `recover_netlist()` appends ALM-half LUT5 cells straight onto
  `Design.luts` (same row shape as every other family:
  `name`/`init`/`a`/`b`/`c`/`d`/`e`/`z`/`z_used`), `init` as the 32-char
  MSB-first binary string (`format(init32, "032b")`) `classify_lut()`
  expects. `Design.alm_luts` is gone.
- `load.py`'s `classify_lut()` and `machxo2_lift.lut_dependence()` derive
  input count from `len(init_str)` (16→a-d, 32→a-e) instead of a
  hardcoded 16/4. One new pattern at nd==5 (LUT5 only): cascaded 2-select
  mux tree `MUX(sel0,i0,MUX(sel1,i1,i2))`. nd==4 stays a pure `COMBO4`
  fallback, deliberately not pattern-matched — a wire mux is inherently
  odd-width (2k+1 for k selects), so no clean nd==4 mux shape exists
  without also reclassifying some already-correct 4-input Lattice/Gowin/
  Anlogic LUTs, which is out of scope.
- Verified zero behavior change for existing families: exhaustive
  differential test over all 65,536 possible 16-bit truth tables (0
  mismatches vs pre-change logic); full Hantek/MachXO2 pipeline
  regression — identical `2611/1280 (203%) LUTs, 1108 FFs, 4341 nets`,
  passing LEC against the pre-change Verilog output.
- Now wired into `load.py` (`load_cyclonev()`) and emitted by `verilog.py`
  (its LUT query selects `e`) — see "load.py: wired up" and "verilog.py:
  emits LUT5" below. `_evaluate_lut_init` (reach3.py) still raises loudly
  on anything but a 16-char init (untouched — not part of this slice).
- `scripts/cyclonev_lift_selftest.py` now calls `classify_lut()` /
  `lut_dependence()` directly on the 33,336 real ALM-half LUT5 cells
  recovered from the DJI m2001 firmware, confirming the unified path
  end-to-end without touching the database.

## Input-format dependency: Mistral `.bt` now, Rust decoder later

A concurrent effort is building a native Rust Cyclone V decoder +
device-db-style schema table. At the time this was written, neither had
landed (checked: no `rust/`/`Cargo.toml`, no `device_fingerprints`-style
Cyclone V table in `schema.py`, no `cyclonev_db_import.py` in
`scripts/`). `parse_config()` reads Mistral's `.bt` text format for now —
state this explicitly rather than block on the other effort. The .bt
grammar is isolated in one regex (`_NODE_RE`) and one parse loop; swapping
the source (reading the Rust decoder's own output instead) is a localised
change to `parse_config()`, not a change to `recover_netlist()` or the
lifter interface.

## load.py: wired up

`load_cyclonev(label, config_path, device)` is a dedicated load path
(same shape as `load_anlogic()`) — NOT driven through `load.py`'s generic
Trellis/pin-TSV-shaped core, since Cyclone V has no board.toml/pad layer.
Dispatched via `--lifter cyclonev` in `main()` (same `--lifter` flag every
family uses, no new flag invented), exempted from the `--pins` requirement
the same way `anlogic` is.

- Device validated up front (`5CEBA4U19C8` only), same check as
  `CycloneVLift.__init__`, so a wrong `--device` fails immediately with a
  clear message instead of inside the lifter.
- `bitstreams.package` has no real value to put (no board/pinout exists)
  — stored as the literal string `"UNKNOWN"`, an explicit sentinel, not a
  guess, satisfying the column's NOT NULL.
- Inserts `nets`, `luts` (a-e + classify_lut `fn`/`deps`), `ffs` (Q net
  only), `net_fanout` (LUT inputs — FF d/clk/ce/lsr are all NULL so
  contribute nothing), and `arcs` (CVNode `.x`/`.y` stand in for the
  Lattice-shaped `tile_row`/`tile_col` columns — same 2D-grid concept,
  different vendor's coordinates).
- Always-rebuild per label, same as every other family.

**Verified end-to-end** against the real DJI m2001 firmware (same sample
the selftest uses — read-only reference, no bytes committed):

```
mistral-cv decomp 5CEBA4U19C8 m2001.depack.bin /tmp/m2001_wireup_test.bt
PLURIBUS_SQLITE_PATH=tmp/cyclonev_test.db python3.15t load.py \
    --lifter cyclonev --label M2001_TEST \
    --config /tmp/m2001_wireup_test.bt --device 5CEBA4U19C8
```

Rows landed in the DB exactly match the selftest's in-memory numbers:
33,336 LUTs, 11,502 FFs, 144,296 nets, 70,007 arcs, 166,680 net_fanout
rows. No dedup drift between the selftest's `Design.all_nets` count and
the DB's `COUNT(*) FROM nets` — same net-naming path, so none expected.

## verilog.py: emits LUT5

LUT query now selects `e` (`SELECT cell, init, a, b, c, d, e, z, fn`); two
other `luts` row-unpacking sites (net-naming pass, undriven-net scan) were
also missed on the first pass and fixed to the 9-tuple shape. Extended,
not duplicated:

- `_simplify_lut`, `_lut_active_positions`, `_lut_init_to_case` all derive
  width from `len(init)` (16 or 32) instead of assuming 4 inputs; `e` is
  an optional parameter, `None` for every 4-input family.
- `_FN_RULES`' character classes widened `[abcd]` -> `[abcde]` (inert for
  4-input families — the letter `e` never appears in their fn tags), plus
  one new rule for the LUT5-only nested mux tag
  `MUX(sel0,i0,MUX(sel1,i1,i2))` from `load.py`'s `_mux5_tree`. That tag's
  OUTER level is sel0=1->i0 (inverted from the single-level MUX's
  sel=0->i0 convention) — verified by exhaustive 0-mismatch check over all
  120 role-permutations against `_mux5_tree`'s own bit-check, not assumed
  from the naming.
- **Pre-existing bug surfaced, now fixed**: `emit_ffs()` spliced an
  unresolved clock's `/* no_clk */` placeholder straight into
  `always @(posedge /* no_clk */)` — invalid Verilog, never hit before
  because every prior family always resolves a real clock net. Cyclone V's
  FFs (Q-net-only, D/CLK/CE/LSR unresolved — a real, documented gap, not a
  bug) are the first caller to exercise this path. Fixed in all 3 sites
  (stuck-at-reset / CE-gated-clear / real-D groups): an unresolved clock
  now emits a comment block ("clock unresolved, left undriven") instead of
  a fabricated always block — same under-connect-don't-guess convention as
  the rest of this lifter.

**Verified**: ran `verilog.py` against the M2001_TEST bitstream above —
`iverilog`: 0 errors, 0 warnings. `yosys`: loads cleanly (post-opt shows
21,815 wires; no top-level ports since there's no pad layer, expected).
Spot-checked both LUT5 emission shapes:

```verilog
localparam [31:0] _lut_alm_lab_r10c10_a0_bottom = 32'b00000111000100000010010000000100;
assign alm_lab_r10c10_a0_bottom = _lut_alm_lab_r10c10_a0_bottom[{n17301, n17300, n17299, n17298, n17297}];
```

(COMBO5 bit-select form — the overwhelming majority: 33,202/33,336 real
ALM-half LUTs in this sample have no clean 1-4-input structured pattern.)
No real cell in this sample happened to classify as a structured
MUX/AND/OR tag using `e`, so the structured-fn `e`-substitution and nested
MUX rule are verified by the exhaustive synthetic check above instead,
not by a real-corpus example — flag this if a future corpus sample does
hit one, as an additional real-world data point.

## Regression check: zero impact on existing families

`scripts/run_pipeline.py --board boards/aw2-2d82auto --label V02`
(Hantek/MachXO2) re-run after all `load.py`/`verilog.py` changes above:
identical `2611/1280 (203%) LUTs, 1108 FFs, 4341 nets` fabric line,
`check_verilog.py` PASS (0 errors, 0 conflicting-driver, 0 combinational
loops) — unchanged from every prior regression check this session.

## No board

Per CLAUDE.md, pluribus stores no board data without a real board.toml —
none exists for any Cyclone V board, so none was added here (DJI's m2001
is explicitly out of tree — private RE work, not published). This is
separate from the pin recovery above: `Design.pads` resolves real
PACKAGE-pin identity (vendor/engine data — which die ball is which, same
status as Lattice's `device-db/` pinout tables), but there is still no
board-level mapping from a *specific populated PCB's* net/signal name to a
pin, which only a real board.toml could carry. A real Cyclone V
`boards/<name>/board.toml` would need, once a board exists:

- the `pin`/`label` -> (GPIO x, y, bi) mapping `Design.pads` already
  recovers from the bitstream (see "Pin recovery" above), carried into a
  `pins.tsv` the same shape every other family's board.toml expects.
- the usual `[board]` device/package keys plus `[bitstreams.<label>]`
  config paths, same shape as every other family's board.toml.
