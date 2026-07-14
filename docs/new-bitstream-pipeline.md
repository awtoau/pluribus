# Running a new bitstream through the pipeline

How to take a raw vendor `.bin` you have never seen before and get it
unpacked, loaded, reachability-analysed, and comparable against other
bitstreams for the same board.

## Set up the board once

Everything board-specific lives in `boards/<name>/` — see
[boards/README.md](../boards/README.md).  Pluribus itself stores no board
data: `pins.tsv` / `nets.tsv` are symlinks into the RE project that owns
them, and bitstream paths in `board.toml` point there too.

```toml
[board]
name = "..."   ;  device = "LCMXO2-1200"  ;  package = "TQFP100"
lifter = "machxo2"

[files]
pins_tsv = "pins.tsv"

# Optional: declare the bitstreams you have, so run_pipeline can find
# them by label.  `bin` is only needed when `config` doesn't exist yet.
[bitstreams.<LABEL>]
bin    = "../../../<re-project>/fpga/<ver>/<name>.bin"
config = "../../tmp/<ver>/<name>.bin.config"
```

## Run it

```sh
# one bitstream
python3 scripts/run_pipeline.py --board boards/<name> --label <LABEL>

# every bitstream the board declares
python3 scripts/run_pipeline.py --board boards/<name> --all

# already loaded — start at reach
python3 scripts/run_pipeline.py --board boards/<name> --label <LABEL> --skip-load
```

Board-less form, if you have no `board.toml`:

```sh
python3 scripts/run_pipeline.py --label <LABEL> \
    --bin path/to.bin --config path/to.bin.config --pins path/to/pins.tsv
```

`run_pipeline.py` chains every stage, logs each to
`tmp/pipeline_<label>_<stage>.log`, and stops at the first failure.

## The stages

| stage  | script                      | interpreter | notes |
|--------|-----------------------------|-------------|-------|
| unpack | `scripts/trellis_unpack.py` | python3     | `.bin` → named-cell `.config`; runs only if the `.config` is absent |
| iomap  | `scripts/fpga_iomap.py`     | python3     | `.config` → `.config.iomap.tsv` (pin ↔ site map); same condition |
| load   | `load.py`                   | python3     | netlist recovery → DB rows for the label |
| reach  | `reach.py`                  | **python3.14t** | NoGIL BFS workers |
| reach2/3/4 | `reach{2,3,4}.py`       | python3     | derived analyses |
| report | `report.py`                 | python3     | summary tables |

Only `reach.py` needs python3.14t.  **Do not run `load.py` under it** —
sqlalchemy forces the GIL back on and the later pytrellis import
segfaults.

## Environment

Trellis paths come from the same env vars the lifter uses
(`lifters/machxo2_lift.py`), so set them however you already do:

```
TRELLIS_BUILD   libtrellis build dir containing pytrellis.so
TRELLIS_DBROOT  prjtrellis database root
TRELLIS_DEVICE  optional; default LCMXO2-1200
```

`--package` (or the board's `package`) pins `TRELLIS_PACKAGE` for the
iomap stage.  Pin it: best-fit package detection can drift to a larger
package than the physical part once more pads are recovered.

## Safety

- **The generators refuse to overwrite.**  `trellis_unpack.py` and
  `fpga_iomap.py` both abort rather than replace an existing output.
  Regenerating is therefore an explicit act: delete the file first.  This
  is what makes it safe to point `board.toml` at a read-only RE project —
  no pipeline run can clobber curated `.config` / `.iomap.tsv` sidecars.
- Unpack outputs for bitstreams with no committed `.config` go under
  pluribus `tmp/`, never next to the source `.bin`.
- The DB is per-label always-rebuild: loading a label deletes and
  reinserts only that label's rows.  Other labels are untouched.

## Verifying the result

1. **Load log** (`tmp/pipeline_<label>_load.log`): expect all pads
   resolved and a low `Input-pad fanout gap: N`.  That counter is a
   lifter-defect metric — see [pad-fanout-gap.md](pad-fanout-gap.md).
2. **FF D-input health**: `python3 scripts/ffd_stats.py <config>`
   classifies every FF's D-net (LUT z / FF q / routed / const) and exits
   non-zero if >10% come back constant.  This is the regression guard for
   the REG.SD polarity bug, which silently flattened FF connectivity
   while leaving every cell count and net name looking correct.
3. **Cross-bitstream diff**: `python3 scripts/compare_pads.py LABEL...`
   shows per-pin direction and stitch status across labels.  For one
   board, a pin live in one bitstream and dead in another is a lifter
   bug, never a design fact — and the union across bitstreams corroborates
   the board's pin annotation.
4. **Stranded pads**: `python3 scripts/diag_fanout_gap.py LABEL CONFIG`
   dumps the DSU class of each and resolves the keys back to bel pins.

## Pitfalls learned the hard way

- **REG.SD polarity** (fixed; see `ff_d_source()`): Trellis PLC bits.db
  makes SD value 1 the zero-state — enum *omitted* from the textcfg —
  meaning DI, i.e. the FF is packed with its slice LUT.  An explicit
  `SD 0` means the fabric-routed **M** wire.  nextpnr's machxo2
  `pack.cc` is the ground truth for the forward direction.
- The DI wire never appears in a config arc (LUT F→DI is an internal
  fixed path), so an SD=1 FF must resolve its D straight to the paired
  LUT's F key.
- Vendor bitstreams are often compressed: `trellis_unpack.py` wraps the
  raw config with an `FF 00` header before `read_bit` and relies on
  `deserialise_chip_forced` (a compressed MachXO2 config carries no
  IDCODE or frame count).
- Right/top-edge pads route via `E{N}_H06E*`-style bus names whose
  canonical must anchor at the pad's own column — see `gkey()`.
