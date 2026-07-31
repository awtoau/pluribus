# Why `device-db/` exists, and what these two files are

Retired 2026-07-31, when pluribus vendored the device (tile) database into
`device-db/` instead of pointing at somebody else's copy.

## What went wrong

The tile database was external, and two copies had drifted apart:

| | prjtrellis checkout, Jun 2026 | oss-cad-suite, shipped Feb 2025 |
|---|---|---|
| used by | one board pipeline, via a `[trellis]` override in `board.toml` | the fuzz corpus, the tests, everything else |
| `PLC/bits.db` | identical | identical |
| `CIB_EBR1`, `CIB_EBR2`, `CIB_EBR_DUMMY`, `GPLL_L0`, `PIC_B_DUMMY_VIQ{,_VREF}` | **richer** (e.g. carries `EBR.OCEAMUX`) | missing that content |

Every difference was content the June tree had and the other lacked — a strict
superset, never a conflict. But the board that used the override also uses
`CIB_EBR1` and `CIB_EBR2` tiles, so **the corpus result and that board's result
were never comparable**, and nothing in the repo said so.

The June copy also lived under the owning project's `debris/` — the archive for
retired content — so a live dependency was being served out of a wastebasket.

## The hand edit (these two files)

Both trees carried an out-of-band edit to `MachXO2/tiledata/EBR1/bits.db`: the
issue-#29 `EBR.MODE` correction, keying the mode select on `F1B33 F1B34` instead
of upstream's `F1B35`. The only surviving pristine copy was a `bits.db.orig`
backup left beside it.

That edit was **redundant** — `scripts/db_overrides.py` already carries exactly
the same correction and `native_tile_decode` applies it at decode time. Its own
docstring says why it exists:

> Rather than hand-edit that database — which is outside pluribus's scope and
> would be lost on any re-clone/rebuild — pluribus carries the corrections here.

So the edit bought nothing and would have been silently destroyed by the first
database rebuild. `device-db/` is therefore vendored **pristine**, with `EBR1`
restored from the `.orig`, and the correction left where it belongs.

Kept here because neither file is regenerable from the current tree: one is the
pre-edit upstream, the other the edited version, and together they are the only
record of what was changed and why it was safe to drop.

- `EBR1-bits.db-upstream-pristine-F1B35.txt` — upstream, now in `device-db/`
- `EBR1-bits.db-handedited-F1B33-F1B34.txt` — the hand-edited version, retired

## The rule that allowed this

`CLAUDE.md` said pluribus is board-agnostic and stores no board data, and that
got applied to the tile database. It is a category error: what bit `F25B0` means
in a `CIB_EBR1` tile is a property of the **silicon**, identical for every board
using that part. That is engine data, like `schema.py`. Board data is pins, nets,
register maps, bitstreams — and that rule still stands.
