# Cyclone IV retired coordinate model (#157, #160, #161, #162, #165)

Retired 2026-10-30; replaced by the clean pipeline (`docs/altera/cycloneIV/cycloneiv-clean-pipeline.md`). Old code and full result tables: tag `pre-clean-cycloneiv`, docs `cycloneiv-hop-override.md` and `cycloneiv-relax-active.md` at that tag.

## What was tried (asm address -> plane cell, LB -> R4 hops)
- Hop override (`PLURIBUS_HOP_OVERRIDE`): fixed -70 / -74 frame shift for LB -> R4 groups.
- Relaxed `Dec.active` (`PLURIBUS_RELAX_ACTIVE`): fire refused full-pred groups under a maximal-group rule.
- Frame-distance law P1' and per-column `(dx, df)` table (`PLURIBUS_R4_COLTABLE`), M9K-skip rule P4.
- Coordinate models v2..v5 (`PLURIBUS_COORD_V2`): AFX relabel, source-column mirror, EXC4 shift table, band-offset drop rule.

## Which tests refuted it
- Hop override P1 (-70 everywhere): 3 of 23 arcs at -74. Rule R4-shift-v1 fitted on 17 rows; gate R4 matched fell 902 -> 715, wrong rose 4,085 -> 4,823.
- LI-mux order P2 (one fixed permutation): refuted at 5 LABs.
- P1 (relative column) and P1' (frame distance): each refuted by arcs at the same key with different `(dx, df)`.
- Per-column table: held on 83 scopes, but gate ALL 24,113 -> 27,659 matched with missing and C16 wrong rising; flag stayed off.
- Relaxed active: wrong rose (+12 pins, +8 hops); flag stayed off.
- v2 (F3 mirror about source column): 383 / 399 arcs; gate ALL 5.42 % -> 3.16 %, blocks fragmented (units 1.62 M -> 4.10 M). v2b, v3: fault categories rose. v4: identical to v3.
- Common cause: constants fitted per column / source to explain the asm-to-plane step, which is a fixed function (A4 + A5 in the clean plan).
- v6 (raw address = sof index, sof2rbf, vendor x = fitter X): 399 / 399 arcs at tile level, gate ALL 5.42 % -> 11.28 %, wrong 10,353 -> 49. Basis of A5 / A8; the v6 files wait for the clean address engine.

## Scoring baseline
- Gate scoring changed 2026-10-29 (#160): ambiguous or unresolved hop = missing, plus every hop below it. Earlier headlines are not comparable.

## Pointers
- #157 hop specimens; #160 R4 destination convention and gate scoring; #161 LI-mux order; #162 per-column (dx, df); #165 clean pipeline.
- Raw specimen diffs stay in the evidence rows; derived claim classes 2h, 2h-fd, 2h-col are retired.
