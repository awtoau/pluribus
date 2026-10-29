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
