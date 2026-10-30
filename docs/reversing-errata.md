# Reversing errata (#165, #167, #168, #169)

Claims that were wrong or unsupported because of reversing / fitting, and where the correct statement lives. Status: WRONG (refuted, text removed), UNVERIFIED (no vendor derivation yet), CORRECTED (fixed in docs / code), PARKED (Cyclone V, out of scope by Dan 2026-10-30; listed only).
Machine check: `tests/test_errata.py` fails if a banned pattern (block below) reappears in a tracked doc or source file outside the allowlist. Add a pattern when a claim is declared WRONG.
Reversing refs are libraries of `quartus/linux64`, ELF vaddr (Ghidra shows +0x100000). Names: `reference/ghidra/*.tsv`.
Conditions: 2026-10-30, EP4CGX150, Quartus 25.1. Static analysis only.

## Cyclone IV GX

| ID | Claim | Where stated | Status | Evidence | Correct statement / open | Reversing (function@vaddr) |
|---|---|---|---|---|---|---|
| E-A1 | JTAG classes set 2 option bits (core access, pin share) | `docs/cycloneiv-address-spaces.md` 3.1 (was line 108), #165 | CORRECTED | `OPTION_REG_JTAG_CORE_ACCESS` / `_USE_JTAG_PIN_SHARE` have no asmdb group on this die; 0 bits in 197 pair builds (`docs/cycloneiv-clean-options.md` sec 5) | 4 of 15 JTAG classes have a group (2 CRAM x 16 bits, 2 DB_ILLEGAL); the rest write nothing | `ASM_OPTION_REG_*::process_*` libcomp_asm 0x1caa60.. (functions.tsv); `ASM_ARCH_GROUP::mux_select` libcomp_asmcc 0x28526 |
| E-A2 | Option bit function: "0 of 160 decoded" | `docs/cycloneiv-address-spaces.md` (lines 11, 28, 3.2, 7) | CORRECTED | `docs/cycloneiv-clean-options.md`: 30 / 160 | 130 forced / default bits: function open | same as E-A1 |
| E-A3 | LUT address = `... - dy + 23` ("dy negated", "+23 fitted"); also `dx*6154 + dy + 3`, "+43 frame offset" | `docs/cycloneiv-clean-pipeline.md` A3 + Open, `lifters/cycloneiv_clean/README.md` A3, `docs/cycloneiv-ddb-format.md` asmdb section, #165 comment "LUT sign test" | CORRECTED | vendor formula as read, no sign flip, no constant: 1,023 / 1,023 sites (16,368 cells), next best 74 / 1,023 (#165 comment "O1"). 23 = dy_min + dy_max = 8 + 15, so the negated form is the same cell set, not a constant. Fit from one cell is gone | A3 restated in the three files. OPEN: the decoded pool vectors sit exactly 3 frames above the model (`y_cum + 3`) and the decode's `y_cum` sign convention is not derived; the +3 is not in the oracle | `ASMDB_BLOCK_INFO::calculate_bits_traditional` libdb_asmdb 0x8e8a4 (re-read 2026-10-30: `(addr/W + hi)*W + addr%W + lo`, W = 6154, cell = `hi<<16 | lo`); pool decode of `y_cum`: `PDB_SEGMENT_READER` libdb_pdb (open) |
| E-A4 | Pairing LAB columns with instance cells "right-to-left", `lo[c] = FX[X] - 61`, AFX = FX | `docs/cycloneiv-ddb-format.md` asmdb section | CORRECTED | pairing ascending with X scores 1,023 / 1,023; right-to-left was half of the compensation for the wrong dy sign (#165 comment "LUT sign test") | A3 | `calculate_bits_traditional` 0x8e8a4 |
| E-A5 | "LUT INIT bit b sits at RBLUT index 15 - sigma(b), sigma = per-site permutation (fitter pin swap)" | #165 comment "O1" | UNVERIFIED | the gate reads `.vo` lut_mask bit l at cell index 15 - l with identity pin order: 100 % (8,661 / 8,661 rb10). The two statements are not reconciled: the `.vo` ports are post-fit physical pins, so sigma is likely the fitter's swap already applied in the `.vo` | open: derive the pin-order relation from `LE_LUT_FUNCTION` / `ASM_LE_LUT` process_atom | `libcomp_asm` LE LUT writer (not yet named) |
| E-B1 | Old +23 / dy-sign called "fitted constants" | `docs/cycloneiv-clean-pipeline.md` (Open), #165 | CORRECTED | see E-A3 | 23 = dy_min + dy_max, not a fit constant | n/a |
| E-C1 | Learned-table results: per-column / per-source tables, `Y mod 4` C4 naming, `X mod 8` tables, held-out 92.10 %, 17.4 %, 4.1 % scores, Jaccard clock-inversion bit (-6,-30), "mux bits at the driving end" | `docs/cycloneiv-bitstream.md` (EP4CE6 findings, EP4CGX150 routing tables, method findings) | WRONG (removed) | fitted to the corpus; refuted when replaced by the fixed asm-to-plane function (`docs/cycloneiv-retired-coordinate-model.md`); gate ALL 5.42 % -> 11.28 % under v6 | clean tracer numbers in `docs/cycloneiv-clean-pipeline.md`; clock inversion open | `get_bits_from_source_to_dest` libddb_dygr 0x23bfe0; `silent_set_bits` libcomp_asmcc 0x1a240 |
| E-C2 | AFX ladder, `lab_vx` mirror, `plane_frame = FX + 17 - (asm - AFX)`, `plane_v = 6344 - asm_v`, vendor x = 115 - X, FX - 61 anchors, "88 double-offset frames" | `docs/cycloneiv-ddb-format.md` (coordinates, LI element, asmdb), `docs/cycloneiv-address-spaces.md` (regions) | WRONG (removed) | `docs/cycloneiv-retired-coordinate-model.md` (v2..v5 refuted); A8: vendor x = fitter X 354 / 354 | A4 + A5 (`plane.address_to_plane`); "88 double-offset" never shown, dropped | `silent_set_bits` 0x1a240; sof writer `PGMIO_F2P` (A5 measured with `quartus_cpf`, not decompiled) |
| E-C3 | (dx, df) tables, hop override (-70/-74), relax-active, Y mod 4, EXC4 | retired doc, #157 #160 #161 #162 | WRONG | refutations listed in the retired doc | clean pipeline | as E-C2 |
| E-D1 | "Register-used bit" exists | #165 comment (clean tracer), early gate notes | CORRECTED | no dedicated bit; pair specimens: FF added to a LUT LE clears YGR of each used output path; FF-only LE sets `LE_USE_SYNC_CLEAR` + `LOAD` (5 LABs x 75 sites) | `lifters/cycloneiv_clean/reg_used.py` | `LE_REG_OUT_YGR` group via asmdb; writer `ASM_LE_*` (open) |
| E-D2 | "YGR clear and LUT cells set" marks a used FF | #165 comment (clean tracer, "Observation, not applied") | WRONG | loses/over-claims for FF+comb LEs (#165 comment, run 20) | E-D1 | as E-D1 |
| E-E1 | RCF `route_port` permutation gives the LUT INIT bit order (26.8 %) | #165 early gate comment | CORRECTED | `.vo` ports are post-fit physical pins; RCF route_port equals them; identity order 100 % | `scripts/cycloneiv_clean_gate.py` header; no doc keeps the permutation | n/a |
| E-F1 | pcf payload "zlib at byte 117" | earlier notes (no current file keeps it) | CORRECTED | `78 da` at byte 115 (0x73); stream truncated at the `00 00 ff ff` marker (746), no trailer | `docs/cycloneiv-bitstream.md` Install-side data | `PGMIO_*` readers libpgm_pgmio / libpgm_npcf (functions.tsv) |
| E-H1 | "IV has no separate PRAM; IO bits live in CRAM" | none stands in a current doc (grep); implied by "asm.ddb holds CRAM only" misread | CORRECTED | IOE settings are CFF (31,060 bits), asm.ddb holds CRAM only (51,565,365 / 51,565,365) | `docs/cycloneiv-clean-io.md` E1-E4 | `silent_set_bits` 0x1a240 (tag 101 = CFF) |
| E-I1 | "decoded" coverage tier rows tied to classes 2a / 2b | `docs/cycloneiv-bit-inventory.md`, `docs/coverage-history.jsonl` | CORRECTED | classes 2a / 2b removed 2026-10-30 (asm routing attribution rode on the retired model); history lines are kept | return with the clean address engine; line 70 of the inventory still quotes a count "measured with 2a / 2b present": UNVERIFIED | n/a |
| E-J1 | Variant `lit_x` (literal `b0 == +1 or b1 == -1`) vs `sel_x` ("first entry always the select"): how chosen | README tracer facts, `docs/cycloneiv-clean-image.md`, #165 gate comment | WRONG as a rule description | `lit` was read off the corpus flags; the on-disk b0 / b1 bytes are i8 DELTAS (running sum parity gives F0 / F1). `sel_x` 62.08 % on the sample was a corpus check, i.e. the choice of `lit_x` before the first comparison used rb_000..009 observation, not the code | vendor rule: F0 clear -> bit must be 1; F0 set -> bit = F1; destination exclusion bits not in the source's list must be 0. README fixed; routing agent's uncommitted `tracer.py` implements it; `docs/cycloneiv-clean-image.md` still names `lit_x` (gate-result label, rerun pending) | `DYGR_ROUTE_ASM_INFO_BODY::get_bits_from_source_to_dest` libddb_dygr 0x23bfe0; `DYGR_ROUTE_ASM_BIT::use_encoded_setting` 0x23ab90; `is_encoded_bit_high` 0x23abb0; `operator<<` 0x2caf80 |
| E-K1 | IV option bits that "reach" the rbf header | `docs/cycloneiv-address-spaces.md` (35 bits, 51 cells), options.md 9 (7 of the 130) | CORRECTED | consistent after fix: 35 = 28 group + 3 forced (7, 38, 94) + 4 default (71, 106, 112, 130); options.md listed bit 7 in the group set (typo fixed) | open: which forced / default bits matter | cpf header overlay (`quartus_cpf`, not decompiled) |
| E-L1 | Fan-in / flag rules in tracer docs fitted rather than from assembler code ("Entry roles", "Set-only over-fires", "Not decided by the flags") | `lifters/cycloneiv_clean/README.md` tracer facts | CORRECTED | see E-J1; the "not decided" cases (3-groups with b0 = 0) are artefacts of reading deltas as values | README rewritten | as E-J1 |
| E-L2 | "Fan-in conflicts 4.2 % is the tracer's own error level" | #165 comment (image decode), `docs/cycloneiv-clean-image.md` 52-53 | UNVERIFIED | measured under the `lit_x` rule (E-J1); `sel_x` showed 0 conflicts. Needs rerun under the vendor rule | rerun after the tracer commit | as E-J1 |
| E-M1 | Cyclone IV E/GX: no PRAM | n/a | (see E-H1) | | | |
| E-N1 | HIO / VIO / clock / PLL / GX / HSSI / CONTROL / OCT groups: "CRAM offsets relative, no decoded instance base" (counted, not placed) | `docs/cycloneiv-clean-fields.md` (enumeration table, Open), `lifters/cycloneiv_clean/fields.py` docstring, `docs/cycloneiv-address-spaces.md` 5.1 | CORRECTED | only calc groups (LAB / MEAB / MAC) carry a BLOCK_INFO and are base + offset; std / dumb / stlmap groups store ABSOLUTE addresses (tag 0 CRAM, 0xA CFF, 0x88 option, 0x84 DPRIO): 95,957 CRAM bits of those groups were unclaimed, now claimed (`scripts/cycloneiv_clean_unclaimed_map.py`) | `docs/cycloneiv-clean-hardblocks-reversing.md`; HIO/VIO key-1 lists are bases for their calc groups only | `ASMDB_BLOCK_INFO::calculate_bits_traditional` libdb_asmdb 0x8e8a4 (applies only to the calc group's BLOCK_INFO) |

## Cyclone V (PARKED by Dan 2026-10-30: no fixes, no Ghidra work)

| ID | Claim | Where stated | Status | Evidence | Open | Reversing |
|---|---|---|---|---|---|---|
| V-G1 | PRAM address reversal `A = N-1-L` | `docs/cyclonev-clean-pram.md` Open | PARKED | found against the Mistral oracle, not vendor code; `PGMIO_F2P::make_cff_frame` decompile failed (thunk through a GOT pointer, `analysis/cv/pgmio_cff.c`) | derive from vendor code | `PGMIO_F2P::make_cff_frame` libpgm_pgmio 0x14a900 (unresolved) |
| V-G2 | Strip sizes / order / `fs` | `docs/cyclonev-pram.md` geometry, `docs/cyclonev-clean-pram.md` | PARKED | from Mistral `cvd` tables and `scripts/cyclonev_native_tables.py`; not in any vendor file read | derive from vendor code | as V-G1 |
| V-G3 | Die 0x13 geometry | `docs/cyclonev-pram.md` | PARKED (UNVERIFIED) | CRC- and claim-validated only; no Quartus pair | | |
| V-G4 | IO fields (GPIO, LVDS) name / position | `docs/cyclonev-pram.md` | PARKED | CSV names a subset (27 % / 12 %); no proven BINDEX -> bit map | | |
| V-G5 | devxml models | `docs/cyclonev-clean-pram.md` | PARKED | encrypted wrappers (`acef0100`); no key work | | |
| V-G6 | Every statement of `docs/cyclonev-pram.md` and `docs/cyclonev-native-decoder.md` field positions | those files | PARKED, label: ORACLE-ONLY (Mistral-derived) | tables are Mistral-sourced (`docs/cyclonev-native-decoder.md` line 10, 117) | relabel when work resumes | |
| V-F1 | "Cyclone V `.enc` files are encrypted" | none stands (`docs/cyclonev-vendor-data.md` states plain zlib after an 8-byte header) | CORRECTED (docs only) | `78 9c` after `ac0f010000000000`, `zlib.decompress(data[8:])` | | |

## Banned patterns

```errata-banned
# regex<TAB>reason ; allowlist applies per file below
-\s*dy\s*\+\s*23	E-A3 negated dy with +23 constant
dy negated	E-A3
\+ 23 constant	E-A3
dx \* 6154 \+ dy \+ 3	E-A3 pool +3 not in oracle
plane frame - asm frame = \+43	E-A3
FX\[X\] - 61	E-A4 / E-C2
plane_frame = FX\[x\] \+ 17	E-C2 AFX mirror
plane_v = 6344 - asm_v	E-C2
Plus 2 option bits: JTAG	E-A1
Function of any option bit: not decoded	E-A2
(?<!\d)0 of 160 bits decoded	E-A2
Entry roles: expected 1 iff `b0 == \+1`	E-J1
Not decided by the flags: 3-groups	E-L1
Y mod 4 in 20,295	E-C1
pooled X mod 8 tables, 150 \+ 61	E-C1
zlib header `78 da` at byte 117	E-F1
```

```errata-allow
docs/reversing-errata.md
docs/cycloneiv-retired-coordinate-model.md
tests/test_errata.py
```
