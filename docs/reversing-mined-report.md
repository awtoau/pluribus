# Mined reversing facts (#165, #169)

Conditions: 2026-10-30, Quartus 25.1, static analysis, EP4CGX150. Data: `reference/ghidra/mined.tsv` (kind, lib, vaddr_or_symbol, fact, source, verified, status).

## Sources scanned

- 267 subagent transcripts (226 MB; name@vaddr, struct offsets, table addresses, retractions) incl. 66 task-output symlinks.
- 288 `SubagentHandback` reports (1 MB) and the lead session transcript.
- Issue comments #165 #167 #168 #169 #171 #172 #173 #174 (#175 has no comments).
- Gitignored workspace: `analysis/ghidra_out`, `analysis/readable`, `analysis/decomp` (read for verification).

## Counts

| | n |
|---|---|
| mined.tsv rows (candidates) | 135 |
| verified yes (nm exact name@vaddr, ELF bytes, or decompile text) | 126 |
| partial | 6 |
| not verified | 3 |
| rejected / retracted / unverified-claim | 1 / 5 / 2 |
| status NEW to the TSVs / KNOWN already | 115 / 8 |
| rows by kind | function 93, enum 12, rule 6, finding 6, retraction 6, table 5, negative 4, struct 3 |

- Merged: `functions.tsv` +93 rows (all resolve by `nm -C`), `globals.tsv` +14 rows; `structs.tsv` and `notes.tsv` untouched (struct sizes unknown; plates are in the function comments).
- Ledger (`reference/rules.tsv`): 0 status changes. 4 citation fixes (L-009, L-012, O-001, F-013), 2 notes extended (L-002, M-007). CONFIRMED_BY_CODE / SPECIMEN_ONLY counts unchanged.
- Errata: E-U1..E-U4 added.

## Conflicts found

- E-U1: `silent_set_bits` 0x17e50 / `set_bits` 0x18000 are PLT stubs (`.plt` 0x17810..0x192e0, `jmp *GOT`). The "twin / overload" claim is wrong; real functions 0x1a240 / 0x1aca0.
- E-U2: `look_up_signal_polarity`@0x1563ae is `ASM_SINGLE_LAB_MODEL_BASE`, not `ASM_LAB_MODEL_BASE`.
- E-U3: PLL_6 / PLL_7 "not placeable in package" contradicts the handbook (#175).
- E-U4: pgmio functions cited in Ghidra form resolve to other symbols (ELF 0x53be30 is `__tcf_0`).
- Rejected: `ASM_LAB_ENABLE_SYNC_SIGNALS` at 0x15f628 / 0x15f9e2 (real 0x15feb6).
- Unverified: CUT_RAM_UTIL family-0xc dispatch to `CDB_ATOM_YGR_EC` (thunk only); "no inversion on any IO group" vs ledger F-001 / O-003.
- Not conflicts: `DEV_ELEMENT_DESC::operator<<`@0x15afa0 and `DEV_ELEMENT_DESC_BODY::operator<<`@0x168f60 are two classes.
- Tags still citing the stub addresses (owner files, not edited): `docs/cycloneiv-address-spaces.md`, `docs/cycloneiv-clean-options.md`, `docs/cycloneiv-clean-io.md`, `lifters/cycloneiv_clean/cycloneiv_io.py`, `scripts/cycloneiv_clean_options_build.py`, `options_table.json`.

## Top 20 new facts for the open areas

M9K control
1. `ASM_SINGLE_RAM_MODEL_YGR_MEAB::cache_ram_mode`@0x4a624: port flag vectors at model+0x240 (A) / +0x250 (B); port-B path clears BIDIR_DUAL_PORT and all width flags, restores the ones in the B vector. Width lives in the `RAM_BY*` flags of the atom.
2. `RAM_BY*` flag bits: 14 BY1, 15 BY2, 16 BY4, 17 BY8, 18 BY16, 39 BY32, 40 BY9, 41 BY18, 42 BY36, 85 BY5, 86 BY10, 87 BY20, 88 BY40.
3. `ASM_RAM_NEW_DATA_MODE`@0x1f6fe: value 1 iff (bit 77 | 78 same-port feed-through NEW) and (bit 4 | 30 | 32).
4. `ASM_RAM_IS_ROM_ONLY`@0x1fa72 = rom(port A) AND rom(port B); `ASM_RAM_REG_DATA_OUT`@0x7de60 = flag bit 9.
5. `ASM_RAM_MS_DATA_INPUT`@0x6663e: port-input mux value = RE line index of the source plus PIA / extra-line offsets by RE type (value table still open, M-007).
6. `CDB_RAM_FEED_THROUGH_MODE`: 0 OLD, 1 NEW, 2 DONT_CARE, 3 CONSTRAINED_DONT_CARE, 4 NEW_A_OLD_B (read-during-write semantics for the byte-enable gap).
7. Device-DB 2D int tables `RAM_SINGLE_PORT_CONFIG` / `SIMPLE_DUAL` / `BIDIR_DUAL` / `SIMPLE_QUAD` (slots 2..5 of `DEV_ELEMENT_DESC_2D_INT_DATA`): the allowed-config source per element.

MAC modes
8. `ASM_MAC_ROW_DATA_INPUT`@0x4e0d6 writes only a LAB-line RE index (E-P4 stands); `process_atom_mac_mult/out` (0x5e232 / 0x5e42e) add no bit tables.
9. `ASM_MAC_SIGN_INVERT::process_end_of_phase` writes `look_up_port_stats(model, 4, signal)` per MAC: the code source for M-010 (not yet decoded).

PLL connectivity / values
10. `get_cp_and_lp_value`@0x1b1e2a returns the position of the parameter in a row of a PLL element 2D int table (slots 6 charge pump, 7 loop filter R, 8 loop filter C).
11. `CDB_PLL_PARAMETER_TYPE` / `COUNTER_PARAMETER_TYPE` enums (counter bypass / odd-even / high / low / nominal / SS).
12. `set_2d_int_data_from_string`@0x85000: 2D tables can be loaded from text (consistent with the `*.pll` tables, P-005).

IO / config pads
13. `PGMIO_BITFIELD::set_auto_usercode`@0x3b6540 -> `compute_checksum`@0x3b6240 (no package input; K-002).
14. `write_bitstream_by_location`@0x3b47f0 has only ICB option-data callers; `write_sof_data`@0x5e5040 is checksum + memmove: sof CRAM payload = bitfield bytes.
15. `reverse_address_counter_frames`@0x43be30: rbf-side per-device range reversal (0x1c-byte records).
16. `ASMIO_MIO_TERMINATION_CONTROL_SELECT::process_atom`@0x74d96 located (value written as fitter CGA integer).

BIM / clock buffers
17. `DYGR_ROUTE_BLOCK_INTERFACE{,_NODE,_CONNECTION}::operator<<` @0x2cfca0 / 0x2c7190 / 0x2c6fd0 (28 interfaces + 983 nodes).
18. `ASM_RE_PROXY::get_first_useful_re_source`@0x2cc36 skips the BIM index; `mux_select` takes the LI index.
19. `ASM_CLKBUF_CLK_INPUT_SELECT_CYCLONEII::process_atom`@0x2fd9f8: value = CLKBUF_IN index.
20. `BOOL_ARE_PROGRAMMING_BITS_INVERTED` / `ONE_HOT_ENCODED` (element bool slots 4 / 3): per-element programming-bit flags in the device DB, candidate source for unexplained polarity cases.

## Verification method

- name <-> vaddr: `nm -C --defined-only` of 24 libs, ELF and Ghidra (+0x100000) forms tried; only exact-name matches accepted.
- Data tables: ELF bytes read (VIRTUAL_LAB_LINE tables, jump tables, `.rela.dyn` RELATIVE addends for enum name tables).
- Semantics: decompile text in `ghidra_out` / `readable` (no Ghidra project lock taken; no snapshot opened).
- Not re-run: agent inventory sweeps (negative rows), handbook text (E-U3).
