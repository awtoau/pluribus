# Cyclone IV GX decoder rules ledger (#165, 2026-10-30)

Ledger: `reference/rules.tsv` (98 rows). Test: `tests/test_rules_ledger.py` (parse, status on every row, every clean-tree module / JSON table / module-level rule table named, SPECIMEN_ONLY queue shown as xfail with count).
Columns: id, module, rule, derivation (CODE | SPECIMEN | MIXED), source (function@vaddr / vendor data file, plus the chain specimen -> group -> class -> function where one exists), corpus_check (matched / missing / extra / wrong and held-out set), status, notes.
Method (Dan): single-feature pair diff = exact label -> asmdb group -> group-type name -> `class_groups_table.json` binding -> ASM_* class -> process_atom / ctor / value table -> check the code reproduces the value -> bit pattern.
Static analysis only. Ghidra read-only snapshot + readable export + cached decompiles; main project never locked.

## Counts by status
- CONFIRMED_BY_CODE: 66
- SPECIMEN_ONLY: 30 (about 10 of these are not decoder rules: oracle plumbing, labels, emission conventions: L-002 L-003 L-004 L-011 L-016 T-005 E-007 I-006 and similar)
- CODE_CONTRADICTS: 0
- UNKNOWN: 2 (C-003 global-network clock inversion, I-012 VREF pad)
- Rows citing a vaddr from an earlier doc without a re-read here are marked in notes; re-read this session: F-001 F-007 F-010 F-011 F-012 R-001 R-002 B-004 I-001 O-003.

## Closed this session (candidate gaps)
- LAB_INVERT gi 5 = sclr (F-012): `ASM_LAB_MODEL_CUDA` ctor@0x165038 copies 9 VIRTUAL_LAB_LINE entries (20 B) from 0x3cd760; signal masks 4,2,4,2,0x40,0x20,8,8,0x40 = clk0 ce0 clk1 ce1 sload sclr aclr aclr sload2; line 5 = SCLR. The earlier citation (Titan table 0x3cda00, line 5 = clock) was the wrong table: errata E-T1. Not "dropped lines 5..8 by the SINGLE ctor": the CUDA table simply has no clk2 pair.
- LE_CLOCK_SELECT polarity (F-007): no polarity in that group; `ASM_LE_CLOCK_SELECT::process_atom`@0x16ba06 writes the LAB clock signal index (0/1); polarity is LAB_INVERT (F-012) and look_up_signal_polarity.
- ASM_LE_USE_REGISTER_FEEDBACK (F-010): `process_atom`@0x16c294 re-read, matches.
- Register-used / YGR mapping (R-001): `ASM_LE_REG_OUT_YGR::process_atom`@0x16e66a: gi 0/1 = RE type 0x2e with re_index%2 == gi, gi 2 = type 0xc; value = is_registered + 1.
- arch_value 0 / E-S2 (F-001): `ASMDB_ARCH_GROUP_DUMB::select`@0x78f4c re-read (bit = value==0 if arch 0, else value!=0), consistent with STD@0x7a3ac and 8/8 option groups (O-003).
- Mux classes 21 / 22 / 24 (B-004): `ASMDB_SIMPLE_BANK_MUX::select`@0x8bec8, `ASMDB_ENCODED_BANK_MUX::select`@0x8bfac, `ASMDB_RAM_MUX::select`@0x86bc4 / 0x8bdca (polarity-mux flip), `ASMDB_ARCH_GROUP_STLMAP::select`@0x7b28c. `asmdb_select` raises NotImplementedError for these classes; code read, decoder change left to the owner.
- Entry rule `lit/sel` (T-001): closed earlier, `get_bits_from_source_to_dest`@0x23bfe0.

## Closed in the second pass (2026-10-30)
- Mux classes 21 / 22 / 24 + groups 7 / 8 implemented in `asmdb_select` (B-004), tests `tests/cycloneiv_clean/test_asmdb_select_banks.py`. Class 21 is ENCODED_BANK (ddb type table), class 24 = STL_MAPPED_ENCODED (inherits ENCODED), class 22 RAM_MUX (polarity-mux flip; RAM_CONTENT has none).
- LUT pin permutation (D-002, T-006, L-018): family 0x30 util = `CUT_ATOM_CUDA_LE`; `get_assembler_lutmask`@0x2fc120 = four `invert_input` + complement, no permute; base `ASM_LUT_PORT_MAPPER` registered (identity). Errata E-T3. Arithmetic-mode sum / carry combination not re-derived (decompile control flow partly broken).
- Register-used unused-path rule (R-002): power-opt predicate on only for PDC extra effort (`get_pdc_setting` libcomp_asmcc@0x2d4fe) or `asm_always_optimize_power_for_unused_registers`; default compile off, unused path untouched.
- Carry monitor for 0x30 (F-015, F-016): `create_models`@0x10a830 registers none (`ASM_LAB_MODEL_CUDA` is called directly). F-015 moves back to SPECIMEN_ONLY, errata E-T2.
- IO (I-005, I-007): direction-dependent strength / clamp / termination values are fitter CGA parameters written as is; not derivable from the assembler, stay specimen.

## Open SPECIMEN_ONLY queue, ranked by impact on the image lift
- S-01 closed (see above).
- S-02 closed (R-003 decision logic stays ours: ambiguity is real).
- S-03 Carry-in source and skip-half flag for 0x30 (F-015, F-016): specimen only; no assembler check exists for Stingray.
- S-04 / S-05 IO joint states, strength, termination: fitter-side values (I-003, I-004, I-005, I-007), plus unread registered-IO CRAM groups (I-010) and unused-pin pull-up (I-009).
- S-06 BIM index of pad pins (B-005; 1,305 HIO LI -> BIM pips): not in routing.ddb (E-R4); search the placement side.
- S-07 PLL placement and defaults (P-002 PLL_k -> (type, path), P-004 unused counter 15 / 15 / 3, P-006): libcomp_asmpll location -> index and counter default branches unread.
- S-08 M9K / MAC (M-002 M-006 M-007 M-010 M-011): owned by the M9K / MAC agent; recorded only, posted to #169.
- S-09 Tracer default-bit and structural clock edges (T-003 120 edges, T-004 145,283 edges): no code reading of default-list conduction.
- Not rules (no action): L-002 L-003 L-004 L-011 L-016 T-005 E-004 E-007 I-006.
