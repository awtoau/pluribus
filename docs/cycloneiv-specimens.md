# Cyclone IV specimen tests — specification

What the minimal specimen designs are, what question each answers, and the sweep that counts as
complete. Companion to [recovery-process.md](recovery-process.md) (the method) and #141 (the
pivot). Tooling: `scripts/cycloneiv_specimens.py` (gen / build / solve / verify).

## Anatomy of a specimen

- 1–2 cells (LUT→LUT or LUT→FF), ONE net under test, LOCATION-pinned sites.
- Built as a **pair**: base design (no net) + specimen; the base subtracts the always-on config
  groups, so the fired-block diff is the path alone.  Implemented: interior rows = l2 reads the
  input pin in the base; pin row 6 = constant-LUT base; pin row 7 = base drives the pin from a
  second LAB (the exit mux then differs and survives the diff).
- Precondition found by the first specimen: the asm→plane frame map needed per-column asm bases
  (`afx_map`, cycloneiv_asm_decode) — 7 LAB columns sat inside the plane's M9K spans and decoded
  to nothing; see cycloneiv-ddb-format.md "Coordinates".
- Oracle per specimen: the post-fit RCF path.  Chip Planner probed 2026-10-28 and REJECTED:
  `routing_path` internal-errors in 25.1std Lite (`dump_routing_path` → `get_delay` →
  `CDB_ATOM_NODE::get_instance_name`, on specimen and corpus builds alike); `get_nodes` returns
  used atoms only (no device-wide dump); node ids are atom indices, not routing.ddb record ids.
- Answer format: exact (tile_class, block key) → output record / pin, provenance `specimen`, into
  `lifters/data/cycloneiv_ep4cgx150_phys_map.json`.
- One question per build. A specimen whose answer is ambiguous is split into narrower specimens,
  never voted over.

## Sweep matrix (completion = every row covered)

| # | Kind | Question | Sweep |
|---|---|---|---|
| 1 | LI driver | which block drives LI index i of a LAB | LUT→LUT same LAB, every LI 0–15; cross-LAB sources for LI 16–41 |
| 2 | LE input mux | which LI feeds LE input a/b/c/d | every (input, LE position 0–15) |
| 3 | LE_BUFFER fan-out | where each LE output can enter the fabric | all 6 fan-out groups per LE family |
| 4 | R4 / C4 | span wires: driver mux per offset | each direction, each of the 4/4 offsets within span, per column/row class |
| 5 | R24 / C16 | long wires | each direction, sampled offsets, every driver class |
| 6 | Pin → fabric | IO ring entry muxes | **every bonded pin** of the package, varied targets per pin |
| 7 | Fabric → pin | IO ring exit muxes | every bonded pin as output, varied sources |
| 8 | Edge truncation | what happens to spans at the boundary | R4 sources within 4 cols of either edge; C4 within 4 rows; R24/C16 equivalents; all four edges |
| 9 | Corners | compound edge behaviour | all four corners, kinds 1–8 repeated there |
| 10 | FF pins | clock / ena / clr / sload / data routing into LAB control lines | per control, per LAB class (later phase — clock tree) |
| 11 | M9K | RAM block pin ↔ fabric muxes | every port pin (addr/data/ctrl, both ports), in and out, per M9K column |
| 12 | Multiplier | DSP pin ↔ fabric muxes | every pin of the 18×18 block, per DSP column |
| 13 | PLL | inputs, outputs, lock, clock entry | every PLL, every output counter → where it can go |
| 14 | Clock network | GCLK/RCLK mux sources | pin→GCLK, PLL→GCLK, fabric→GCLK, per network input |
| 15 | HSSI (GX) | transceiver ↔ fabric pins | per channel, lower priority unless the target image uses them |

## Hard IP rule (Dan, 2026-10-28)

- Hard IP gets the SAME treatment as fabric: don't be smart — extensive small tests.
- The core pattern is **one pin, several different things connected to it — as separate tests**:
  fix one IP pin and sweep what's on the other end (LUT, FF, another IP pin, an IO pin, a
  constant), ONE connection per build. (pin × far-end kind) = one specimen pair; five variants =
  five builds, never one build with five nets. Each build fires a different mux into/out of that
  pin; the union over builds maps the pin's full connectivity. Then the next pin.
- One pin per specimen, never a configured "realistic" IP instance as the unit of test — a
  realistic instance answers many questions at once, which is to say none of them exactly.
- IP configuration bits (modes, widths, counters) are a separate decode from pin routing; keep
  the specimens single-variable there too: one parameter changed per pair, diff the planes.

## Edge rule (Dan, 2026-10-28)

- Edges are where tile-class patterns break (precedent: MachXO2 V-span edge mirroring, H06E
  right-edge sense bug; the CIV coordinate formula is unverified on non-LAB columns).
- Exact edge placement is hard to force directly → place a cell on each **bonded IO pin**
  (pin assignment is exact) and connect it to varied targets; the fitter must then use that edge
  tile's routing, and the oracle reports what it did. Vary connections per pin across repeats.
- **Edge tiles are their own classes**: never pool an edge answer with interior tiles of the same
  X-mod-8 class; never generalise an interior pattern to an edge tile without a verifying
  specimen there. Corners doubly so.
- Coverage is reported as its own line: edge tiles touched / total, bonded pins touched / total.

## Generalisation + verification

- ≥2 positions per (kind × tile class) must agree before an answer generalises class-wide; any
  disagreement ⇒ enumerate every position of that class (brute-force-first rule).  A single
  interior observation stays a per-tile entry (`wires_tile` / `lis_tile` in the phys map) until
  a second position confirms it.
- **The unit of generalisation is the GROUP, not the block** (found by the first sweep's
  conflicts): one block = groups sharing second-level bits can hold SEVERAL muxes, each driving
  its own wire.  Answers are keyed (class, block key, group select position) and a map entry
  carries the list of its groups' outputs; the tracer's backward walk (record → driver block →
  fired source) is unaffected.  Corollary: a design using two outputs of a shared-bit block at
  once defeats the block-exclusivity firing rule — neither fires (decode gap, counted).
- Held-out specimens verify the generalised map; the fixed 76-design gate set verifies
  composition end-to-end.
- Every specimen answer must agree with the routing.ddb fan-out decode wherever that overlaps
  (two exact sources; a disagreement is a decode bug in one of them, find which).

## Status (2026-10-28 sweep)

- Built: 5,022 designs = 2,511 pairs (interior 32 classes × 3 positions × 9 displacements; all
  384 edge LAB tiles, both roles; 4 corners × 9; every bonded pin in + out, 451 × 2), ~12–20 s
  each at 20 parallel chains; 3 load-induced failures retried clean.
- Solved: 2,535 specimens, 0 errors, 0 same-tile / class conflicts (final ruleset).  Edges
  matched 6,274 / 44,469 over all nets; no-candidate 35,602, ambiguous 2,593.
- Exact entries (provenance `specimen`): C4-driver 13 class + 35 per-tile, R4-driver 1 per-tile,
  LI-driver 20 class + 47 per-tile.  Where exact overlaps the voted maps: 4 / 4 agree.
- Edge coverage: 8 / 384 edge LAB tiles touched; pins with ≥1 matched edge: in 236 / 451,
  out 429 / 451.
- **Ceiling found**: most path muxes never FIRE in the asm decode (`Dec.active`) at all — C16/R24
  driver muxes, most LI drivers, nearly all edge/IO-ring muxes.  Specimen matching is exact where
  a block fires; the firing coverage itself is the blocker (unattributed 2/6/12/16-groups,
  block-exclusivity, remaining transform gaps).  That is track 2 of #141 (routing.ddb fan-out /
  group attribution), not more specimens.

## Block checklists and order (Dan, 2026-10-29; ranking rule in recovery-process.md)

Order: M9K → LAB core classes (LOCAL_LINE sink ports, control stripe, LE modes, LE_BUFFER) →
LI/R4/C4 interior → multiplier → IO/periphery → edges/corners last. Edges are NOT first.

M9K checklist (one M9K, pinned site, one change per pair, raw diff; tick each):
- [x] data: widths x1,x2,x4,x8,x9,x16,x18,x32,x36 at one site (M9K_X23_Y40_N0): full (word,bit) -> cell tables, 0 unattributed, held-out round trips exact (commit: see M9K hardware map below)
- [ ] mode: single-port / simple dual / true dual / ROM / FIFO; one change per pair
- [ ] clocking: clock-enable, aclr, read-during-write, output register on/off, address register on/off
- [ ] ports: each address / data / byte-enable / write-enable pin routed (one pin, one far-end per build)
- [ ] column position: same pair at ≥3 M9K sites per column and in every M9K column (8) — confirm the single-offset rule

Mark each box with the commit that verified it; unticked boxes appear in the inventory top-10.

LAB control-line checklist (`scripts/cycloneiv_ctrl.py`; labs a-d = X10Y10 / X58Y30 / X37Y60 / X100Y75; raw cram diff, evidence rows `cycloneiv_ctrl:<set>:<lab>`):
- [x] clk, clkpin, ena, aclr, sclr, sload, asdata: 17 pairs x 4 labs built and diffed, 6 rebuilt (10%), 0 unstable (536a7b312)
- [ ] pos, pos2 (LE position), idle: sweep paused; held-out TileClassTranslate prediction pending
- Cross-lab: a single (frame, v) offset per lab (b +2438/+1400, c +1455/+3500, d +4676/+4550) explains only 5-34% of the bits per set; the diffs carry routing bits of the new connection, so lab-to-lab laws need the routing part separated first.

## M9K hardware (word,bit) map, one site (#141)

- Method: altsyncram + MIF (Quartus does the logical -> physical placement); binary-coded init, specimen k sets (word,bit) iff bit k of word*W+bit+1; raw cram-plane diff, no decoder. Tables: `tmp/cycloneiv_m9k_hmap<W>.json` (also in the family DB as derived-table rows, `scripts/cycloneiv_m9k.py register`).
- Located: 8192 cells (x1,x2,x4,x8,x16,x32) or 9216 (x9,x18,x36), 0 unattributed, per width.
- Held out: 2 random builds per width (~150 distinct (word,bit) pairs each, 2 x 9 widths): predicted set == raw diff, 18/18 exact.
- Stability: 23 of 187 builds (12%) rebuilt under new names: raw diff identical, 23/23.
- Laws (exact on every cell, F1 = the x1 index map `tmp/cycloneiv_m9k_hmap1.json`):
  - x1,x2,x4,x8: cell = F1[word*W + bit].
  - x9: lane = bit%9; lane < 8 -> F1[word*8 + bit]; bit 8 -> parity cell P[word].
  - x18: bit = 9*L + r; r < 8 -> F1[word*16 + 8*L + r]; r = 8 -> parity P2[word,L] (1024 parity cells in total, disjoint from F1's).
  - x16 = x18 (same word, same bit index 0..15).
  - x36 = x18 (word + 256*(bit >= 18), bit % 18).
  - x32 = x36 (same word, bit if bit < 14 else bit + 4): x36 bits 14..17 are not reached by x32.
  - x9 parity (fitted, `pattern_matchers.BitLinearLaw`, held-out 204/204): frame = 1111 + (w>>2); v = 2789 - 18*(w&1) - ((w>>1)&1).
- The WYSIWYG ram_block primitive rejects port_a_data_width 32 and 36 (quartus_map error 14093); altsyncram is the route for those widths.
- The (word,bit) map equals the mem_init-index map (index = word*W + bit) for x1..x18: no separate hardware permutation exists for them.

## Cost

- One specimen pair ≈ 15 s of Quartus (measured 2026-10-28); the matrix is a few thousand
  builds, embarrassingly parallel across 32 cores within the 20 GB free-RAM rule — minutes to
  low hours of wall-clock, re-runnable at will.

## Raw-diff specimens (forced single-hop)

- Binding rules: [recovery-process.md](recovery-process.md) "Specimen rules for agents".  Tier 0/1 tool: `scripts/cycloneiv_forced.py`.
