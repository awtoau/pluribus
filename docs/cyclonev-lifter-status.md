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
- `arc_endpoint_sets`, `pad_fabric_node` (GPIO DATAIN/DATAOUT),
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
- **Pads**: `pad_fabric_node()` resolves GPIO DATAIN/DATAOUT nodes, but
  there is no board.toml for any real Cyclone V board — see "No board"
  below.

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
is explicitly out of tree — private RE work, not published). A real
Cyclone V `boards/<name>/board.toml` would need, once a board exists:

- a **package/pinout table** — pin number -> (GPIO x, y, port-index).
  Unlike the Lattice `device-db/`, no vendor pinout data for any Cyclone V
  package ships in this repo; this does not exist yet.
- the usual `[board]` device/package keys plus `[bitstreams.<label>]`
  config paths, same shape as every other family's board.toml.
