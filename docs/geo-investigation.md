# Geo / vector / graph extensions: investigation

Question: do PostGIS, pgRouting, pgvector (and the rest of the local PostgreSQL) solve real problems for us. Research only, no conversion. Feeds #143 (PostgreSQL move) and #141. Measured 2026-10-29, EP4CGX150 data, PostgreSQL 18.6, 30-core box, scratch DB (dropped afterwards, 1.4 GB at peak). All numbers are server-side `\timing` medians unless stated.

Scripts (derived/display data only, never a source of truth): `scripts/geo_tiles.py` (tile table), `scripts/geo_bench_tiles.py` (native box / SQLite / numpy baselines), `scripts/geo_bench_ext.py --stage postgis|routing|vector` (extension benches), `scripts/geo_bench_routing.py` (plain edge table), `scripts/geo_explorer.py` (HTML map; `scripts/geo_data.py --geojson` for GeoJSON). Logs `tmp/logs/geo_*.log`, results `tmp/geo/*.json`. Earlier survey: `docs/fpga-map-tools-survey.md`.

## 1. What the server has

- PostgreSQL 18.6 (distro packages). Extensions used: postgis 3.6.4, pgrouting 3.8.0, vector (pgvector) 0.8.0.
- Also available: postgis_topology, postgis_raster, btree_gist, cube, intarray, ltree, hstore, pg_trgm, bloom, pg_stat_statements. Absent: h3, timescaledb, age.
- `CREATE EXTENSION` for postgis / pgrouting / vector needs a superuser; trusted ones (btree_gist, cube, intarray, ltree, pg_trgm, hstore) install as the DB owner.
- pgvector was not installed on this box. Nothing was removed from core. The distro repo carries `pgvector 0.8.0-2.fc44` (built for PostgreSQL 18); installed with `dnf` on 2026-10-29. A user-prefix source build is not possible without `postgresql-server-devel` and root-owned extension dirs.

## 2. Real problems today (what is awkward)

| problem | today | awkward? |
|---|---|---|
| pattern scope = union of tile rectangles / columns | python sets, `FX[x]` arithmetic | no; 10,856 tiles, one array mask |
| per-tile coverage heat map | `cycloneiv_bit_inventory.py` gives die-wide per-class totals only | yes: no tile-level join exists. Needs a per-tile attribution pass in the inventory |
| where predictions fail (spatial clustering) | 20 LAB columns with asm base != plane FX listed by hand | column anomalies are a `GROUP BY x`; 2-D clusters have no data yet |
| nearest-similar-tile for propagation | translation rule (frame = FX[x] + rel, v = 20 + 70y + rel) reproduces 240/240 pairs at 3 other LABs | no; an exact rule beats similarity |
| routing reachability / fan-out / k-hop / path | numpy CSR from `stingray4_rt_fanout.npz` | no (4.2) |
| bit-region geometry (M9K/LAB/IO rectangles in frame x v) | `cycloneiv_geom.py` band arithmetic | mildly: IO row binning approximate; a geometry type does not fix that |
| edge-tile classification | `x in (0,117) or y in (0,91)` | no |
| similarity over specimens / LUT INITs | none | not needed (4.3) |
| displaying the die | none | yes: the one real gap; section 6 |

## 3. Data used

- Tile grid: 118 x 92 = 10,856 tiles (`lifters/data/cycloneiv_ep4cgx150_geom.json`), tier from verified LUT INIT / specimen LABs, set-bit density from one third-party image.
- Routing: decoded `routing.ddb`, 1,802,443 nodes, 14,862,095 edges (unit cost).
- LUT INIT corpus: 214,669 LUT masks from 226 Quartus post-fit netlists of GX150 builds; LAB-level vectors: 119 real logic-carrying LABs from the example image + 100,000 synthetic LABs (16 INITs drawn from the real distribution), synthetic only for index latency/recall.

## 4. Measurements

### 4.1 Tile grid, 10,856 tiles (median ms)

| query | PostGIS GiST | native box GiST | PG btree | SQLite btree / R-tree | numpy |
|---|---|---|---|---|---|
| scope = union of 3 rectangles (`ST_Intersects` vs `ST_Union`) | 8.2 (5.3 as OR of envelopes) | 0.83 | | 0.14 / 0.17 | 0.04 |
| edge tiles via `ST_Intersects(tile, ST_Boundary(die))` | 11.2 | 1.19 | 1.09 (stored flag) | | 0.02 |
| edge tiles via `ST_Touches` against the inset boundary | 868 | | | | |
| 8-neighbours of 1,000 tiles | 14.6 (`ST_DWithin` 14.3) | 10.5 | 5.9 | 6.2 | 1.5 |
| column-band aggregate | 1.8 (plain `GROUP BY`) | | 2.0 | 0.46 | 0.04 |

- Answers agree everywhere (scope counts, 416 edge tiles by boundary = 416 by column rule, neighbour totals 7,895).
- ST_ functions that did something plain code does not:
  - `ST_Union` by kind returns the region topology directly: LAB 13 polygons / area 9,360, M9K 8 / 736, MUL 4 / 368, IO ring pieces. 119 ms.
  - `ST_ClusterDBSCAN` on 300 refuted-claim-style points (3 synthetic blobs + noise): 3 clusters in 5.5 ms; a 15-line numpy DBSCAN gives the same 3 clusters in 2.4 ms.
  - `ST_ConvexHull`, `ST_Area`, `ST_Buffer` for region reasoning.
  - GeoJSON export in SQL: 10,856 features, 2.5 MB, 43 ms (opens in QGIS as-is).
- PostGIS is slower than the in-process routes on this size (round trip, geometry overhead). Everything is under 15 ms except `ST_Touches` (868 ms).

### 4.2 Routing graph: 1,802,443 nodes / 14,862,095 edges

| item | pgRouting (edge table with id, source, target, cost) | plain SQL (edge table) | numpy CSR |
|---|---|---|---|
| load / build | CSV 10 s, COPY 3.5 s, 2 indexes 5.8 s, table 1,271 MB | 795 MB (2 int columns) | expand 0.46 s + CSRs 0.6 s, 148 MB |
| `pgr_dijkstra`, one pair 3 hops apart, full graph | 8.4 s per call | 1.1 ms (3-way self-join) | 0.14 ms |
| `pgr_drivingDistance` k=3 (872 nodes), full graph | 9.3 s per call | 1.2 ms (self-join) | 0.15 ms |
| same on reversed edges (fan-in cone) | 8.7 s | | |
| same on the 4-hop cone only (6,631 nodes, 66,400 edges) | dijkstra 32 ms, drivingDistance 62 ms | | |
| edge SQL restricted by index to the cone | dijkstra 39 ms | | |
| `pgr_connectedComponents` (34 components) | 8.9 s | | numpy label propagation 8.0 s (34) |
| full closure from one node (1,076,544 nodes, 16 levels) | | 4.0 s (recursive CTE) | 0.98 s |

- Results agree: dijkstra cost 3, drivingDistance k=3 returns 872 nodes (871 + start), 34 components both ways.
- Per-call graph load is the cost: every `pgr_*` call re-reads and rebuilds the graph from the edge SQL. Full graph 8.4 s versus 32 ms when the SQL passes only the cone; the algorithm itself is trivial.
- `pgr_drivingDistance` expresses fan-out/fan-in cones of depth k (unit cost) directly and returns the same node set; no use for cone queries that depend on set mux bits beyond handing it a pre-filtered edge SQL.
- pgRouting adds nothing for a static graph with k-small cones; numpy does the same queries in 0.1-1 s and holds the graph once.

### 4.3 Similarity (pgvector 0.8.0)

- Index latency/recall on 100,119 LAB vectors (256-dim), 100 queries, top-10, recall by distance-rank against the exact scan, server time per query:

  | metric / index | build | size | latency | recall@10 |
  |---|---|---|---|---|
  | exact scan, `vector` L2 / cosine, `bit` Hamming | | 119 MB table | 11.2 / 13.0 / 11.1 ms | 1.0 |
  | HNSW L2 (m=16, ef_construction=64, ef_search=100) | 32 s | 136 MB | 5.6 ms | 0.87 |
  | HNSW cosine | 29 s | 136 MB | 4.9 ms | 0.78 |
  | HNSW `bit_hamming_ops` | 8 s | 33 MB | 2.8 ms | 0.87 |
  | IVFFlat L2 (lists=316, probes=10) | 1.5 s | 118 MB | 2.3 ms | 0.58 |
  | IVFFlat cosine | 1.6 s | 118 MB | 2.8 ms | 0.53 |
  | IVFFlat `bit_hamming_ops` | 0.8 s | 6 MB | 1.6 ms | 0.49 |
  | numpy `bitwise_count` exact, in process | | | 2.3 ms | 1.0 |

  - The approximate indexes are no faster than exact numpy at this size and lose 13-50 % recall. Many synthetic vectors are near-ties, which depresses recall; the point stands for n ~ 10^5.
- Masked-bit prediction: hide the top 4 INIT bits, predict from the other 12, 2,000 test LUTs from designs unseen in training (train/test split by design). Nearest known-12 pattern (L2, cosine, L1, `bit` Hamming) vs exact dictionary lookup (with most-common fallback) vs most-common prior:

  | training set | dictionary coverage | prior | dictionary | NN accuracy (L2 / L1 / Hamming) | NN on dictionary misses |
  |---|---|---|---|---|---|
  | 107k LUTs (113 designs) | 100 % | 23.2 % | 45.6 % | 45.6 % (same) | no misses |
  | 4.2k LUTs (5 designs) | 69.9 % | 23.2 % | 41.1 % | 41.2 % | 7.0 % (prior 23 %) |
  | 909 LUTs (1 design) | 45.4 % | 23.2 % | 37.6 % | 37.6 % | 7.4 % |
  | 200 LUTs | 13.5 % | 11.0 % | 14.3 % | 15.1 % (cosine 33.2 %) | 7.6 % (cosine 28.5 %) |

  - With enough data every 12-bit pattern is present and NN equals the dictionary. Where the dictionary misses, NN is worse than the prior. The earlier +3.7 point gain was on one design's 1,534 INITs and is superseded.
  - Metric choice is irrelevant for L2/L1/Hamming on 0/1 vectors (identical rankings). Cosine differs only through the all-zero vector (undefined) and scores higher once (200 LUTs), cause not investigated; one point.
  - numpy Hamming gives identical accuracy (45.6 / 41.2 / 37.6 / 15.1 %).
- Specimen diffs (960 sets over 1,220 dims, 4 LABs): nearest neighbour by L2 or cosine shares the same source in 960/960 and the same sink in 0/960; HNSW builds. It rediscovers the known structure (bit offsets keyed by source), nothing new.
- No dense float embeddings exist in the data; pgvector's reason to exist (millions of float vectors) is absent.

### 4.4 Coverage map

- `scripts/geo_tiles.py` bins the set bits of one image to tiles and tags tier; `scripts/geo_data.py --geojson` writes `die.geojson`, `scripts/geo_explorer.py` a self-contained HTML map (`tmp/geo/explorer.html`). PostGIS reproduces the GeoJSON in SQL (43 ms) but is not needed to make it.
- Limit: per-tile verified cells are only the LUT INIT 256 cells; routing/asm per-tile attribution needs a per-tile pass in `cycloneiv_bit_inventory.py`. Row binning is approximate.

## 5. Verdict

| candidate | verdict | evidence | cost / portability |
|---|---|---|---|
| PostGIS tile geometry | display / QGIS only, optional | every tile query 0.04-15 ms by any route, PostGIS slowest (8.2 vs 0.04 ms numpy for scope); `ST_Union` region topology and SQL GeoJSON are the only extras | superuser to install; PG-only; derived layer, never source |
| pgRouting | skip | 8-9 s per call on the full graph (per-call load), 32-62 ms on a cone-only edge SQL; numpy 0.1-1 s for the same answers, one load | PG-only; 1.27 GB table; graph static; features unused (costs, topology repair) |
| plain edge table in PG | optional derived table | 14.9 M edges, 795 MB, ~15 s end to end, self-join k-hop 1-2 ms | ad-hoc SQL only |
| pgvector | skip | HNSW/IVFFlat no faster than numpy at 10^5 x 256 and 13-50 % recall loss; NN prediction = dictionary where data exist and below the prior where it does not; no float embeddings | PG-only; needs superuser install; SQLite default has no vector ops |
| bit strings / numpy Hamming | adopt in matcher code | numpy 2.3 ms vs PG exact 11 ms per query at 100k x 256; SQLite-compatible | none |
| similarity search in the DB at all | no: matcher code | prediction gain nil; specimen NN only restates source keying | none |
| H3 | skip | extension absent; square grid `(x, y)` is the index | n/a |
| ltree | skip | scope is rectangles/column sets, not a tree | n/a |
| cube / intarray / pg_trgm / hstore / bloom | skip | no query needs them | trusted, free if wanted |

## 6. Proposed design: geometry as a derived, optional layer

- Source of truth stays the generic schema (SQLite default, PostgreSQL optional). No geometry column in `schema.py`'s core tables.
- `geo` layer = generated tables built by a script from the schema + `lifters/data/<die>_geom.json`, rebuilt on demand (derived artifacts have no legacy):
  - `geo_tile(x, y, kind, tier, cells, verified_cells, set_bits, edge, geom)`; `geom` only when PostGIS is present, absent otherwise.
  - `geo_edge(src, dst)` only if ad-hoc SQL over the routing graph is wanted.
- Display path: tile table -> GeoJSON / static HTML (done). QGIS reads the GeoJSON or the PostGIS table.
- Data to add first: per-tile attribution of each bit-inventory class and per-claim tile scope (rectangles) from the provenance schema (#141), so heat maps and refuted-claim clustering have rows to draw.
- Gate for adopting an extension later: a query that is slow or unwritable without it. None found.
