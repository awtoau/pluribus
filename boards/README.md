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
```

## Boards

| Directory | Board | FPGA | Lifter |
|-----------|-------|------|--------|
| `aw2-2d82auto/` | Hantek 2D82AUTO | LCMXO2-1200HC TQFP100 | machxo2 |

## Adding a new board

1. Create `boards/<name>/` with `board.toml` and `pins.tsv`
2. If the lifter doesn't exist yet, add it to `lifters/` and register it in `load.py`'s `make_lift()`
3. Run `load.py --board boards/<name> --label <label> --config <bitstream.config>`
