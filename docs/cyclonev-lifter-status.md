# Cyclone V lifter — status

> #106 (2026-10-24): LUT/FF recovery was rewritten against the Quartus post-fit oracle. The LUT5 / Q-net-only statements below describe the pre-#106 lifter and are superseded by `docs/cyclonev-postfit-oracle.md`.

First slice of a fifth pluribus family: Altera/Intel Cyclone V. Not a
Lattice-trellis family — different vendor, different fabric (ALM/LAB,
not PFU/slice). Code: `lifters/cyclonev_lift.py`. Selftest:
`scripts/cyclonev_lift_selftest.py`.

## Scope: one die, e50f (5CEBA4U19C8)

The die the Quartus corpus targets (`corpus/cyclonev/`, docs/cyclonev-postfit-oracle.md).
Validated only on corpus designs built by Quartus for this part.
`CycloneVLift.__init__` hard-rejects any other device string —
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

## Verified

- Lifter output is judged against the Quartus post-fit oracle on the corpus: `docs/cyclonev-postfit-oracle.md`.
- `scripts/cyclonev_verify_all.py` (stages 3-4) re-checks LUT/FF/net/arc/pad counts on corpus design `regbank16`; baseline in `EXPECTED_LIFTER` / `EXPECTED_PADMAP`.
- `scripts/cyclonev_lift_selftest.py <decomp.bt>` does not touch the database (see "No board").
- A route count or a "decoded" `.bt` is not a quality check: a non-Cyclone-V input also produces a large `.bt` (#114).

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

**Corpus evidence (all `corpus/cyclonev/*/decomp.bt`, Quartus-built; re-derive with the grammar notes in `cyclonev_lift.py`):**

- Pin identity is `(GPIO tile, bi)`: 179 keys, 179 pin names, no conflicts either direction.
- Ports seen carrying pin comments: DATAIN (always the arc source), DATAOUT and OEIN (always the arc sink).
- Non-GPIO pin comments are HMC only; counted and excluded.
- `i` lines carry a second ` ; ` alt-node field (7,081 of the pin-annotated `i` lines); never a second pin name.
- Not covered by the corpus (unverified): CLKIN/CLKOUT/CEIN/ACLR pin comments, multi-`pi` DATAIN taps per pin, unannotated GPIO banks, differential P/N pairing.

**Edge cases and how each is handled:**

1. **Pin identity is `(GPIO tile, bi)`, not port/pi/line-kind** (corpus evidence above).
2. **`pad_fabric_node()` builds `CVNode("GPIO", row, col, pio, port, None)`** (`pio` in the `bi` slot); a bi-less DATAIN/DATAOUT node never appears in the corpus.
3. **Direction is read from the port name**, not arc position (DATAIN = pad->fabric, DATAOUT = fabric->pad).
4. **Unannotated GPIO tiles** are kept with `pin=None`. Why Mistral's table omits a ball is unverified.
5. **Differential pairs:** one row per `(tile, bi)`; P/N pairing is open, Mistral does not tag it.
6. **`i` lines can carry a second `;`-field** (alt-node reference); `_trailing_pin()` takes only the first field.
7. **Multi-`pi` taps:** `recover_pads()` keeps the lowest `pi` as `net_in`/`net_out` and records `n_datain_taps`/`n_dataout_taps`. Behaviour unverified on the corpus.

**Schema gap — resolved, no schema.py change made:**

`pad_map.pin` is `Integer NOT NULL`; Cyclone V's recovered pin identity is a
BGA coordinate string (`"AA10"`), not a number. Decision (operator): keep
`pad_map.pin` as `Integer` for every family (no DDL change), have the
Cyclone V lifter derive a stable integer surrogate. `bga_pin_to_int()`
(`lifters/cyclonev_lift.py`) encodes `row_rank * 1000 + column_number`
(JEDEC skip-I/O/Q/S/X/Z row sequence; injective for any column under 1000). `label` carries the real BGA string and is the
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
  `lut_dependence()` directly on the recovered ALM-half cells, confirming the unified path
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

**Verified end-to-end** on a corpus design (`regbank16`):

```
python3.15t load.py --lifter cyclonev --label REGBANK16 \
    --config corpus/cyclonev/regbank16/decomp.bt --device 5CEBA4U19C8
```

Rows landed in the DB match the selftest's in-memory counts (61 LUTs, 64 FFs, 139 nets, 608 arcs, 19 pad_map rows; same counts as the `cyclonev_verify_all.py` baseline).

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

**Verified**: `verilog.py` output for corpus designs (`lifted.v`, `scripts/cyclonev_corpus_relift.py`) goes through `iverilog` with no errors.
The COMBO5 bit-select form is the common case:

```verilog
localparam [31:0] _lut_alm_lab_r10c10_a0_bottom = 32'b00000111000100000010010000000100;
assign alm_lab_r10c10_a0_bottom = _lut_alm_lab_r10c10_a0_bottom[{n17301, n17300, n17299, n17298, n17297}];
```

The structured-fn `e`-substitution and nested MUX rule are verified by the exhaustive synthetic check above, not by a corpus example.

## Regression check: zero impact on existing families

`scripts/run_pipeline.py --board boards/aw2-2d82auto --label V02` (Hantek/MachXO2) re-run after the `load.py`/`verilog.py` changes above: fabric line identical, `check_verilog.py` PASS. Current baseline: CLAUDE.md, "Scoring faults".

## No board

Per CLAUDE.md, pluribus stores no board data without a real board.toml —
none exists for any Cyclone V board, so none was added here. This is
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

## Pipeline integration (run_pipeline.py)

- `lifter = "cyclonev"` in a board.toml routes `scripts/run_pipeline.py` through: `[unpack]` -> `load` -> `reach`..`reach4` -> `auto_name` -> `patterns` -> `report` -> `chains` -> `verilog` -> `verify`. No `iomap` (pins come from the `.bt`); LEC-vs-prior is skipped (as for gowin).
- `[unpack]` = `scripts/cyclonev_unpack.py`: drops flash padding before the preamble (preamble + sync kept), validates sync/CRC16s, runs `mistral-cv decomp`, refuses to overwrite.
- `config` in `[bitstreams.<label>]` is the `.bt` (regenerable, keep under `tmp/`); `bin` is the flash image or `.rbf`.
- `pins.tsv` is optional annotation: column 1 is the BGA ball (`AA10`), cols 7/8 function/confidence, 9-11 chip_ref/chip_pin/chip_signal; applied to `pad_map` by `label == ball` (`si_function` carries `"<function> [conf N]"`).
- `scripts/cyclonev_io_report.py` dumps per-pad features (bank, ports, settings, HMC/DQS16 links, LUT-consumer counts) to a TSV.
- Output limits: `docs/cyclonev-postfit-oracle.md`.
