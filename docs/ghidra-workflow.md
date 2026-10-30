# Ghidra workflow for the Quartus libs (#165, #168)

Goal: names, struct layouts and notes found once stay applied to the Ghidra project; later agents start from them. Static analysis only (#165).

## Layout

| What | Where | Tracked |
|---|---|---|
| Ghidra project `quartus` (all libs below, analysed) | `vendor-analysis/altera/ghidra-project/` | no (gitignored, vendor-derived) |
| Name files | `reference/ghidra/{functions,globals,structs,notes}.tsv` | yes (names / offsets / types only) |
| Driver | `scripts/ghidra_apply_names.py` | yes |
| Ghidra scripts | `scripts/ghidra/{ApplyNames,ExportNames,DecompNames,StringXrefs}.java` | yes |
| Struct miner | `scripts/ghidra_mine_serializers.py` | yes |
| Decompile / string-xref output | `vendor-analysis/altera/analysis/ghidra_out/` | no |
| Logs | `tmp/logs/ghidra_apply_names.log` | no |

- Libs in the project: libcomp_asm, libcomp_asm2, libcomp_asmcc, libcomp_asmgx, libdb_asmdb, libddb_dev, libddb_dygr, libddb_dstr, libpgm_pgmio, libpgm_npcf, libdb_pdb.
- Image base of every lib is 0x100000: TSV addresses are ELF vaddrs (= `nm` addresses); Ghidra shows vaddr + 0x100000. Old decompile dumps under `analysis/` carry the Ghidra form.

## Start (new agent)

- Project missing: `python3 scripts/ghidra_apply_names.py import` (about 15 min, once; `import <lib>` adds one lib).
- Apply names: `python3 scripts/ghidra_apply_names.py apply` (idempotent; report in `tmp/ghidra/apply_report.tsv`; summary line per lib `ok=N fail=M`).
- One `analyzeHeadless` at a time (project lock). Do not open the project in the GUI while a headless run is active.
- GUI: `ghidra`, open `vendor-analysis/altera/ghidra-project/quartus.gpr`; structs live under `/pluribus` in the Data Type Manager; bookmarks category `pluribus`.

## Query

- `... decomp <lib> <pattern|0xVADDR> ...` : decompile functions whose full name contains the pattern (or at the vaddr) -> `ghidra_out/`.
- `... strings <lib> <regex>` : defined strings matching the regex with the functions that reference them (string-xref naming).
- Search `nm -C` dumps in `vendor-analysis/altera/analysis/nm_*.txt` first; libs carry full symbol tables, so most functions are already named. The gaps are data globals, struct layouts, semantics.

## Add a name (every finding, when found)

- One row per fact in the matching TSV, tab separated, `#` header lines ignored:
  - `functions.tsv`: lib, vaddr or symbol, name, signature (C prototype or empty), source, comment (plate comment).
  - `globals.tsv`: lib, vaddr or symbol, name, type, size, source, comment (EOL comment).
  - `structs.tsv`: lib, struct, size, offset, field, type, comment, source (one row per field; types as Ghidra parses them: `int`, `byte[24]`, `pointer`).
  - `notes.tsv`: lib, vaddr or symbol, kind (`plate` | `eol` | `bookmark`), text, source.
- `source` = issue / doc / script that proved it (`#168`, `docs/cycloneiv-clean-io.md`, `serializer:asmdb_ser.c`). A row with no source is rejected by `check`.
- Only names, offsets, types, short comments. No decompiled bodies, no binaries, no hashes, no `/mnt` or `/home` paths (`check` rejects those).
- `python3 scripts/ghidra_apply_names.py check` validates shape without Ghidra; `apply` loads it into the project.
- Names found interactively in the GUI/headless: `... export` writes user-defined names to `tmp/ghidra/export.tsv`; copy the rows into the TSVs and add the source.

## Struct mining from PDB serializers

- Every `X::operator<<(PDB_SEGMENT_TEMPLATE&)` lists `m_<field>` names with `this + offset`: a free member table.
- `python3 scripts/ghidra_mine_serializers.py <lib> <decomp.c> ...` rewrites the `serializer:*` rows of `structs.tsv` (other rows kept). Name strings referenced as `LAB_`/`DAT_` are read from the lib file; a label inside a string means the next string.
- Types are coarse (vtable slot: 0x48 i32 delta, 0x40 u16, 0xb8 bool, 0x88 enum i32; `byte[N]` = container, N = gap to next field).
- Serializer call offsets are vtable slot + 0x10 (vptr points past offset/typeinfo): +0xe0 serialize_begin, +0xe8 serialize_end, +0x20 xfr_new_array, +0x28 xfr_stl_ptr, +0x30 xfr_ptr, +0x48 xfr_int_delta, +0x40 xfr_short_delta, +0x88 xfr_int, +0x80 xfr_short, +0xb8 xfr_bool (libdb_pdb PDB_SEGMENT_READER vtable).

## Rules

- Rename only with evidence; put the evidence in `source`. A wrong name is worse than none.
- Re-applying must not change anything (apply is by address; same name and type are skipped).
- Findings and open questions go to the issue (#168 for IO), not only to a TSV.

## Batch / xref / class-recovery tools (#169)

- `... batch <lib> <re:regex|0xVADDR|substr> ...`: decompile every matching function to `ghidra_out/cache/<lib>/<vaddr>_<name>.c`; existing files are skipped (re-run is cheap). Script `scripts/ghidra/DecompBatch.java`. Example: `batch libcomp_asm 're:^ASM_\w+::(process_atom|process_end_of_phase)$'` (1,030 functions, ~1 min).
- `... xrefs <lib> 0xVADDR ...`: references to an address and to address+0x10 (vtable slot 0) -> `ghidra_out/<lib>_xrefs.tsv` (`AddrXrefs.java`). Empty for ASM_* vtables: vtable stores are `lea` of the symbol, found by text search of `objdump -d -C` instead.
- `scripts/cycloneiv_clean_class_objects.py <lib> [--dump CLASS]`: static instances of a class from `.rela.dyn` RELATIVE addends = vtable + 0x10. ASM_* processing classes have none (created by `new` in the arch-group factories).
- `scripts/cycloneiv_clean_class_bind.py`: factory switch (jump tables + cmp/je cases) -> class per group type; ~1 min, needs `objdump`.
- Decompiler caveats: in `mux_select` calls `(uint)param_1` is the first argument as decompiled (the class instance in the process_atom functions read; signature parse unverified); noreturn `operator_new` truncates factory bodies (read the disassembly).
