# Geo explorer (die map + known cells + package pins + chip overlay)

One page per device (not committed, self-contained, no network): `python3.15t scripts/geo_explorer.py [--family cycloneiv|machxo2] [--device D] [--package PKG] [--board boards/<name>] [--design CONFIG] [--no-image] [--out F]`.
- Cyclone IV default: `tmp/geo/explorer.html` (~2.7 MB). MachXO2: `--family machxo2 --board boards/aw2-2d82auto --out reports/geo-explorer-machxo2.html` (gitignored; run `scripts/pins_register_machxo2.py` first). Adapters: `docs/geo-adapters.md`.
- Everything on the page (title, labels, kinds, roles, package drawing) comes from the payload; no chip is hard-coded.
- Replaces `geo_map.py`, `geo_image_overlay.py` (page part) and `geo_package.py`; one implementation of layout, panels, size, search.
- Data: single payload from `scripts/geo_data.py`, embedded once; schema and JSON export in `docs/geo-data.md`.
- UI sources: `scripts/geo_explorer_ui/` (`page.html`, `style.css`, `app.js`; JS modules: core/Store/selection, Sizer, TileView, Img, PkgView, Panels).
- Refresh after registering IO builds (`scripts/pins_register.py`): re-run `geo_explorer.py`. Image layer cache: `scripts/geo_image_overlay.py --image <image>` (heavy, `docs/geo-image-overlay.md`); `--repin` = run the explorer.

## Tabs
- Die map: colour by evidence tier / example-image set-bit density / tile kind; tile-kind filter; overlays die edge, specimen LABs, LE-output grids.
- Known cells: image layer; colour by known share / set-bit density / capacity / kind; overlay "set bits but none known". Needs the image layer (toggle `Image layer`; cache missing = tab disabled, rest works).
- Package pins: `bga-matrix` (BGA grid) or `perimeter` (TQFP/QFP/QFN: square body, pins on four sides, pin 1 dot top-left, numbered counter-clockwise, labels outside; top view only, no flip-chip). BGA: Bottom (A1 top-left) / Top (mirrored), colour by role or bank, same-bank ring, differential-pair link, die inset (top surface or flip-chip mirrored).

- Chip (overlay): one canvas, five layers with toggle + opacity each: package balls (30x30, Bottom/Top, role/bank colour, all filters), die tiles (evidence tier / set-bit density / kind), known cells (known share bars or capacity, needs the image layer), ball-to-tile links.
  - Die size is schematic: `Die scale` slider (default 45 % of the package width), not measured from the vendor drawing. Die orientation = the `Die position` switch (top surface / flip-chip mirrored); ball matrix = View (Bottom / Top).
  - Links: faint for every ball with a die site, strong for hovered / selected / searched / selected-tile pins, medium for the hovered ball's bank; none for power / ground / NC. `Bundle link lines` routes via a snapped ring around the die.
  - Hover / click picks the nearest ball, else the die tile; same cards and inspector, same shared selection.

## Layout
- >= 1100 px: three columns, no page scroll. Left: search + results, view / layer controls, pins summary, filters / legend, no-site lists. Centre: the map, sized by the available height and width (Fit = largest that fits; default = Fit); colour legend under the map. Right: hover info, pin inspector, tile inspector + bitmap, die position, notes. Each side column scrolls on its own; panels stay collapsible.
- < 1100 px: one column, map first.

## Shared
- Selection: `{tile, pin}`. Select a ball -> its die tile is ringed in both tile tabs and the inset; click a die tile -> its pins are listed in the Pin inspector and ringed on the package. Survives tab switches. Links `show on die` / `show on package` in the pin card.
- One search box (ball, vendor name, IBIS net, site substring): matches ringed in the active view and listed in `Pins`; Enter jumps (tile tabs: zoom + scroll to the first match with a die site; package: select).
- Filters (role / bank / die site, with counts) apply to every view; roles double as the legend.
- Size slider + `Fit` act on the active view (tiles 4-56 px; package / chip 30-100 %).
- Collapsible panels, open state remembered, `Expand all` / `Collapse all`. Tile inspector (die and chip tabs): tile table + class bitmap (image layer). No-site lists: `no die site yet` and `no die site expected` (see below).
- State remembered in localStorage (`geo-x:` keys: tab, options, filters, sizes, panels), all in try/catch. Selection and search are not persisted.
- Pin markers: on IO tiles by `z` (up to 4), colour = role, filled = bonded, hollow = not bonded, labels at size 32+. Conflicts in red.
- Dark/light follows the system.

## Site-expected vs not
- Rule and counts: `docs/geo-data.md`. EP4CGX150DF31: 896 / 428 with die site / 103 no site yet / 365 no site expected.

## Known gaps
- 103 expected-site balls have no die site: need a 1-LUT-per-pin build sweep, Quartus, not run.
- Registered sites are on the top row (y = 91), bottom row (y = 0) and right column (x = 117); left side is transceivers.
- 6 conflicts: AG1, AH1 (`bonded`: fit.rpt/pin say unbonded, IBIS says bonded), E1, E2, F1, F2 (`usage_default` `#TMS` vs `TMS`, naming difference).
- No unrolled die-ring view of the package page.

## Position block, labels, board names
- Every pin card starts with `Position`: perimeter `Left side, pin 8 of 25 on this side. 7 pins to the top-left corner (pin 1 side), 17 pins to the bottom-left corner. ...`; matrix `Row AB (22 of 30), column 12 (12 of 30). Along the row: 11 balls to the left edge, 18 to the right edge. ... Ring depth 8 ... Nearest corner AK1`; then the die tile line. Convention once: counts = pins (tiles) between this one and the edge, including the edge one, not this one. BGA left/right and the die line follow the View / Die position switches.
- `Label pins by`: pin number / vendor name / board name (board only with `--board`); drawn beside perimeter pins, used in tooltips and result rows. Search also matches board name, signal and net. Pin card shows Board name / signal / net / direction / note. Payload: `docs/geo-data.md`.

## Chip overlay alignment and patterns
- `Align die to package` (default on): die ring just inside the outer balls / pins, die edges face the matching package sides; `Keep die aspect` off = stretch to the pin field; `Aligned size` scales about the centre; `Die scale` applies only when unaligned.
- Die colour `I/O bank`: IO tiles take the majority bank of their pins (same palette as the pins, hatch = several banks), other tiles their kind. `Bank blocks`: dashed box round each bank's pins + thick segment on the die edge over its tile range, same colour.
- Links: bundled strands (ball -> outer lane -> inner lane at the die tile's position -> tile), ordered along the die edge so same order = parallel, reversal = crossing; links that cross others are tinted.
- Pattern panel (pkg + chip tabs): per die edge a sentence (correlation, crossings), scatter of pin position vs die tile position (hover = highlight the pin everywhere, click = select) and the per-bank table (balls, with site, die-edge tile range, package extent). Numbers are in the payload (`pattern`).
