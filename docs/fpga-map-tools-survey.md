# FPGA map tools survey — vendor dumps + GIS/graph tools

- Date: 2026-10-23. Host: Quartus Prime Lite 25.1std.0 b1129, Diamond 3.14 (licence expired), PostgreSQL 18.6, PostGIS 3.6.4, pgRouting 3.8.0, python3.15t (3.15.0 free-threaded).
- Tags: **[V]** = verified (ran it / read the source). **[I]** = inferred from evidence. **[U]** = unverified (memory / not tested).
- Scratch scripts: `tmp/survey/*.py|*.tcl|*.sql`. Large outputs deleted (regenerable). Scratch DB `bluebird_scratch` created and **dropped**.

## Ranked next steps

1. **Quartus RCF as the Cyclone V routing oracle (and possibly a routing *driver*).** `quartus_cdb <proj> -c <rev> --back_annotate=routing` writes `<rev>.rcf`: every net's full routing tree, all fanout branches, clock network included, in `TYPE:XxYyS<n>I<idx>` names. Replaces `report_timing -show_routing` (timing-path-limited) for route_hops. Then test the reverse: hand-edit an RCF hop, refit, diff bitstreams = directed routing fuzzing (prjxray-style). [V for export; U for import]
2. **Decode Quartus `ddb_cyclonev_e50f_{routing,asm,icname}.ddb`.** They are plain zlib after a 0x73-byte header; 99.4% inflates with stock `zlib`. `icname` = 865k readable wire names; `routing` = 40 MB graph; `asm` = 268 MB numeric (likely the CRAM bit map). This is Intel's own map — a decode beats fuzzing and gives an independent check on Mistral. [V inflate; I content]
3. **Dump the MachXO2 vendor routing graph with Diamond `ispTcl`** (`dev_list_node_at_location`, `dev_list_arc_by_node_name`). Works with the expired licence. Full wire + arc list per tile from Lattice; cross-check `device-db/` and every `gkey()` workaround in `lifters/machxo2_lift.py`. [V]
4. **PostGIS as a Postgres-only spatial/graph layer over portable core tables** (not a full move yet). Keep pathfinding in-process (CSR arrays under 3.15t); use PostGIS for window/coverage queries and QGIS viewing. Fix first: pg8000 not installed for system python3.15t. [V]
5. **Build the Cyclone V routing graph from (2)/(1), not from Mistral**; load into the layer from (4); route reconstruction = BFS constrained by set-mux bits. [I]

Most important Part A finding: **Quartus ships its own Cyclone V routing/assembler database as zlib-compressed `.ddb` files, and `--back_annotate=routing` exports complete per-net routing trees.** Together they're a vendor-sourced route to the map that doesn't need Mistral.

## Part A — vendor maps

### A1 Quartus / Cyclone V

**Device data files** [V]
- `quartus/common/devinfo/cyclonev/` = 1.4 GB; `cyclonev_e50f/` = 64 MB.
- Key e50f files (size on disk → inflated, header u64 @0x4f):
  - `ddb_cyclonev_e50f_routing.ddb` 3.3 MB → 40,051,724 B
  - `ddb_cyclonev_e50f_asm.ddb` 5.2 MB → 268,169,394 B (no strings; numeric tables)
  - `ddb_cyclonev_e50f_icname.ddb` 2.5 MB → 17,981,908 B
  - `ddb_cyclonev_e50f_place.ddb` 125 KB → 3,246,003 B
  - `ddb_cyclonev_e50f_timing.ddb` 644 KB → 11,989,346 B
  - also `_asmdb.ddb`, `_asmdb_dirt.ddb` (different layout, no zlib at 0x73), `_pad`, `_hdr`, `*_pkg`, `*.dmf.ddb` / `*_fdi.ddb` (per speed/temp corner), `zb{8,16}_mtm_cff_mapping.csv.enc` (zlib after an 8-byte header, plain CSV of named periphery bits: docs/altera/cycloneV/cyclonev-vendor-data.md)
- Header: `u32 0x14`, `u32 0x10bad`, version string `Version 25.1std.0 Build 1129 ... SC Standard Edition`, then u64 inflated size, u64 compressed size, zlib stream at 0x73 (`78 01`).
- Inflate: stock `zlib` gets ~99.4–99.95% then `invalid stored block lengths` near the end. Probably a second chunk or trailer; not chased. Script: `tmp/survey/ddb_inflate.py`, `ddb_probe.py`.
- Contents (string histogram, `tmp/survey/ddb_strings.py`):
  - `icname`: 865,206 names, e.g. `H#R#C#LT[#]`, `V#R#C#UP[#]`, `LIM#R#C#`, `CLKLIMR#C#CS#RT[#]`, `VIOR#C#I[#]`: interconnect wire names per row/column.
  - `routing`: port names (`BUFFER_IN/OUT`, HSSI/HMC/DQ ports, `GCLKMUXSEL#_RE`): block-port ↔ routing table plus binary graph.
  - `asm`: zero strings: numeric, consistent with a mux→CRAM-bit table [I].
  - `place`: `CLKCTRL_R#`, `QCLK_CLKBUF_*`, port names: placement db (Mistral's 2020 notes decode its C++ struct `DYGR_PLACE_INFO_BODY`: block list, nx/ny, per-location properties).
- `devinfo/device.db` (5.7 MB) is SQLite: part catalogue + resource counts (base64-obfuscated names), **no routing**. [V]

**Quartus Tcl** [V]
- `quartus_sh --tcl_eval help` packages: device, misc, project, qshm (+ flow, report, names, design, ...). `::quartus::device` = part list/info only.
- `quartus_cdb` adds `::quartus::chip_planner` and `::quartus::backannotate`. No `advanced_device` in Lite 25.1.
- `chip_planner`: `read_netlist`, `get_nodes -type all|lcell|io|pll|dsp|ram`, `get_node_info`, `get_iports`, `routing_path -node N -port_id P [-table] [-file]`. Design-netlist only (used nodes), not the device graph.
  - `read_netlist` + `get_nodes -type lcell` worked (`tmp/survey/cp_probe.tcl`).
  - `get_node_info -info location` → `info value "location" is not valid`.
  - `routing_path -node 0 -port_id 1` → **Quartus internal error, reproducible** (`HDB hdb_namespace.cpp:253` in `ADB_CDB_INTERFACE_BODY_IMPL::dump_routing_path`). Unusable in 25.1 Lite.
- `--vqm=out.vqm --write_rcf_for_vqm=on` → wrote the VQM, **no RCF**.
- **`quartus_cdb <proj> -c <rev> --back_annotate=routing --write_settings_files=on` → `Generated Routing Constraints File build.rcf`** (adder12: 77 nets, 869 lines, <1 s). Sample:
  ```
  signal_name = s[0]~reg0 {
      LE_BUFFER:X43Y44S0I0; R6:X38Y44S0I33; R14_C12_INTERCONNECT_DRIVER:X43Y44S0I1; R14:X30Y44S0I1;
      C2:X35Y45S0I11; LOCAL_INTERCONNECT:X36Y45S0I30; BLOCK_INPUT_MUX_PASSTHROUGH:X36Y45S0I44; ...
      dest = ( s[0]~output, I );
  }
  signal_name = clk~inputCLKENA0 { ... GLOBAL_CLOCK:X0Y22S0I10; SPINE_CLOCK:X39Y23S0I11; ... LAB_CLK ...
      label = Label_LAB_INPUT:X43Y44S0I0, LAB_INPUT:X43Y44S0I0;  dest = ( s[0]~reg0, CLK );
      branch_point = Label_LAB_INPUT:X43Y44S0I0;  dest = ( s[1]~reg0, CLK ); ...
  ```
  - Complete trees with `label`/`branch_point` fan-out: covers what `report_timing` misses (non-critical nets, every sink).
  - Same element types as `route_hops` (`R6`, `C2`, `LOCAL_INTERCONNECT`, `LE_BUFFER`...), so it joins the existing corpus.
  - Run on a copy (`tmp/survey/adder12_q`): it rewrites the `.qsf`.
  - **RCF as input** (`ROUTING_BACKANNOTATION_FILE`-style constraint → fitter honours hand-edited routes) **not tested** [U]. If it works, it is the directed-routing fuzzer.
- QUIP (Quartus University Interface Program): not shipped with 25.1. Historically a separate academic download (VQM I/O, timing/arch docs for Stratix-era parts) used with VPR/Titan; VTR's Stratix IV arch was hand-captured, not exported. No evidence it ever exported a Cyclone V routing graph. [U]

**How Mistral got its data** [V history, I conclusion]
- 2019 (Ravenslofty): fuzzing. `fuzz/bash/00-tilegrid`, `rbf-utils/horrortable.rs` (8 LUT-mask patterns, diff `.rbf`), LABCELL csv.
- 2020-03: `docs/quartus/DYGR_PLACE_INFO_BODY.cpp`: a reconstructed Quartus internal C++ struct (placement db), plus `ddb-utils/` (pruned 2020-12-28). They were reading Quartus internals.
- 2020-12-25 (Galibert) "Initial public version of the generator": drops complete `data/<die>-r.txt` (every routing mux, bit-pattern id, CRAM position, all inputs) for **all 7 dies** in one commit; README: "a lot of things that can be done to help without having to look inside quartus".
- Conclusion [I]: the routing mux tables were extracted from Quartus's device database, not fuzzed. No source for the extractor is in the repo. Docs (`cyclonev_library_internals.rst`, readthedocs) describe the format, not the provenance.
- Format (`e50f-r.txt.xz`): `DST mux_pattern:bitpos src0:… src1:…`. Full e50f graph: **695,446 muxes, 838,298 rnodes, 11,878,060 edges**; rnode types GIN (block out → routing), GOUT (routing → block in), TD, LD, H3/H6/H14, V2/V4/V12, WM, clocks. [V] (`tmp/survey/mistral_graph_size.py`)
- Implication: since #103 confirmed Mistral errors, decoding the `.ddb` ourselves gives a vendor-sourced replacement and a way to find *which* Mistral tables are wrong (extraction bug vs Quartus-version drift).

### A2 Lattice / MachXO2

- **#93 `bstool`** [V, from issue]: dumps the vendor BFD (tile → bit map) as ASCII: per tile type rows/cols, sites, node table. ECP5: 198 tile types vs trellis 185, trellis a strict subset. Also `.con` (package/IO topology, plain text), `.tac` (primitive schema), `.spd` (timing, ps×1024). Same tools exist for MachXO2 (`ispfpga/xo2c00/data/xo2c00.bfd` 23 MB, `xo2c256/640/....grf/.hrg/.nph`). MachXO2 BFD dump not yet run [U].
- **#105 `ncd2nmc -r`**: per-net routing hops from an NCD (design-level oracle).
- **New: `ispTcl` device graph** [V]: `ispfpga/userware/unix/bin/lin64/ispTcl` + `data/tcltool/IspTcl{Dev,Cmd}.tcl`, after `des_read_ncd/des_read_prf` on any LCMXO2-1200 NCD:
  - `dev_list_node_at_location -row 5 -col 5` → every wire touching R5C5 with class (`LOCAL`, `BY1_0`, `BY2`, `BY6`) and id (`R5C6_H02E0001`, `R3C5_V06N0302`, ...).
  - `dev_list_arc_by_node_name -to R5C5_A0 -num 100000` / `-from R5C5_F0` → all PIPs (`R5C4_H02E0501 --> R5C5_A0`, `R5C5_F0 --> R5C8_H06E0003`).
  - Names are prjtrellis-style → direct diff against `device-db/MachXO2`. Script `tmp/survey/isptcl_probe.py`.
  - prjtrellis built its routing graph exactly this way (`util/common/isptcl.py`; notes a Tcl memory leak, batches nodes) [V source].
- `arcdump -ncd <ncd> -n` → 85,195 routing nodes for LCMXO2-1200 with speed class + arc count, no names; `-a`, `-ac`, `-nc` segfault; `-sn` lists 2,718 speed/timing class names. Low value beyond ispTcl. [V]
- `bstool -t` → tilegrid (prjtrellis `tools/extract_tilegrid.py`) [V source].

### A3 Prior art

| project | routing graph | bit meanings | vendor-extracted? |
|---|---|---|---|
| prjtrellis (ECP5/MachXO2) | Diamond `ispTcl` `dev_list_*` [V src] | fuzzing NCL→bitstream diffs | graph + tilegrid yes (ispTcl, `bstool -t`); bits fuzzed |
| Project X-Ray (7-series) | Vivado Tcl `get_tiles/get_wires/get_pips/get_nodes` [U] | fuzzing + `segmatch` (correlate bit sets vs feature sets across many specimens) [U] | graph yes; bits fuzzed |
| prjoxide (Nexus) | Radiant's Tcl/dev API, same family as ispTcl [U] | fuzzing | graph yes [U] |
| apicula (Gowin) | parses vendor `.fse` (fuse tables) and `.dat` directly (`apycula/fse_parser.py`, `dat_parser.py`, `chipdb.py` "table 'alonenode[6]' in the vendor file") [V src] | mostly from `.fse` + fuzz confirmation | yes, heavily |
| icestorm (iCE40) | fuzzing iCEcube2 + its text outputs [U] | fuzzing | mostly fuzzed [U] |
| Mistral (Cyclone V) | Quartus db extraction [I] | same | yes [I] |

- Transfers to Cyclone V:
  - apicula / Mistral model: decode the vendor binary db (`.ddb` here). Highest yield.
  - prjxray `segmatch`: works on our corpus once the RCF gives "feature = this mux used" per design. Specimens with varied routing then correlate features with CRAM bits.
  - prjtrellis / prjxray "ask the tool for the graph": Quartus has no device-graph Tcl in Lite (only design-level `chip_planner`, and that crashes). The `.ddb` is the substitute.

## Part B — GIS / graph tools

### Installed / works under python3.15t [V]

| item | state |
|---|---|
| PostgreSQL 18.6 + PostGIS 3.6.4 + pgRouting 3.8.0 | installed; `CREATE EXTENSION` needs superuser (`sudo -n -u postgres` worked) |
| pg8000 | **not installed for system python3.15t** (`ModuleNotFoundError`); pluribus postgres backend can't run there today. Scratch venv: `import pg8000.native` → GIL False |
| SQLAlchemy 2.1.4 + pg8000 → PostGIS query | GIL False (scratch venv) |
| networkx | pure Python, GIL False |
| shapely 2.2.0 (cp315t wheel) | GIL False |
| rustworkx, python-igraph | **no cp315t wheel** (`pip --only-binary` fails) |
| SQLite R-tree | compiled in; works from python3.15t |
| SpatiaLite (`mod_spatialite.so` 5.1.0) | on disk, but python3.15t `sqlite3` built **without `enable_load_extension`** → unusable from the pipeline |
| QGIS, GDAL/ogr2ogr, Neo4j | not installed |

### Prototype results [V] (`tmp/survey/pgis_proto.py`, `full_graph*.sql`, `csr_bfs.py`, log `tmp/logs/pgis_proto.log`)

- **Corpus-scale** (`corpus/cyclonev/corpus.db`: 91,933 RE/IC/CELL hops → 4,410 elements, 9,150 directed edges, 1 weak component). Load via pg8000 row-at-a-time: 2.5 s.
  - Window (tiles X30–45, Y40–45, count elements by kind): PostGIS GiST `&&` **0.24–0.31 ms**; SQLite btree (x,y) on `route_hops` 1.4–2.3 ms; SQLite R-tree join 1.6–2.4 ms. Same answers. All trivial at this size.
  - Path `IO_INPUT_BUFFER_OUTPUT_X54_Y18_N61_I2 → PIN_N6`: `pgr_dijkstra` 7.0 ms (bbox-pruned edge SQL 3.8 ms); networkx in-memory 0.41 ms. Gotcha: pgr_dijkstra needs `::bigint` casts on ids (otherwise "function is not unique").
  - Caveat: hops from timing paths include cell arcs (`LABCELL → LE_BUFFER`), so the path walks *through* logic. Routing-only searches must drop CELL/IC edges.
- **Full-device scale** (Mistral e50f graph: 838,298 nodes, 11,878,060 edges):
  - `\copy` load: edges 16.4 s, nodes 1.1 s; indexes ~8 s; `medge` = 1,210 MB.
  - Window query on full node set: 15.7 ms.
  - `pgr_dijkstra GIN.010.010.0019 → GOUT.040.035.0000`: **4.8–7.1 s per query** (rebuilds the graph from the edge SQL every call; bbox pruning doesn't help because the join costs as much as the load). `pgr_bdDijkstra` ~4.8 s. Path 13 edges.
  - Same query, in-process CSR (`array` module, python3.15t, GIL off): build 10.6 s, RSS 336 MB, **BFS 370–440 ms**, 13 edges (equal-length alternative path).
  - Gotcha: Mistral direction is GIN (block output → routing) → GOUT (routing → block input); GOUT has no out-edges.

### Fit per use case

| use | best fit | notes |
|---|---|---|
| route reconstruction (set mux bits + endpoints + partial hops) | **in-process CSR/BFS in python3.15t**, edges filtered to "bit set" muxes | constrained search is cheaper still: only edges whose mux bits are set, so a few k edges per design. pgRouting's per-call graph load (5–7 s at device scale) rules it out for many-net loops. networkx fine at corpus scale, too heavy (GBs) at 12M edges [I]. rustworkx/igraph would be faster but have no 3.15t wheels |
| spatial queries, coverage maps | **PostGIS** (GiST) or SQLite R-tree | both fast; PostGIS adds `ST_Envelope/ST_Union/ST_ClusterDBSCAN`, heatmap aggregation, line geometry for wires. SQLite R-tree is enough for pure rectangle windows and stays serverless |
| die visualisation for humans | **QGIS on PostGIS** (not installed) or generated SVG/HTML | PostGIS tables are QGIS layers directly (points = elements, lines = wire spans, polygons = tiles; style by "used/unknown bit"). Without QGIS: an SVG/HTML from Python is enough and has no install |
| subgraph / pattern matching (#104) | networkx `isomorphism` (VF2) at corpus scale; SQL recursive CTEs for fixed small motifs | Neo4j/Cypher would fit pattern queries, but it's a JVM server outside the SQLite/pg8000 rules. Not recommended |

### PostGIS within pluribus's backend rules

- Constraints: `db.py` has exactly 3 public functions; pg8000 the only PG driver; `schema.py` owns DDL with portable SQLAlchemy Core (JSON, `Integer` PKs).
- Recommendation: **core tables stay portable; add a Postgres-only spatial/graph layer**:
  - Geometry columns, GiST indexes, pgRouting views in a separate DDL block in `schema.py`, applied by `schema.init()` only when `BACKEND == "postgres"` (`geoalchemy2` or `sqlalchemy.text`). Nothing in the pipeline *requires* it, so SQLite tests and the "no server" default survive.
  - Geometry derived from existing integer `x, y` columns (generated column or view), so no portable-schema change and no second copy of coordinates.
  - Extensions need superuser → one-time `CREATE EXTENSION postgis, pgrouting` in `fpga_re` by the admin; `schema.init()` should `die()` if missing, not try to create them.
  - Pathfinding: load edges once per run into an in-process CSR (`connect_threadsafe()` worker reads), not `pgr_*` per net.
- Full move to Postgres-only: not justified by speed at current corpus size (sub-ms both sides). It becomes reasonable when the full-device graph (12M edges, 1.2 GB) and many boards live in one DB, or when QGIS is the main viewer. Prerequisite either way: install pg8000 for system python3.15t (pure Python, GIL stays off).

## Commands that worked / failed (quick reference)

- worked: `quartus_cdb <proj> -c build --back_annotate=routing --write_settings_files=on` → `build.rcf`
- worked: `quartus_cdb --tcl_eval help`, `help -pkg chip_planner`, `help -cmd routing_path`
- worked: `quartus_cdb -t cp_probe.tcl` with `package require ::quartus::chip_planner; project_open build -revision build; read_netlist; get_nodes -type lcell`
- failed: `routing_path -node 0 -port_id 1 [-table -file f]` → internal error (crash)
- failed: `--vqm=out.vqm --write_rcf_for_vqm=on` → no RCF written
- worked: `python3 -I tmp/survey/ddb_inflate.py <out> <ddb...>` (zlib @0x73)
- worked: `FOUNDRY=$D/ispfpga LD_LIBRARY_PATH=$D/bin/lin64:$D/ispfpga/bin/lin64 TCL_LIBRARY=$D/tcltk/lib/tcl8.5 $D/ispfpga/userware/unix/bin/lin64/ispTcl script.tcl` with `dev_list_node_at_location`, `dev_list_arc_by_node_name -to|-from <wire> -num 100000`
- failed: `ispTcl` `dev_list_arcs` → invalid command (prjtrellis's error-string name; real command is `dev_list_arc_by_node_name`)
- partial: `arcdump -ncd <ncd> -n|-sn` ok; `-a|-ac|-nc` segfault; `arcdump -d LCMXO2-256HC -a` segfault
- failed: `CREATE EXTENSION postgis` as normal user → needs superuser
