# Pin layer on the die maps + package view

Pages (all under `tmp/geo/`, not committed):
- `die_map.html` - `scripts/geo_map.py`
- `image_overlay.html` - `scripts/geo_image_overlay.py` (`--repin` rebuilds from cached `image_overlay_data.json`)
- `package_map.html` - `scripts/geo_package.py [--db P] [--device EP4CGX150] [--package DF31]`

## Data source
- Table `device_pins` in `databases/cycloneiv/gx150.db`, read-only sqlite3 via `scripts/geo_pins.py` (no DDL). Filled by `scripts/pins_register.py`; re-run it after registering IO builds, then regenerate the pages (`geo_map.py`, `geo_image_overlay.py --repin`, `geo_package.py`).
- Embedded as compact JSON (~100 kB): one row per ball + deduplicated per-field `source` dicts. No paths, no network. Page counts are computed from the rows; `geo_package.py` asserts them against an independent DB query.

## Site-expected vs not (classified in `geo_pins.py`, DB unchanged)
- Role = DB `special`, except a ball whose only vendor names are `NC`/`DNU` -> `nc` (`NC_NAMES`, `role_of`).
- Not expected (`NO_SITE_ROLES`): power, ground, nc. Package-only balls, no I/O cell on the die.
- Expected: user I/O, clock, reference, configuration, JTAG, transceiver. These are pads; no site = not yet seen in a registered build.
- Counts split as total / with die site / no site yet / no site expected. EP4CGX150DF31: 896 / 428 / 103 / 365 (363 power+ground, 2 NC).
- Row field 16 = site expected (0/1); lists `no die site yet` and `no die site expected` are separate panels.

## Die maps
- Pins with a site are drawn on their tile (by `z`, up to 4). Colour = role; filled = bonded, hollow = not bonded. Labels at map size 32+.
- Search: ball, vendor name, IBIS net, site substring; Enter / click jumps to the tile.
- Conflicts shown in red (field + value per source).

## Layout (all pages)
- Graphic left, centred; default size ~58 % of fit-to-window. `Size` slider + `Fit` button (full window); value in localStorage (try/catch; works without).
- Everything else in the right column as collapsible panels; open state remembered per panel; `Expand all` / `Collapse all`. Column is sticky with its own scroll >= 900 px, stacks below the map narrower.
- Overlay page: tile inspector + bitmap panel (open), bitmap legend/options (closed).

## Package view (`geo_package.py`)
- Grid derived from ball names: 30 rows (A..AK) x 30 columns. Letters omitted: I, O, Q, S, X, Z and AI. Corners A1, A30, AK1, AK30 have no row in the table (drawn dashed, "no pin in table").
- View switch: Bottom (ball side, A1 top-left, default) / Top (mirrored left-right, not rotated, A1 top-right). Selection, filters, search and highlights persist across the switch; choice in localStorage.
- Colour by role or I/O bank; role / bank / site-status filters with counts.
- Hover = card in the right column + short tooltip; click or tap selects. Card: ball, pad, bank, side, die site, I/O type, all vendor names, IBIS net, special, usage default, source fields, conflicts (red).
- Hovered/selected ball: same-bank balls ringed; differential pair partner (vendor names ending p/n after a digit or `_`, both present) linked.
- Die inset: tile marked when a site exists, else the side edge. Orientation: top surface (as the die map) or mirrored bottom (flip-chip bumps side).

## Known gaps
- 103 expected-site balls have no die site: need a 1-LUT-per-pin build sweep, Quartus, not run.
- Registered sites are on the top row (y = 91), bottom row (y = 0) and right column (x = 117); left side is transceivers.
- 6 conflicts: AG1, AH1 (`bonded`: fit.rpt/pin say unbonded, IBIS says bonded), E1, E2, F1, F2 (`usage_default` `#TMS` vs `TMS`, naming difference).
- No unrolled die-ring view of the package page.
