# Cyclone IV GX clean pipeline: image annotations (#165)

Counts only. The table, the aliases and the annotated Verilog stay local (commercial RE). Image path only via env `PLURIBUS_DJI_IMAGE`.

## Store
- `schema.py`: `annotations` (one row per named block), `annotation_members` (physical id, kind, optional alias), `annotation_coverage` (counts per `coverage` run, `gate_run_id` of the latest `gate_runs` row).
- Lives in the family DB (`databases/cycloneiv/gx150.db`, gitignored). Existing DBs gain the tables via `scripts/migrate_family_db.py --apply` (now also creates absent declared tables).
- Physical ids are primary and never renumbered: `ff_X_Y_N`, `lc_X_Y_N`, `m9k_X_Y`, `mac_X_Y`, `pll_K`, `pad_BALL`, clock root `u_clkbuf_...`.
- Block id = kind + 3-digit counter. Kinds: SCR CRC CNT FSM SPI MEM MAC PLL IO DAT, plus CLK (clock domain, no logic members). Re-adding the same sorted member set (sha1), or the same kind + name, keeps the id.
- Tags: V traced (existing log / trace / ledger reference), I inferred, H hypothesis, U unknown. Coverage "named" = tag V / I / H; U is listed and counted separately.
- Evidence = `;`-separated `kind:ref`, kinds `log trace ledger json script issue doc`.

## Commands (`scripts/cycloneiv_clean_annotate.py`, log `tmp/logs/cycloneiv_clean_annotate.log`)
- `add --kind --name --claim --tag --evidence --members ids|file [--block ID]`: members file lines `physical_id[,alias]`.
- `list [--kind] [--tag]`, `remove --block ID`, `names [--out map.tsv]` (alias <-> physical).
- `check [--nl NL.pkl]`: exit 1 on any problem below.
- `coverage [--nl NL.pkl] [--no-record]`: share of FFs / LUTs / M9K / MAC in a named block, count by tag; records a row.
- `seed-image`: seeds from existing outputs only (`tmp/dji_patterns/patterns.json`, `tmp/dji_seed/*.json`, `tmp/cycloneiv_clean/image_clocks.json`); upsert, safe to re-run.

## What `check` rejects
- Missing evidence; unknown evidence kind; reference to a file that does not exist; `ledger:` id not in `reference/rules.tsv`.
- Tag V without an existing `log` / `trace` / `ledger` reference; a `log` / `trace` that names none of the block's FFs.
- Same physical id in two blocks (or twice in one); empty block; block id not matching its kind; stale member hash / count.
- Alias shared by two objects; alias equal to another object's physical id (or, with `--nl`, to any netlist signal); alias that is not an identifier.
- With `--nl`: member not in the netlist.

## Annotated emit (`scripts/cycloneiv_clean_annotate_emit.py IN.v`)
- Reads an existing flat / RTL Verilog file (emit.py and rtl.py untouched) and writes `tmp/annotated/IN.v`, `.names.tsv` (alias <-> physical), `.blocks.tsv`.
- One header of at most 3 lines (id + tag + name, claim, evidence) before the first line naming a member; blocks whose ids never appear go in a top index. U blocks get no header.
- Alias renames cover `lc_` / `I_lc_` / `co_` forms and the `m9k_X_Y_*` / `mac_X_Y_*` bus names. Unnamed logic stays under physical ids.
- Flat emit of the image (456 k lines): 719 named blocks, 717 anchored, 2 index-only (PLLs), 4.5 s.

## Image seed, 2026-10-30 (EP4CGX150, 36,993 FFs, 89,282 LUTs, 542 M9K, 87 MAC)
| tag | blocks | FFs | LUTs | M9K | MAC |
|---|---|---|---|---|---|
| V | 16 | 105 | 116 | 0 | 0 |
| I | 703 | 3,164 | 4,063 | 349 | 87 |
| H | 0 | 0 | 0 | 0 | 0 |
| U | 2 | 5 | 5 | 193 | 0 |

- Annotated coverage (V + I + H): FF 3,269 / 36,993 (8.84%), LUT 4,179 / 89,282 (4.68%), M9K 349 / 542 (64.39%), MAC 87 / 87 (100%). Recorded in `annotation_coverage` beside gate run 36.
- V (16): 7 LFSR/PRBS (SCR: PRBS15 x 3, PRBS11 x 4) + 1 CRC-16 group, each with a seed-trace json from `tmp/dji_seed/`; 2 PLLs and 6 clock domains with the `image_clocks` log.
- I (703): 267 counters / accumulators (2 of the 269 detector hits overlap an earlier block, skipped), 349 modelled M9K (one MEM each), 87 MAC (one each).
- U (2): the 5-stage unmatched linear group, and the 193 unmodelled M9K as one MEM block.
- Role hypotheses (test-pattern source, CRC over an M9K byte stream) sit in the V blocks' claim text as `H:`; they are not separate rows because a physical id may belong to one block only.
- Pending, not invented: SPI deserialiser / serial-input structure (`tmp/dji_spi/` holds probe scripts, no result yet), FX3 FIFO pad group, 317 shift chains, 262 sync-word candidates, M9K address buses (detectors give no member sets).
- No aliases yet; names from the board file stay in the local board file.
