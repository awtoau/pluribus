# Cyclone IV GX decoder rules ledger (#165, 2026-10-30)

Ledger: `reference/rules.tsv` (97 rows). Test: `tests/test_rules_ledger.py` (parse, status on every row, every clean-tree module / JSON table / module-level rule table named, SPECIMEN_ONLY queue shown as xfail with count).
Columns: id, module, rule, derivation (CODE | SPECIMEN | MIXED), source (function@vaddr / vendor data file, plus the chain specimen -> group -> class -> function where one exists), corpus_check (matched / missing / extra / wrong and held-out set), status, notes.
Method (Dan): single-feature pair diff = exact label -> asmdb group -> group-type name -> `class_groups_table.json` binding -> ASM_* class -> process_atom / ctor / value table -> check the code reproduces the value -> bit pattern.
Static analysis only. Ghidra read-only snapshot + readable export + cached decompiles; main project never locked.

## Counts by status
- CONFIRMED_BY_CODE: 63
- SPECIMEN_ONLY: 32 (about 10 of these are not decoder rules: oracle plumbing, labels, emission conventions: L-002 L-003 L-004 L-011 L-016 T-005 E-007 I-006 and similar)
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

## Open SPECIMEN_ONLY queue, ranked by impact on the image lift
- S-01 LUT INIT pin permutation / bit order (D-002, T-006, E-001): every LUT (2,396,160 INIT bits). `ASM_LE_LUT_FUNCTION::process_atom`@0x16b05c writes `cut_le_util` vfn0(atom) (mask with pin swap); `CUT_ATOM_LE::create_util` libdb_cut@0x2fb590 allocates a 0x20-byte object for family 0x30; class name and vtable slot 0 unresolved (decompile stops at operator_new). Next: vtable of that object (vtables.tsv / RTTI), slot 0 body.
- S-02 Register-used claim (R-002, R-003): 38,772 claims on the image. Unused-path value in `ASM_LE_REG_OUT_YGR::process_end_of_phase`@0x16e326 is written only under the LAB-model predicate (vtbl +0x50) with value (comb used)+1; predicate default unread, so "unused path reads 0" is unconfirmed.
- S-03 Skip-half-LAB flag for family 0x30 (F-016): `ASM_MODEL_GENERATOR_STINGRAY::create_models`@0x10a830 truncated at operator_new; carry monitor registered for Stingray not visible. Specimen: LE 8 <- LE 7 in 1,879 / 1,879 links (supports 0).
- S-04 IO direction patterns, joint IOST / strength / clamp states, termination, unused-pin states, registered-IO CRAM groups (I-004 I-005 I-006 I-007 I-009 I-010): writers located (`ASM_IO_PIN_MODE::process_atom`@0x29101c, `ASMIO_MIO_TERMINATION_CONTROL_SELECT`@0x74d96, `ASMIO_MIO_SELECT_INPUT_REGISTER_MODE`, `ASMIO_MIO_USE_CLR`), value logic not read.
- S-05 Drive current -> strength value (I-003): `ASMIO_MIO_SET_PULLDOWN_STRENGTH`@0x5def4 / PULLUP@0x5e18e write CGA parameter 0xf6 as is; the scaling is fitter-side. Not derivable from the assembler; stays specimen / fitter-side.
- S-06 BIM index of pad pins (B-005; 1,305 HIO LI -> BIM pips): not in routing.ddb (E-R4); search the placement side.
- S-07 PLL placement and defaults (P-002 PLL_k -> (type, path), P-004 unused counter 15 / 15 / 3, P-006): libcomp_asmpll location -> index and counter default branches unread.
- S-08 M9K / MAC (M-002 M-006 M-007 M-010 M-011): owned by the M9K / MAC agent; recorded only, posted to #169.
- S-09 Tracer default-bit and structural clock edges (T-003 120 edges, T-004 145,283 edges): no code reading of default-list conduction.
- Not rules (leave as SPECIMEN_ONLY, no action): L-002 L-003 L-004 L-011 L-016 T-005 E-004 E-007 I-006.
