# Cyclone IV: LB -> R4 hop displacement and LI-mux order (#157, #141 track 2)

Tool: `scripts/cycloneiv_hop_specimens.py` (sample / plan-set / build / analyse / summary / record). Flag: `PLURIBUS_HOP_OVERRIDE=1` (default OFF; `Dec._hop_pf` in `scripts/cycloneiv_asm_decode.py`; caches `*_pf_hop1.npy`, `*_flat_hop1_*.npy`, `active_hop1/`).

## Predictions (written before the sweep, in the script docstring)
- P1: every LB -> R4 group is displaced -70 plane frames in all interior LAB columns.
- P2: the LI-mux input order is one fixed permutation per mux type, identical across LABs.

## Sweep (2026-10-29, Quartus, forced single path; null controls 0 differing cells before any arc)
- Builds 82 of cap 150 (41 pairs); answered features 41 (20 R4 shifts + 21 LI outcomes; the 3 R4 and 6 LI of the first run at X54Y61 are not counted); yield 50 per 100 builds vs floor 10.
- Forcing honoured only on hops seen in a corpus RCF (tier A). Corner and side LABs are not forceable: no corpus-named R4 mux there. Recorded as data rows (plan `skipped`), not retried.
- Forceable LABs: 114, all in X15..89, Y6..77. Sampled (R4): 4 interior extremes, 8 seeded interior (seed 20261029), 4 near-corner (X25Y77, X31Y22, X87Y6, X87Y66: the forceable LABs nearest a corner; not corner-class; two coincide with extremes), 6 column-scope.

## P1 (R4)
- LB -> R4 shift, 23 honoured arcs, 18 distinct LAB columns: -70 in 20, -74 in 3 (X87Y6, X87Y66, X29Y73). P1 literal: REFUTED (3 misses).
- All 3 misses are LABs whose two-column span holds a 39-frame column (FX[30]-FX[29] and FX[88]-FX[87] are 39, others 35). Rule R4-shift-v1 fitted on the 17 rows seen first: shift = -(w(c) + w(c-1)), c = column of the group cells, w(x) = FX[x]-FX[x-1] between two LAB columns, else 35 (M9K/MUL gaps count 35: X53, X66, X37, X82 next to M9K and X15 next to MUL all show -70).
- Rule check: 6 arcs planned after the rule, predicted before building: 6/6 (one predicted -74 at X29, five -70 incl. X37 and X82 next to M9K). Untested: X30, X88 (predicted -74; no forceable LAB in those columns).
- Claim `CLASS:2h` pattern `hop-shift-v1`: n = 23 scopes, tier `suspect` (see gate).
- Specimen-level decode with the override: the group of the forced hop is fully set and fires in 23/23 specimen builds; without it 0/23.

## Gate (76 gx150_rb odd-split designs, RCF oracle; flag off -> on)
- R4 hops: matched 902 -> 715; missing 5,335 -> 4,784; extra 0 -> 0; wrong 4,085 -> 4,823.
- ALL hops: matched 24,113 -> 23,926; missing 17,822 -> 17,271; extra 0; wrong 10,353 -> 11,091. LI, C4, C16, R24 unchanged.
- LCCOMB pins: matched 69,672 -> 69,701; missing 157,397 -> 160,749; wrong 32,025 -> 28,613.
- Matched fell and wrong rose: flag stays OFF. Variants run once to locate it (gate-only, not rules, not adopted): only LB-sourced R4 groups: R4 matched 463, missing 7,553, wrong 2,306; only R4 template indices 1/2/13/14: matched 735, missing 6,064, wrong 3,523.
- Specimen and gate disagree on the same hop class. The gate resolves an R4 destination as the unique fan-out record within |dvx| <= 3, |dvy| <= 1 of the RCF coordinate; the specimens resolve by exact tile. Open: #160.

## P2 (LI mux, idx 11)
- 5 interior LABs (X54Y61, X58Y45, X61Y47, X70Y43, X46Y45), all tier-A inputs (27 honoured arcs): identical (LI index, source class/index, edge k) gives different outcomes at different LABs (e.g. C4 idx 8 k=11: exact x4, permuted x1; C4 idx 15 k=8: four different outcomes in four LABs). P2: REFUTED. No LI correction implemented. Gap: #161.
- Rigid-shift fits of 2-cell groups are not diagnostic (a small group fits some shift by chance); only exact vs not-exact is used.

## NEW BASELINE: gate scoring correction (2026-10-29, #160)
- Superseded, not comparable: every earlier gate headline (26.89 % pins is unchanged; per-hop R4 8.7 %, ALL 24,113 / 52,288 = 46.1 %: matched + 17,822 missing + 10,353 wrong) dropped ambiguous hops and everything below an unresolved hop from the denominator.
- Rule: ambiguous / unresolved hop = MISSING, plus every RCF hop below it (`count_unreached` in `scripts/cycloneiv_ddb_trace.py`; gate_runs param `scoring=ambiguous_as_missing`).
- Flag-off baseline (76 odd designs, gate_run 1): pins LCCOMB 69,672 matched (26.89 %, unchanged). Hops matched / missing / extra / wrong: LI 10,199 / 133,630 / 0 / 4,304; R4 902 / 148,831 / 0 / 4,085; C4 13,012 / 118,305 / 0 / 1,964; C16 0 / 4,881; R24 0 / 4,756; ALL 24,113 / 410,403 / 0 / 10,353 = 5.42 %.
- Earlier "ambiguous" counts: full flag-off runs R4 44,850 / C4 25,960 / LI 422 (every run 15:18-16:27); R4 6 / C4 22,522 and R4 34 / C4 18 were the exact-tile and a limited run; 2,784 R4 is the 5-design subset.

## R4 destination convention (#160, `scripts/cycloneiv_r4_convention.py`)
- Exact tile: 0 of 5,913 alias-named R4 hops; named record dx in {-3,-2,-1,+1,+2} from the RCF x, dy 0. C4: dx,dy = 0,0 in 37,299 of 37,299.
- Prediction "dx = f(wire index, pitch)" REFUTED (fit 3 designs, 73 held out): 55.1 % agree of 5,525 covered, 480 wrong, 1,981 ambiguous (several R4 records at one tile). Tile offset alone does not identify the record; the vendor wire name (alias forms) does, and the alias table names only 10 % of R4 hops. Gap: new issue.
- Resolver and override default unchanged (override OFF); the override re-run under the corrected scoring was not made.
