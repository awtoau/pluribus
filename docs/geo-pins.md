# Pin layer on the die maps

Pages: `tmp/geo/die_map.html` (`scripts/geo_map.py`) and `tmp/geo/image_overlay.html` (`scripts/geo_image_overlay.py`). Not committed.

## Data source
- Table `device_pins` in `databases/cycloneiv/gx150.db`, opened read-only with sqlite3 by `scripts/geo_pins.py` (no DDL). Filled by `scripts/pins_register.py`.
- Device `EP4CGX150DF31`: 896 balls, 892 bonded, 428 with a die site, 468 without, 6 with flagged conflicts.
- Embedded in the page as compact JSON (~120 kB): one row per ball + a deduplicated table of the per-field `source` dicts. No paths, no network.
- Counts on the page are computed from the embedded rows, not hard-coded.

## How the layer works
- Pins with a die site (`tile_x`, `tile_y`, `z`) are drawn on that tile, ordered by `z`, up to 4 per tile.
- Colour = `special` (none, config, jtag, clock, transceiver, reference, power, ground). Filled = bonded, hollow = not bonded.
- Map zoom slider (6-56). At zoom 32+ each marker gets its ball label (AB12) beside it.
- Hover an IO tile: every pin on it in the Pins card (ball, pad number, bank, side, die site + X/Y/z, I/O type, all vendor names, IBIS net, special, usage default, source fields). Click locks the tile.
- Conflicts (`conflicts` JSON) are shown in red under the pin: field + value per source.
- Search box: ball (`AB12`), vendor name (`DIFFIO_B1n`, `CLK7p`, `DATA0`), IBIS net or die-site substring. Matches on the map are ringed; Enter or a click on a result zooms to the tile (zoom >= 40, IO tiles forced visible).
- List `no die site yet (468)`: every ball with no die site (bank / side / names), filtered by the search box. Power, ground, config, JTAG and transceiver balls are in it too, so nothing is hidden. Click shows its details.
- `geo_image_overlay.py --repin` rebuilds the page from the cached `tmp/geo/image_overlay_data.json` (written by every full run), no image needed.

## Known gaps
- 468 balls without a die site: 399 have no side either (power, ground, NC, most config/reference), 49 are transceiver-side (`left`), the rest are user I/O on top/bottom/right not yet seen in a registered build (e.g. AE7 = DIFFIO_B1n / NCEO).
- Registered sites are all on the top row (y = 91), bottom row (y = 0) and the right column (x = 117); no left-column tile has a pin (left side is transceivers).
- 6 conflicts: AG1, AH1 (`bonded`: fit.rpt/pin say unbonded, IBIS says bonded), E1, E2, F1, F2 (`usage_default` `#TMS` vs `TMS` etc., a naming difference between sources).
- Side vs tile: every sited pin agrees (top = y 91, bottom = y 0, right = x 117).

## Filling the gaps
- 1-LUT-per-pin build sweep: one design per group of balls, each ball driving/reading one LUT, keep `postfit.vo` and register with `pins_register.py`.
- Needs Quartus. Not run.
- Site coverage on the maps grows with every IO build registered.
