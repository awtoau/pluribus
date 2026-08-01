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

## What lives here, and what points out

The rule is **not** "pluribus stores no board data" — it plainly does, and
should. Four of the five boards below keep their pinouts in this repo, tracked
in git. The distinction that matters is not *board vs engine*, it is
**shareable vs not**:

| | where it goes | why |
|---|---|---|
| **Open hardware** — Cynthion, Tang Nano, a dev board with a published schematic | **in this repo**, tracked | Ghidra ships processor definitions; a pinout for an open board is the same kind of asset. Nobody benefits from every user re-deriving it. |
| **Third-party binaries** — vendor bitstreams, firmware images | **never here** | Not ours to redistribute. `corpus/` is gitignored; the SHA-256 manifest is what is committed. |
| **Private RE work** — commercial products, anything under NDA or embargo | **out of tree**, symlinked in | The board directory is the seam. `boards/aw2-2d82auto/` does exactly this: `board.toml` is here, every artefact it names is a symlink or relative path into the owning project. |

A board directory is therefore a *config*, and whether its files are real or
symlinks is a per-board decision about disclosure — not a rule about pluribus.

### The database does not make this distinction

Any board's data can be loaded into the same database, and normally should be:
cross-board queries and shared reachability work are the point of having one.
Loading a private board's bitstream into `pluribus.db` is fine. What must not
happen is that data reaching a *public* artefact — a commit, an issue, a
released report. Keep the database local and the repo clean; they are separate
questions and only the second one is about git.

### Adding a closed board without leaking it

Put `boards/<name>/board.toml` in the repo with every path pointing out of tree,
or keep the whole directory out of tree and pass an absolute `--board` path.
Both work. Prefer the first when the *existence* of the board is not sensitive
and only its contents are, since it documents that the config exists.

## Boards

| Directory | Board | FPGA | Lifter | Status |
|-----------|-------|------|--------|--------|
| `aw2-2d82auto/` | Hantek 2D82AUTO | LCMXO2-1200HC TQFP100 | machxo2 | production |
| `cynthion-r1/` | GSG Cynthion r1.x | LFE5U-12F BG256 | ecp5 | stub — pins.tsv + ECP5 lifter pending (#9/#15) |

## Adding a new board

1. Create `boards/<name>/` with `board.toml` and `pins.tsv`
2. If the lifter doesn't exist yet, add it to `lifters/` and register it in `load.py`'s `make_lift()`
3. Run `load.py --board boards/<name> --label <label> --config <bitstream.config>`
