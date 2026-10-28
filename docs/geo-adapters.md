# Geo explorer device adapters

One module per family under `scripts/geo_devices/`; `scripts/geo_data.py` dispatches on `--family` and assembles the payload (`docs/geo-data.md`, schema 2). The page (`scripts/geo_explorer_ui/`) reads only the payload.

## Interface (module-level functions)
- `FAMILY`, `DEFAULT_DEVICE`, `DEFAULT_PACKAGE`.
- `db_path(path)` -> SQLite file holding `device_pins` (family DB, `dbtools.family_db`; `$PLURIBUS_SQLITE_PATH` / `--db` wins).
- `tiles()` -> geometry: `die, nx, ny, kinds[], tiers[], flags[]` + per-tile columns `kind, tier, cells, ver, set, flag` (index `i = x*ny + y`, y up). Optional: `bands` (frame/bit bands, Cyclone IV only).
- `pins(path, device_pkg)` -> `{device, cols, roles, rows, src}`; row layout = `PIN_COLS` (tile / pair / cell filled by `geo_data`).
- `package(rows)` -> `(package dict, grid or None, cell map)`; `package.layout` is `bga-matrix` or `perimeter`.
- `ui()` -> display hints (kind groups + colour slot, tier colour class, flag labels, role labels, design-layer label, view options).
- Optional: `pairs(rows)` (differential partners, else name-based), `image(tiles)` (Cyclone IV known-cell layer), `design(tiles)` (per-tile usage of one design), `check(payload, path)`.

## Package layouts
- `bga-matrix`: `grid` = `{letters[], cols, absent[], notes[], title}`; `pin.cell = row*cols + col`. Views: Bottom (A1 top-left), Top (mirrored). Die flip-chip option meaningful.
- `perimeter` (TQFP/QFP/QFN): `package` = `{layout, name, sides[4], per_side, n_pins, pin1}`. Numbering counter-clockwise from the top view, pin 1 at the top-left (left side top to bottom, bottom side left to right, right side bottom to top, top side right to left). `pin.cell` = position `pin number - 1`. Top view only; wire-bonded, so no flip-chip die.

## Payload schema 2 additions (schema 1 content untouched, except `package` is an object)
- `schema: 2`, `family`, `package = {name, layout, ...}` (was the string `DF31`).
- `ui`: `kind_groups[{id,label,slot}]`, `kind_group[]` (per kind), `tier_class[]` (`ver|evi|unk` per tier), `flag_labels{}`, `set_label`, `role_labels[]`, `image_label`, `design` descriptor.
- `pins.geo[]` per pin: package position numbers (4b), die-edge counts. `pins.board[]` per pin (4c, only with `--board`).
- `pattern`: per die edge pin-order statistics and per-bank table (4d).
- Optional `design`: `{label, source, cols{lut, ff, feat}}` columns of length `nx*ny` aligned to the tile index.

## Evidence tier per tile
- Cyclone IV: `tmp/geo/tiles.json` (verified / evidence / unknown).
- Others: claims of the family `provenance.db` by tile type (`tiletype:<T>` subject_key); tier names are the claim tiers present, plus `no claim`.

## MachXO2 mapping (LCMXO2-1200: 22 columns x 13 rows)
- Grid from the routing database tiles by position (`native_trellis` chip: `get_tiles_by_position(row, col)`); `x = col`, `y = max_row - row` (row 0 = top). One display kind per position, first match wins:
  - `EBR` any `EBR*` (non-CIB) tile; `HARD` `CFG*`, `GPLL*`, `DQSDLL*`, `*OSC*`; `SLICE` `PLC`; `PIO` `PIC_*` with a pad; `PIO-DUMMY` `PIC_*_DUMMY*`; `CORNER` `LLC/ULC/LRC/URC`; `CLOCK` `CENTER*`; `CIB` `CIB_*` only; `OTHER` rest.
- Pins: `device-db/MachXO2/<dev>/iodb.json` (`packages[pkg][pin] -> row, col, pio`; `pio_metadata` -> bank, function, `+/-` grouping), loaded by `scripts/pins_register_machxo2.py`. Pins absent from the IO database are inserted as `unlisted` (power / config / NC not covered by the vendored data).
- Design layer: unpacked `.config` of a lifted design (LUT INITs non-zero, FF registers configured, features per tile); labelled with its source; if none, an in-repo corpus design as a labelled example.

## Later families
- ECP5 and Gowin: tile grid from `device-db/ECP5` / the Gowin chipdb only (no pins, no design); same page.
- Evidence for the page headline numbers stays in the family DB; nothing in the payload is a source of truth.
