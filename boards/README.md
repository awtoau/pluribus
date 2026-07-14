# Board configs

Each subdirectory is a drop-in board config for `load.py --board <path>`.

## Directory layout

```
boards/
  <board-name>/
    board.toml    required — device, package, lifter, file paths
    pins.tsv      required — pad location + direction annotations
    nets.tsv      optional — human net name annotations
```

## board.toml format

```toml
[board]
name    = "Human readable board name"
device  = "LCMXO2-1200"   # device string passed to pytrellis
package = "TQFP100"        # package string
lifter  = "machxo2"        # lifter name: machxo2 | ecp5

[files]
pins_tsv = "pins.tsv"      # relative to this board.toml
nets_tsv = "nets.tsv"      # optional

# Optional — where the RE project that owns this board keeps prjtrellis.
# scripts/run_pipeline.py exports these as TRELLIS_BUILD / TRELLIS_DBROOT
# when they are not already set, so a --board run is self-sufficient.
# An explicit environment always wins.
[trellis]
build  = "../../../<re-project>/.../libtrellis/build"
dbroot = "../../../<re-project>/.../database"

# Optional — the bitstreams you have for this board, keyed by DB label.
# `bin` is only needed while `config` does not exist yet; run_pipeline.py
# unpacks it then, and never overwrites an existing config.
#   python3 scripts/run_pipeline.py --board boards/<name> --all
[bitstreams.<LABEL>]
bin    = "../../../<re-project>/fpga/<ver>/<name>.bin"   # optional
config = "../../../<re-project>/fpga/<ver>/<name>.bin.config"
```

## Pluribus stores no board data

Every path above points *out* of pluribus, into the RE project that owns
the artefacts (`pins.tsv` and `nets.tsv` are symlinks; the rest are
relative paths).  Pluribus is the generic engine: board pinouts, vendor
bitstreams, toolchain locations and RE findings all belong to the
project, not here.  A board directory is the one place where the two
meet.

## Boards

| Directory | Board | FPGA | Lifter | Status |
|-----------|-------|------|--------|--------|
| `aw2-2d82auto/` | Hantek 2D82AUTO | LCMXO2-1200HC TQFP100 | machxo2 | production |
| `cynthion-r1/` | GSG Cynthion r1.x | LFE5U-12F BG256 | ecp5 | stub — pins.tsv + ECP5 lifter pending (#9/#15) |

## Adding a new board

1. Create `boards/<name>/` with `board.toml` and `pins.tsv`
2. If the lifter doesn't exist yet, add it to `lifters/` and register it in `load.py`'s `make_lift()`
3. Run `load.py --board boards/<name> --label <label> --config <bitstream.config>`
