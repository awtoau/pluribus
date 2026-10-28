# Geo data payload (scripts/geo_data.py)

One payload feeds every view of the explorer (`docs/geo-explorer.md`); the page embeds it once. Reusable outside the page.

- Build: `python3.15t scripts/geo_data.py [--db P] [--device EP4CGX150] [--package DF31] [--no-image]`; prints counts and layer sizes.
- Export: `--export DIR` writes `payload.json` + one file per layer (`tiles.json`, `pins.json`, `grid.json`, `xref.json`, `image.json`, `geom.json`). `--geojson` writes `tmp/geo/die.geojson`.
- `check()` compares payload counts with an independent DB query (assert). Compact JSON, no paths, no network. Local copy of the sources only; nothing here is a source of truth.

## Sources (read-only)
- Tiles: `tmp/geo/tiles.json` (`scripts/geo_tiles.py`).
- Pins: table `device_pins`, `databases/cycloneiv/gx150.db` (or `PLURIBUS_SQLITE_PATH` / `--db`), filled by `scripts/pins_register.py`.
- Image layer (optional): `tmp/geo/image_overlay_data.json`, written by `scripts/geo_image_overlay.py --image`. Absent -> `image: null`; the explorer works without it. Cache not matching the tile grid -> hard error.

## Schema (`schema: 1`)
Top level: `schema, device, package, geom, tiles, pins, grid, xref, image`.

- `geom`: `vpitch` 70, `vband_lo` 48. Tile row band is v in [70 y - 48, 70 y + 21].
- `tiles`: `die, nx, ny, kinds[6], tiers[3], flags[3]` + columns, each of length `nx*ny`.
  - Tile index `i = x*ny + y` (complete grid, checked). `x = i // ny`, `y = i % ny`.
  - Columns: `kind` (index into `kinds`: LAB M9K MUL IOL IOR IOROW), `tier` (verified / evidence / unknown), `cells` (cells in the tile band), `ver` (verified cells), `set` (set bits of one example design), `flag` (bit 0 die edge, bit 1 specimen LAB, bit 2 LE-output grid).
- `pins`: `device, cols[], roles[9], rows[], src[]`.
  - Row = list in `cols` order: `ball, pad, bank, side, x, y, z, site, type, names[], ibis, role, bonded, usage, src, conflicts[], expected, tile, pair, cell`.
  - `role` indexes `roles` (none config jtag clock transceiver reference power ground nc). `src` indexes `pins.src` (deduplicated per-field source dicts). `expected` = die site expected (0 for power / ground / nc, see below).
  - Cross references: `tile` = tile index of the die site or -1; `pair` = differential partner pin index or -1; `cell` = matrix index `row*grid.cols + col` of the ball.
  - Site classes derived from a row: `x != null` with site; `x == null && expected` no site yet; `x == null && !expected` no site expected.
- `grid`: `letters[]` (row letters present), `cols`, `absent[]` (matrix positions with no pin row), `notes[]`, `title`.
- `xref.tile_pins`: `{tileIndex: [pin index...]}` sorted by `z`, ball. Pin -> tile is the row's `tile` field.
- `image` (or null): `label, cols[], cls[], C, S, tp` + one column per `cols` entry, each of length `nx*ny` aligned to the tile index.
  - Columns: `cells` (cells owned by the tile), `set` (set bits), `sv se su so` (set bits in verified / evidence / unknown / overhead classes), `capv cape` (verified / evidence capacity), `s2a` (routing cells fired), `fa` (first frame of the tile rectangle), `w` (frames wide), `tmpl` (class template index).
  - `cls`: `[id, tier letter V/E/U/O, name]` per class (class number = position + 1). `tp`: `[offset, length]` per template into `C`.
  - `C` = class templates (one byte per cell, `w x 70`, column-major) and `S` = set bits packed per tile (`ceil(w*70/8)` bytes each, tile-index order); both raw-deflate + base64.

## Site-expected rule
- Role = DB `special`, except a ball whose only vendor names are `NC`/`DNU` -> `nc` (the DB has no NC special).
- Not expected: power, ground, nc (package-only, no I/O cell). Expected: user I/O, clock, reference, configuration, JTAG, transceiver.
- EP4CGX150DF31: 896 balls / 428 with die site / 103 no site yet / 365 no site expected (363 power+ground, 2 NC).
