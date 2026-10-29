# Cyclone IV: relaxed `Dec.active` rule (#141 track 2)

Flag: `PLURIBUS_RELAX_ACTIVE=1` (default OFF; per-design active cache is keyed by the flag). Script: `scripts/cycloneiv_relax_analysis.py`.

Rejected as a method (gate-only decoder test, recovery-process.md Phase 3). The flag stays off until a specimen shows the new prediction.

## Prediction (stated before the run)
- Extras of refused full-pred groups are pred bits of other groups of the same block feeding the same dest mux; refused group is the sole full group on its (block, dest).

## Result (third-party EP4CGX150 image, 2026-10-29)
- Full-pred groups 572,453; fired 352,405; refused 220,048 (extras 1-3+ in block).
- Extras: all same-dest pred bits (S) 203,870 (92.6 %); other-dest pred bits (O) ~3,400; unpredicted second-level bit (N) 12,206.
- Sole full group on (block, dest): 17,439 only. Prediction half-refuted: extras are S, but the refused group is mostly not sole.
- 191,676 are all-S and DOMINATED (another full group of the block has a strictly larger pred set): correctly refused, the superset group already fires.
- Non-dominated refused: 28,358 (12,194 all-S, 16,164 with O/N extras).

## Rule
- Fire a full, refused group iff it is the only maximal full group of its block and every set bit of the block is a pred bit of some group of the block.

## Gate (76 `gx150_rb*` odd-split designs, RCF oracle; flag off -> on)
- LCCOMB pins [ddb]: matched 69,672 -> 69,673; missing 157,397 -> 157,384; extra 0 -> 0; wrong 32,025 -> 32,037 (+12).
- Per-hop ALL: matched 24,113 -> 24,112; missing 17,822 -> 17,815; extra 0 -> 0; wrong 10,353 -> 10,361 (+8).
- Wrong rose: regression under the scoring rule -> flag stays OFF.
- Image: fired groups +1,855-ish; class 2b set cells 42,832 -> 41,493 (1,339 move into 2a); not enabled.
