# Geo / vector / graph extensions: investigation

Question: do PostGIS, pgRouting, pgvector (and the rest of the local PostgreSQL) solve real problems for us. Research only, no conversion. Feeds #143 (PostgreSQL move) and #141. Measured 2026-10-29, EP4CGX150 data, PostgreSQL 18.6 on a 30-core box.

Scripts (all derived/display data, never a source of truth): `scripts/geo_tiles.py`, `scripts/geo_bench_tiles.py`, `scripts/geo_bench_routing.py`, `scripts/geo_map.py`. Logs `tmp/logs/geo_*.log`, results `tmp/geo/*.json`. Scratch DB `pluribus_geo_scratch`, dropped afterwards. Earlier survey: `docs/fpga-map-tools-survey.md`.

## 1. What the server has

- PostgreSQL 18.6 (distro packages). 61 entries in `pg_available_extensions`.
- Present: postgis 3.6.4, postgis_topology, postgis_raster, pgrouting 3.8.0, btree_gist, cube, intarray, ltree, hstore, pg_trgm, bloom, pg_stat_statements.
- Absent: `vector` (pgvector), `h3`, `h3_postgis`, timescaledb, age.
- `CREATE EXTENSION` for postgis / pgrouting needs a superuser. The agent session has none; a `sudo -u postgres` attempt was refused by the permission system and not retried. Consequence: PostGIS and pgRouting calls were NOT re-measured here; prior numbers from the survey are cited and marked as such.
- Trusted extensions (btree_gist, cube, intarray, ltree, pg_trgm, hstore) install as the DB owner, no superuser.
- Other databases on the server already use postgis 3.6.3 + pgrouting 3.8.0 (two of them); none has a `vector` type.

## 2. "The vector stuff": pgvector

- Not a core removal. Core has everything it ever had: `bit(n)`, `#` (xor), `bit_count()`, arrays, `cube`.
- pgvector is not installed; no dnf transaction in the retained logs (back to 2026-10-20) mentions it.
- The distro repo does carry it: `pgvector 0.8.0-2.fc44`, source package `postgresql18-pgvector`, requires `postgresql18-server`, which the installed server provides. Install is `sudo dnf install pgvector` (root; not done).
- Source build into a user prefix is not possible: `postgresql-server-devel` is not installed, and `pg_config` is the libpq-devel one reporting 18beta1 (mismatch with 18.6). An RPM unpacked to a user prefix cannot be loaded either (the server reads extensions from root-owned dirs).
- Could not confirm the upstream "dropped in latest release" claim from local evidence; the repo still ships a PG18 build.

## 3. Real problems today (what is awkward)

| problem | today | awkward? |
|---|---|---|
| pattern scope = union of tile rectangles / columns | python sets, `FX[x]` arithmetic | no; 10,856 tiles, one array mask |
| per-tile coverage heat map | not done per tile: `cycloneiv_bit_inventory.py` gives die-wide per-class totals only (`regions` has per-tile averages) | yes: no tile-level join exists. Needs a per-tile attribution pass in the inventory |
| where predictions fail (spatial clustering) | column offsets listed by hand (20 LAB columns with asm base != plane FX) | column anomalies are a `GROUP BY x`; true 2-D clustering has no data yet |
| nearest-similar-tile for propagation | translation rule (frame = FX[x] + rel, v = 20 + 70y + rel) reproduces 240/240 pairs at 3 other LABs | no; an exact rule beats similarity |
| routing reachability / fan-out / k-hop / path | numpy CSR from `stingray4_rt_fanout.npz` | no (section 4b) |
| bit-region geometry (M9K/LAB/IO rectangles in frame x v) | `cycloneiv_geom.py`, band arithmetic | mildly: row binning of IO rows approximate; geometry type does not fix that |
| edge-tile classification | `x in (0,117) or y in (0,91)` | no |
| similarity over specimens / LUT INITs | none | not needed (section 4c) |
| displaying the die | none | yes: this is the one real gap; section 5 |

## 4. Measurements

### 4a. Tile grid, 10,856 tiles (118 x 92), median of 15 runs, client-visible ms

| query | PG GiST (box) | PG btree | SQLite btree | SQLite R-tree | numpy |
|---|---|---|---|---|---|
| scope = union of 3 rectangles | 1.02 | n/a | 0.23 | 0.27 | 0.04 |
| edge-tile count | 1.14 (column) / 1.19 (geometry) | | | | 0.02 |
| 8-neighbours of 1,000 tiles | 10.2 | 6.3 | 6.3 | | 1.5 |
| column-band aggregate | 2.3 | | 0.72 | | 0.04 |

- Native PG `box` + GiST used (PostGIS unavailable to the session). Answers agree with numpy.
- PostGIS window query, earlier survey (same kind of query, different grid): GiST 0.24-0.31 ms vs SQLite btree 1.4-2.3 ms. Both trivial.
- At this size every route is under 11 ms; index type is irrelevant. PG is slower than in-process routes because of the round trip.
- Adds that plain SQL lacks: `ST_Union/ST_Envelope/ST_ClusterDBSCAN`, line geometry for wires, QGIS-readable layers. None needed by a current query.

### 4b. Routing graph, full decoded graph: 1,802,443 nodes, 14,862,095 edges

| item | PG edge table (src, dst int + btree on each) | numpy CSR |
|---|---|---|
| build / load | CSV write 9.2 s, COPY 2.3 s, 2 indexes 3.4 s | expand 0.46 s, forward CSR 0.04 s, reverse CSR 0.57 s |
| size | 795 MB | 148 MB (fwd + rev) |
| fan-out of 1,000 nodes | 6.2 ms | 0.10 ms |
| fan-in of 1,000 nodes | 8.5 ms | 0.21 ms |
| 2-hop / 3-hop reach (85 / 871 nodes) | 1.2 / 1.8 ms (self-join) | 0.05 / 0.22 ms |
| 3-hop path to a known node | 1.1 ms | 0.13 ms |
| full closure from one node (1,076,544 nodes, 16 levels) | 4.0 s (recursive CTE) | 0.98 s |

- Counts agree between routes.
- pgRouting not measured. It reads an edge SQL per call; the survey measured 5-7 s per-call graph load at device scale. Per-call load rules it out for loops over many nets; a persistent CSR does not pay it.
- The graph is the vendor routing database, immutable per die. Mutable-graph features of pgRouting (topology repair, costs) are unused. The need is constrained search over edges whose mux bits are set, a few thousand edges per design, which numpy handles.
- Full graph fits PG without trouble (795 MB, ~9 s to load end to end). Feasible as a derived table if wanted for ad-hoc SQL; not faster.

### 4c. Similarity

- LAB LUT-INIT vectors: 256-bit per LAB (16 LEs x 16 bits), 9,360 LABs, one example design (119 LABs carry logic).
  - 100 nearest-neighbour queries, brute-force Hamming: numpy `bitwise_count` 18.7 ms; PG `bit(256)` with `bit_count(a # b)` sequential scan 59.5 ms. Same distances (sum 6140).
  - So bit strings give Hamming search in core PG with no extension; numpy is 3x faster and runs on SQLite deployments.
- LUT INIT completion test (hide 4 of 16 bits of a non-zero INIT, 2,000 samples, 760 distinct non-zero values among 1,534): Hamming NN on the 12 known bits 56.4 %; exact dictionary on the 12 known bits 52.7 %; most-common-value prior 8.3 %. NN is +3.7 points over a hash lookup. A 16-bit INIT space has 65,536 values; the lookup table is the structure.
- Specimen diffs (240 `on` sets of 4 bits each): Jaccard nearest pair shares the same source in 240/240 and the same sink in 0/240. The nearest neighbour recovers the already-known structure (src-keyed bit offsets), not a new pattern. The translation rule already covers cross-LAB.
- No dense float vectors anywhere in the data. pgvector's ANN indexes (HNSW/IVFFlat) address millions of float embeddings; our sets are bit vectors of thousands of rows.

### 4d. Coverage map

- `scripts/geo_tiles.py` bins the set bits of one third-party image to tiles and tags tier (verified LUT INIT, evidence specimen LAB, unknown); `scripts/geo_map.py` writes `die.geojson` + a self-contained HTML map (`tmp/geo/die_map.html`). No PostGIS needed: the page is generated from the tile table.
- Limit: per-tile verified cells are only the LUT INIT 256 cells; routing/asm per-tile attribution needs a per-tile pass in `cycloneiv_bit_inventory.py` (today it totals per class). Row binning is approximate (`ROW_PHASE0`).

## 5. Verdict

| candidate | verdict | evidence | cost / portability |
|---|---|---|---|
| PostGIS tile geometry | use for display only (optional) | all tile queries 0.04-11 ms by any route; only new capability is QGIS-readable layers and `ST_Union/Cluster` | extension needs superuser; PG-only; SQLite loses it. Generate from tables, never source |
| pgRouting | skip | not measurable here; per-call load 5-7 s (survey); fan-out/k-hop/closure 0.1-1 s in numpy vs 6 ms-4 s in SQL | PG-only; duplicates 795 MB of edges; graph immutable |
| Plain edge table in PG | optional | 15 M edges loads in ~9 s, 795 MB, ad-hoc SQL fine | derived table only |
| pgvector | skip for now | not installed (distro package exists, root install); Hamming search already in core (`bit_count`); data are bit sets, not float embeddings | PG-only; matcher belongs in code |
| bit strings / numpy Hamming | adopt in the matcher (code) | 18.7 ms vs 59.5 ms per 100 queries; SQLite-compatible | none |
| similarity search in the DB at all | no: matcher code (numpy) | NN gain +3.7 points over a dictionary; nearest specimen reproduces known src structure | SQLite default has no vector ops |
| H3 | skip | extension absent; square die grid, `(x, y)` is the index | n/a |
| ltree | skip | scope is rectangles/column sets, not a tree; JSON scope tags suffice | n/a |
| cube / intarray / pg_trgm / hstore / bloom | skip | no query needs them | trusted extensions, free if wanted |

## 6. Proposed design: geometry as a derived, optional layer

- Source of truth stays the generic schema (SQLite default, PostgreSQL optional). No geometry column in `schema.py`'s core tables.
- `geo` layer = generated tables built by a script from the schema + `lifters/data/<die>_geom.json`, rebuilt on demand (derived artifacts have no legacy; rebuild is the migration):
  - `geo_tile(x, y, kind, tier, cells, verified_cells, set_bits, edge, bx)`; with PostGIS present `bx` is a `geometry` + GiST, without it a native `box` or no column.
  - `geo_edge(src, dst)` only if ad-hoc SQL over the routing graph is wanted.
- Display path: tile table -> GeoJSON / static HTML (done: `scripts/geo_map.py`). QGIS optional on top of PostGIS if Dan wants it.
- Data to add before the map is useful: per-tile attribution of each bit-inventory class and per-claim tile scope (rectangle list) from the provenance schema (#141), so heat maps and refuted-claim clustering have rows to draw.
- Gate for adopting PostGIS later: a query that is slow or unwritable without it. None found.
- Install requests (root, outside agent scope): `CREATE EXTENSION postgis, pgrouting` in a scratch DB to re-measure; `dnf install pgvector` only if a float-vector use appears.
