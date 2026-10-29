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

## LB -> R4 (dx, df) vs source column (#162, `scripts/cycloneiv_r4_relcol.py`; 2026-10-29, 0 new builds)
- Pool of 62 existing set-level arcs (results_r4map_*, r4df_*), 4 destination tiles (X30Y50, X47Y45, X63Y32, X89Y44), rigid-shift window |df| <= 80 (140 for the rel +4 re-read).
- P1 as written ((dx, df) = f(source X - destination X, destination pitch)): REFUTED. X63Y32 rel +3 (source X66) = (-5, 0) against (-7, -35) in 18/18 arcs at X47Y45/X89Y44 (same rel, pitch 35).
- Cause visible in the geometry: X66 is 363 frames from X63 (M9K column X65 between); X47->X50 is 105. Keyed by source-minus-destination frame distance `FX[src]-FX[dst]` instead of X, no key has two outcomes (n small, one key per scope pair):

| FX distance | dest pitch | (dx, df) | n | tiles |
|---|---|---|---|---|
| -35 | 35 | (+2, 0) | 9 | X47Y45, X89Y44 |
| -39 | 39 | (+2, +4) | 3 | X30Y50 |
| 0 | 35 / 39 | (0, -70) | 16 / 2 | X47Y45, X89Y44 / X30Y50 |
| +105 | 35 / 39 | (-7, -35) / (-6, 0) | 18 / 2 | X47Y45, X89Y44 / X30Y50 |
| +363 | 35 | (-5, 0) | 1 | X63Y32 |
| +140 | 35 / 39 | no fit (2) / (-9, -105) (1) | 3 | X47Y45 / X30Y50 |

- Frame-distance keying is a post-hoc fit, not a prediction; a specimen must show it. Not recorded as a rule claim.
- P2 (rel +4 sources unmatched only because of the window): window to 140 resolves 1 of 3 (X30Y50, df -105, one arc); X47Y45 still no fit (2 arcs). Not supported.
- Corpus RCF edges LB -> R4 only have source X offsets -1, 0, +3, +4 (+1, +2 never seen, so cannot be forced).
- 5-scope sampling plan (corners + seeded interior) not built: first prediction miss stops the sweep (Yield rule).

## Frame-distance law P1' sweep (#162, 2026-10-29, `scripts/cycloneiv_r4_relcol.py`, claim class `2h-fd`)
- Prediction: (dx, df) = f(d = FX[src]-FX[dst], destination pitch w). Refuted by two arcs at one (d, w) with different (dx, df).
- Null controls (rename, seed; base and spec): 0 differing cells. Builds 34 of cap 45 (4 nulls, 15 bases, 15 specs); 15 arcs honoured and resolved; 15 answered features = 44 per 100 builds (floor 10).
- New scopes (dest tiles): X25Y77, X31Y22, X87Y6, X87Y66 (corner-most forceable LABs), X88Y40 (pitch 39), X21Y29 (source across the X23 M9K column). X87Y6 rel +3: no corpus-seen chain (data row).
- P1' REFUTED, 3 keys, 3 scopes (scored against the 4 earlier tiles):
  - (d -35, w 35): (+2, -4) at X87Y6 and X87Y66 vs (+2, 0) in 11 arcs.
  - (d 0, w 35): (0, -74) at X87Y6 and X87Y66 vs (0, -70) in 18 arcs.
  - (d 105, w 35): (-6, 0) at X25Y77 vs (-7, -35) in 19 arcs.
- Held: X88Y40 (w 39) equals X30Y50 at all three keys ((+2,+4), (0,-70), (-6,0)); X31Y22 equals X47Y45 at all three; X21Y29 d 109 (-6, 0) equals X63Y32 d 363 pattern only by dx/df, different d.
- Post-hoc, not tested: X87 sits left of the 39-frame column X88 (df -74/-4 = the 39-frame span, as in R4-shift-v1); X25 is two columns right of the X23 M9K column (as X63 left of X65). Pitch class of the destination alone is too coarse; neighbouring column widths/kinds enter. Next: enumerate by (neighbour widths) as a prediction.
- `claims_register.py` run regenerates derived tables including `gate_runs` (wiped every run by design); the #160 gate_run row is gone from the DB and must be re-run, numbers stay in this doc.

## Per-column enumeration (#162 P3, 2026-10-29, `cycloneiv_r4_relcol.py colplan/coltable/colrecord`; claim class `2h-col`)
- Prediction P3: (dx, df) constant per destination column and source relative column, across rows Y and R4 names. Refuted by two arcs with different (dx, df) in one (column, rel).
- Result: HELD, 0 misses. 75 confirm rows over 30 (column, rel) groups (6 columns x 2 rows x rels -1/0/+3/+4, plus earlier X30/X47/X63/X89); 147 further (column, rel) cells have one row (no constancy test). Tier `sampled` n=83 scopes is inflated by the single rows.
- Builds about 385 of cap 400 (4 nulls 0 cells; 190 bases; 190 specs); 264 arcs honoured; 252 resolved (+ data rows) = about 65 answered features per 100 builds (floor 10).
- Measured table: derived-table row "R4 per-column (dx, df) table by source rel (264 arcs)" with FX[dst-1], FX[dst], FX[dst+1], neighbour kinds, per (X, rel).
- Coverage: rels 0 and +3 in all 68 forceable LAB columns X15..89 (one row); rel -1 in 44 of them; rel +4 in 8 columns only.
- Observed rel 0: df -70 in most columns; -74 at X27, X29, X85, X87; -65 at X40, X71; -95 at X42, X73; -105 at X34, X41, X50, X72, X79. No fit (|df| <= 140, 5 data rows) at X22, X35, X51, X64, X80 (right neighbour X+1 = M9K) and X63.
- Observed rel +3: (-6, 0) in most; (-7, -35) at X18, X19, X31, X32, X38, X39, X47, X48, X60, X61, X69, X70, X76, X77, X89; (-5, 0) at X21, X22, X34, X35, X41, X42, X50, X51, X63, X64, X72, X73, X79, X80.
- No rule fitted (process: enumerate, then fit). Next: fit candidates against this table as predictions on held-out columns.

## Per-column table as resolver lookup (#162/#160, flag `PLURIBUS_R4_COLTABLE`, default OFF; 2026-10-29)
- Code: `scripts/cycloneiv_r4_coltable.py` (table from the derived-table row; `apply` shifts the asm frames of every LB -> R4 edge matched by (dest column, source rel): +df frames, superseding the hop-override shift on those edges); `hop_forward` resolves LB-sourced R4 hops by (dx, dy 0) from the table, no cell = unresolved = missing. Non-LB-sourced R4 hops keep the window resolver.
- Table edges: 465,996 of 970,224 LB -> R4 edges shifted, 0 ambiguous.
- Gate (76 odd designs, scoring ambiguous_as_missing; gate_run 2 = flag off, 3 = on); matched / missing / extra / wrong:
  - R4: 902 / 148,831 / 0 / 4,085 -> 3,997 / 149,316 / 0 / 505.
  - LI: 10,199 / 133,630 / 0 / 4,304 -> 10,196 / 133,772 / 0 / 4,165.
  - C4: 13,012 / 118,305 / 0 / 1,964 -> 13,001 / 118,855 / 0 / 1,425.
  - C16, R24 unchanged (0 / 4,881 / 0 / 0; 0 / 4,756 / 0 / 0).
  - ALL: 24,113 / 410,403 / 0 / 10,353 (5.420 %) -> 27,194 / 411,580 / 0 / 6,095 (6.113 %).
  - LCCOMB pins: 69,672 / 157,397 / 0 / 32,025 -> 69,719 / 159,813 / 0 / 29,577.
- Missing rises (R4 +485, LI +142, C4 +550, pins +2,416) and LI / C4 matched fall by 3 / 11: default stays OFF (rule: no fault category may rise). Missing grows where the table has no cell (rel +1/+2 absent; M9K-neighbour columns) and below those hops.
- Table + `PLURIBUS_HOP_OVERRIDE=1`: R4 3,997 -> 829 matched, wrong 505 -> 2,420 (hop shift on the remaining R4 edges is wrong). Not an additive pair; the table alone is better.
- Not done (flag off): bit inventory / progress ledger reruns.

## Table fill 2 (#160/#162, 2026-10-29): 114 builds (4 nulls 0 cells, 55 bases, 55 specs); 55 arcs, all resolved = 48 per 100 builds (floor 10)
- Cells added: second rows at X15 (rel 0, +3) and X89 (rel -1, 0, +3), all consistent; 50 high-hop-count cells (rel -1, +3, +4, including MUL / M9K destination columns X36, X42-X44, X52, X65-X68, X74, ...). 0 misses. Table: 319 arcs; 2h-col `sampled` n=25 scopes from 34 groups of >= 2 rows, extremes included.
- Rel 0 at X22, X35, X51, X63, X64, X80 (right neighbour M9K), window widened to |df| <= 210: still no fit (candidates dx 0 x2 and -4; 5 arcs). Data rows. Rel +1/+2 never in corpus edges: data rows, no cells.
- Gate, flag off (run 2) vs on (table fill 2), matched / missing / extra / wrong:
  - R4: 902 / 148,831 / 0 / 4,085 -> 4,413 / 148,787 / 0 / 618.
  - LI: 10,199 / 133,630 / 0 / 4,304 -> 10,201 / 133,709 / 0 / 4,223.
  - C4: 13,012 / 118,305 / 0 / 1,964 -> 13,008 / 118,731 / 0 / 1,542.
  - C16: 0 / 4,881 / 0 / 0 -> 0 / 4,880 / 0 / 1. R24 unchanged.
  - ALL: 24,113 / 410,403 / 0 / 10,353 (5.420 %) -> 27,622 / 410,863 / 0 / 6,384 (6.209 %).
  - LCCOMB pins: 69,672 / 157,397 / 0 / 32,025 -> 69,740 / 161,033 / 0 / 28,337.
- Rises remain: LI missing +79, C4 missing +426, C16 wrong +1, C4 matched -4, pins missing +3,636 (wrong -3,688). Default stays OFF.
- Hops still without a cell (R4, LB source): 4,974 (was 12,762); by rel: +4 2,329, 0 1,107, +3 780, -1 751; 2,889 in X15..89. Largest cells: (90,0) 108, (51,0) 105, (59,4) 98, (34,4) 96, (53,4) 96, (63,0) 96, (35,0) 94, (51,4) 94, (82,4) 94, (80,0) 94. The C4 / LI missing rise is hops below an R4 hop that the window resolver used to resolve and the table now leaves unresolved.

## Table fill 3, M9K skip rule, C16 wrong (#160/#162, 2026-10-29)
- Builds 164 of cap 200 (4 nulls 0 cells, 80 bases, 80 specs); 80 arcs, 73 resolved at |df| <= 140, 7 more at 400 = all resolved (49 per 100 builds, floor 10). Table 399 arcs; 2h-col `sampled` n=53 scopes, 48 groups of >= 2 rows, 0 misses.
- P4 (predicted before the test, `cycloneiv_r4_relcol.py m9kpred`): a group next to an M9K column sits 2 LAB columns left SKIPPING the M9K gap, df = -(FX[c] - FX[second LAB column left of c]). Dest X22, X35, X51, X64, X80 rel 0: predicted -363, fitted -363 in 5/5 (one candidate fits each, none contradicts). X63 rel 0 (window 400): (0, -105) in 3 arcs. 7 rel +4 arcs: (dx -9, df -363).
- Gate (76 designs; off = run 2; on = full table), matched / missing / extra / wrong:
  - R4: 902 / 148,831 / 0 / 4,085 -> 4,448 / 148,753 / 0 / 617.
  - LI: 10,199 / 133,630 / 0 / 4,304 -> 10,202 / 133,704 / 0 / 4,227.
  - C4: 13,012 / 118,305 / 0 / 1,964 -> 13,009 / 118,708 / 0 / 1,564.
  - C16: wrong 0 -> 1; R24 unchanged. ALL: 24,113 / 410,403 / 0 / 10,353 -> 27,659 / 410,801 / 0 / 6,409 (6.217 %).
  - Pins LCCOMB: 69,672 / 157,397 / 0 / 32,025 -> 69,755 / 162,017 / 0 / 27,338.
- Default stays OFF: LI missing +74, C4 missing +403, C16 wrong +1, C4 matched -3, pins missing +4,620.
- Hop diff off vs on (`PLURIBUS_DUMP_HOPS`): R4 hops missing -> matched 3,679, wrong -> missing 3,098, wrong -> matched 582, matched -> missing 706 (690 are rel +3 at many columns, e.g. X66, X69, X68, X35, X56). C4 wrong -> missing 181, matched -> missing 8; LI wrong -> missing 33. The rises are wrong -> missing conversions plus the 706 R4 matched hops whose window record fired in off and whose table record is idle in on.
- Variant (diagnostic, `PLURIBUS_R4_COLTABLE_WINDOW_RELS=3`: rel +3 stays on the window resolver): LI wrong 4,441 (+137), C4 wrong 2,537 (+573): also rises.
- Remaining hops without a cell: 926 (X < 15 or X >= 90, rel +4 238, rel 0 258, rel -1 233, rel +3 190).
- C16 wrong (design gx150_rb_079): dest C16 at tile X42 Y60; chain DRV FF X41 Y76 -> LE_BUFFER X41 Y76 -> R4 X42 Y76 -> C16. The table resolves the R4 to the record at vx 74 vy 76 (index 3, in the C16 fan-in); the C16 mux fires the C4 at vx 74 vy 74 (index 18). With the resolver only (no frame shift, `PLURIBUS_R4_COLTABLE=2`) the same wrong appears; flag off counts the hop missing because the R4 above it is ambiguous. C16 matches 0 of 4,881 in every mode: pre-existing C16 mis-attribution revealed by the changed upstream resolution, not a table shift effect. The R4 record could still be wrong; not separable here.
