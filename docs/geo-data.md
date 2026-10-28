# Geo data payload (scripts/geo_data.py)

One payload feeds every view of the explorer (`docs/geo-explorer.md`); the page embeds it once. Reusable outside the page.

- Build: `python3.15t scripts/geo_data.py [--family cycloneiv|machxo2] [--db P] [--device D] [--package PKG] [--board boards/<name>] [--design CONFIG] [--no-image]`; prints counts and layer sizes. Adapters: `docs/geo-adapters.md`.
- Export: `--export DIR` writes `payload.json` + one file per layer (`tiles.json`, `pins.json`, `grid.json`, `xref.json`, `image.json`, `geom.json`). `--geojson` writes `tmp/geo/die.geojson`.
- `check()` compares payload counts with an independent DB query (assert). Compact JSON, no paths, no network. Local copy of the sources only; nothing here is a source of truth.

## Sources (read-only; Cyclone IV, MachXO2 sources in `docs/geo-adapters.md`)
- Tiles: `tmp/geo/tiles.json` (`scripts/geo_tiles.py`).
- Pins: table `device_pins`, `databases/cycloneiv/gx150.db` (or `PLURIBUS_SQLITE_PATH` / `--db`), filled by `scripts/pins_register.py`.
- Image layer (optional): `tmp/geo/image_overlay_data.json`, written by `scripts/geo_image_overlay.py --image`. Absent -> `image: null`; the explorer works without it. Cache not matching the tile grid -> hard error.

## Schema (`schema: 2`)
Top level: `schema, family, device, package, geom, tiles, pins, grid, xref, image, ui, pattern` (+ `design` when the adapter has one).
- Schema 1 -> 2: `package` is an object `{name, layout, ...}` (was the string `DF31`); `family`, `ui`, `pattern`, `pins.geo` added. All schema-1 content is byte-identical for EP4CGX150 (canonical JSON hash compared at the refactor).
- `package.layout`: `bga-matrix` (`rows, cols, flip_chip`; `grid` present, `pin.cell = row*cols + col`) or `perimeter` (`n_pins, per_side, sides[4] = left bottom right top` in numbering order, `pin1`, `notes`; `grid` null, `pin.cell = pin number - 1`).
- `ui`: `kind_groups[{id,label,slot}]`, `kind_group[]` (per kind), `tier_class[]` (`ver|evi|unk`), `flag_labels{}`, `set_label`, `io_groups[]`, `role_labels[]`, `site_labels[3]`, `flip_chip`.
- `design`: `{label, source, cols{name: [per tile]}, names{}}`; MachXO2: LUT INITs non-zero, FF registers configured, config features set.

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

## Position numbers (`pins.geo[i]`, 4b)
- `pkg`: perimeter `{k:'p', side, i, n, around, total}`; matrix `{k:'m', r, nr, c, nc, l, rt, u, d, ring, corner, cdr, cdc}`.
- `die`: `null` or `{x, y, edge, l, r, t, b}` (tiles to the left / right / top / bottom die edge).
- Convention: counts exclude the pin (tile) itself and include the edge pin (tile); matrix counts are balls present. The UI turns the numbers into sentences and swaps left/right for the Top (mirrored) ball view and the flip-chip die.

## Board names (`pins.board[i]`, `pins.board_source`, 4c; only with `--board`)
- Source: the board's pin TSV named in `board.toml` `[files] pins_tsv` (`boards/README.md`); read-only, nothing copied into the repo.
- Columns used (header = the `# pin ...` comment line, else `pin row col pio dir label function confidence chip_ref chip_pin chip_signal net_in net_out note`): `label` -> `name` (empty, `?`, `pin<N>` = unnamed), `chip_ref.chip_signal` -> `sig`, `net_in` or `net_out` -> `net`, `dir`, `function` or `note` -> `desc`, `confidence` -> `conf`; `names` = non-empty of name, sig, net (search keys).
- Entry is `null` for pins the TSV does not list; the board must match `package`. Fixture + test: `tests/fixtures/geo_board/`, `tests/test_geo_board.py`.

## Pattern (`pattern`, 4d)
- `frame`: `{pkg, die}` orientation the numbers are in (perimeter: top view; matrix: Bottom view; die: top surface).
- `edges[]` (top bottom left right = die edge of the pin's tile): `{edge, n, rho, crossings, axis, sentence, pts[[pin, pkgCoord, dieCoord, crossings]]}`; coordinates 0..1 along the edge axis. `rho` = Spearman rank correlation (average ranks), `crossings` = pin pairs with inverted order; sentence thresholds |rho| >= 0.8.
- `banks[]`: `{bank, balls, with_site, die{edge: [lo, hi]}, pkg}` (die tile range along each edge, package extent).
- `tile_bank{tile: [bank, mixed]}`: majority bank of the pins on a tile. Unit test: `tests/test_geo_pattern.py`.
