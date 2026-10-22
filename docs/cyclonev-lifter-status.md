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

- **M10K block-RAM contents, DSP block config** — Mistral itself does not
  decode these; confirmed this session. Not attempted here.
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
- Still NOT wired into `load.py`'s DB-writing pipeline (no
  `load_cyclonev()`) or `verilog.py`'s emitter (its DB query never
  selects `e`) — flagged follow-on scope. `_lut_init_to_case`
  (verilog.py) and `_evaluate_lut_init` (reach3.py) now raise loudly on
  anything but a 16-char init instead of silently truncating/misreading
  one, closing the one correctness gap those paths had for a future
  5-input caller.
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

## load.py: NOT wired up

`load.py`'s generic pipeline core (tile loops, pin TSV handling, EFB
board semantics) is still Trellis/Lattice-shaped. This lifter is not
driven through `load.py` — the selftest script calls `parse_config()` /
`recover_netlist()` directly. The LUT5 schema question above is now
settled (`luts` accepts a 5th input and a 32-char init), so writing a
`load_cyclonev()` path is no longer blocked on that — still future work,
just no longer gated on it.

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
