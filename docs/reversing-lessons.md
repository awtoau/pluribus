# Reversing lessons and recipes (#165, #168, #169, #171)

Static analysis only (#165). Tools: [ghidra-workflow.md](ghidra-workflow.md); names: `reference/ghidra/*.tsv`; wrong claims: [reversing-errata.md](reversing-errata.md); proven rules: [cycloneiv-rules-ledger.md](altera/cycloneIV/cycloneiv-rules-ledger.md) + `reference/rules.tsv`.

## Lessons (what stalled, what fixes it)

| # | Lesson | Fix in the tools |
|---|---|---|
| a | A library nobody imported stalled whole areas (libcomp_asmram, libdb_cut, libdb_cdb_atom_ygr, libatm_astr for `CDB_RAM_FLAG_ENUM`) | `scripts/ghidra_inventory.py` classifies every `linux64/*.so` + `quartus_*` -> `reference/ghidra/libs.tsv` (tier core / adjacent / no); `ghidra_apply_names.py import-core` imports all core libs. Name AND symbols decide: libatm_astr has 2 strict symbol hits but is the stingray atom string lib |
| b | Single-writer Ghidra lock blocked decompile agents; snapshots go stale after imports | Main project = imports and typing only, then `snapshot <name>`; readers use `ro_proj()` (newest snapshot). Path published in ghidra-workflow.md. ELF-only tools (`ghidra_dump.py`, `ghidra_index.py`, `ghidra_trace.py`) need no Ghidra and never lock |
| c | Answers found by luck of search order (BIM in routing.ddb block interfaces; plain-text `*.pll` tables) | `ghidra_trace.py trace` returns the whole chain in one call; `ghidra_index.py strings-grep` / `data` search every lib; before reversing check `common/devinfo/**` for plain-text tables |
| d | pair label -> asmdb group -> group type -> ASM_* class -> writer -> ctor table was manual | `ghidra_trace.py trace <group>`; the factory binds a holder class for some groups (LE_REG_OUT_YGR -> ASM_LAB_ARCH_GROUP): the trace adds the `ASM_<group>` name-convention class |
| e | Decompile defects: wrong external declarations (`mux_select`), broken switch tables, virtual calls stopping at `operator_new`, duplicate overloads at two addresses | `extsigs.tsv` (mangled-name signatures applied to EXTERNAL stubs by `TypesPass`), `clearNoReturnNew`, `defects.tsv` + `ghidra_dump.py switch`, `ghidra_vcalls.py`, `twins.tsv` |
| f | Tables live in data (VIRTUAL_LAB_LINE ctor table, enum name tables); each agent re-extracted them | `ghidra_dump.py dump-table / dump-struct-array / ctor-tables` (ELF relocations resolved); `ghidra_dump.py emulate` for pure generators |

## Recipes

### What to import first
- `python3 scripts/ghidra_apply_names.py libs` lists core libs and import state; `import-core` imports the rest (8 per headless run, marker `tmp/ghidra/imported_<lib>`).
- Order of value for a new area: the `libcomp_asm*` writer libs, `libdb_asmdb` (groups/enums), the area's atom lib (`libdb_cdb_atom_ygr`/`_stingray`, `libatm_astr`), `libdb_cut` (legality / util classes), `libddb_dygr` (routing), then pgm libs (`libpgm_*`) for file formats.
- New lib found later: add it to `libs.tsv` tier core (edit `CORE` in `ghidra_inventory.py`), `import-core`, `snapshot`, `index-feed`, `ghidra_index.py build`.

### Find the writer of a group
1. `python3 scripts/ghidra_trace.py trace <GROUP_TYPE_NAME>` (or `enum:N`): prints group objects (class CALC/STD/DUMB/STLMAP, block type, sites, mux kinds, bit sample with address space), bound class + factory case, writer functions, vtable slots, constructor tables, readable file, ledger rows.
2. No bound class: the group is written outside the factories. `ghidra_index.py strings-grep '<GROUP_NAME>'` then `ghidra_index.py callers <fn>`; also `data '<GROUP_NAME>'`.
3. Read the writer: `ghidra_apply_names.py batch <lib> 0xVADDR` (snapshot), open `ghidra_out/cache/<lib>/<vaddr>_*.c`; value roles via `signatures.tsv` (`mux_select(this, site_index, value, streams)`).
4. Record: `functions.tsv` row with `source:`, a ledger row in `reference/rules.tsv`.

### Find a table
1. Named symbol: `ghidra_index.py data '<regex>'` (all libs), then `ghidra_dump.py dump-table <lib> <symbol|0xVADDR> ptr|u32|... [count]`.
2. Table copied by a constructor (no symbol): `ghidra_dump.py ctor-tables <lib> <Class>` lists every data block a ctor `lea`s; then `dump-struct-array <lib> --layout "0:u32,4:u32,..." --stride N 0xVADDR COUNT`.
3. Enum name table (debug strings): the function `*_get_debug_string`; the array of `char*` is a relocated pointer table: `dump-table <lib> 0xADDR ptr N`. Example: `CDB_RAM_FLAG_ENUM` 89 names in libatm_astr @0x185b800.
4. Pure function (value -> value): `ghidra_dump.py emulate <lib> 0xVADDR <maxSteps> A..B` (leaf functions only; `fault:call` = not a leaf).
5. Plain text first: `common/devinfo/**` (`*.pll`, pin files) before any binary.

### Resolve a virtual call
1. Decompiled `(**(code **)(*p + 0xNN))(...)`: `ghidra_vcalls.py annotate <decomp.c>` lists candidate targets per call; receiver `this`/`param_1` resolves to the file's class.
2. Known class: `ghidra_vcalls.py who '<ClassRegex>' 0xNN`; whole table `slots <Class>`.
3. Global utility objects (`cut_le_util`, `CUT_RAM_UTIL`): the dynamic class is chosen at run time; `ghidra_vcalls.py abstract '^CUT_ATOM_(CUDA|YGR|CYCLONEII)_LE$'` shows the slots where the families differ. Cyclone IV GX = YGR family (`CUT_ATOM_YGR_LE`, `ASM_LAB_MODEL_CUDA`).
4. Truncated body after `operator_new`: noreturn flag (cleared by `TypesPass` after re-typing); until re-decompiled read `objdump -d -C` around the call.

### Confirm a rule from a pair label
1. Pair spec (label, bit diff) -> `ghidra_trace.py trace addr:<bit>` (raw bit values in the asmdb muxes; block-relative groups store offsets) -> group.
2. `trace <group>` -> class + writer -> read the writer's conditions.
3. Rule agrees with the pairs: add `reference/rules.tsv` row (`CODE`/`MIXED`/`SPECIMEN`), cite `function@vaddr`; add a fact to `tests/test_reversing_facts.py` (tool command -> expected value).
4. Rule disagrees: errata row (`docs/reversing-errata.md`) + banned pattern; never leave the old text.

### Decompile defects
- Scan: `python3 scripts/ghidra_defects.py` (cache -> `defects.tsv`).
- Wrong external: add the real signature to `signatures.tsv` (one row per overload address), `ghidra_apply_names.py gen-extsigs`, then `types` in the main project and a new snapshot.
- Broken switch ("Could not recover jumptable"): `ghidra_dump.py switch <lib> <table> <count>` (case -> target); `scripts/cycloneiv_clean_class_bind.py` reads factories from machine code the same way.
- PLT stubs (0x17e50 / 0x18000 are stubs of 0x1a240 / 0x1aca0, E-U1): `twins.tsv`; cite the real function.

## Do not repeat
- Searching decompiled text with `grep` across 90 libs: use the index (`strings-grep`, `callers`, `func`).
- Hand-extracting a table per agent: `dump-table` / `ctor-tables`, then keep the numbers in a ledger row or test, not in a comment.
- Declaring a lib "has no such class" before `ghidra_inventory.py` has classified it.
