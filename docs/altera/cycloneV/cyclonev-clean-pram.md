# Cyclone V clean PRAM (CFF) tables, vendor sources only (2026-10-30)

Re-derivation of the PRAM (CFF, peripheral config) layout without Mistral tables or old pluribus constants.
Code: `lifters/cyclonev_clean/` (`ddb.py`, `asmdb.py`, `pram.py`), `scripts/cyclonev_clean_pram.py`, test `tests/cyclonev_clean/test_pram_vendor.py`. Log `tmp/logs/cyclonev_clean_pram.log`.
Env: `PLURIBUS_QUARTUS_DEVINFO` = `quartus/common/devinfo/cyclonev` of a Quartus Prime Lite 25.1std install; `PLURIBUS_MISTRAL_ROOT` only for `compare`.

## Accepted inputs

| # | Input | Used for |
|---|---|---|
| V1 | `cyclonev_<die>/ddb_cyclonev_<die>_asmdb.ddb` (7 dies), container per `cyclonev-ddb-format.md` | die header, per-block CFF placement |
| V2 | static decompile of `libdb_asmdb.so` (`ASMDB_DIE`, `ASMDB_BLOCK_INFO` `operator<<`; `ASMDB_BLOCK_INFO::calculate_bits_*`, `get_block_data`) | record field order; list keys 3..7 = CFF offsets (`asmdb_offset_cache.cpp`) |
| V3 | `quartus_pgm`-side `.ddb` (`*_pcf.ddb`, `*_npcf.ddb`) | inspected; no PRAM strip data found |

## Banned inputs

- Mistral `data/` and `libmistral/` tables, `scripts/cyclonev_native_tables.py`, `cyclonev_pram_core.py`, `cyclonev_pram_decode.py` field tables, `cvd` pram sizes.
- Oracle use is confined to `scripts/cyclonev_clean_pram.py compare` (labelled ORACLE); nothing it reads feeds the library.
- Not touched: `devxml/b2b/cyclonev/*.xml`, `devxml/cag/cyclonev/bcm_*.xml` (encrypted wrappers, `acef0100` header; no key work), CRAM of any image.

## Derivation

- asmdb body = `ASMDB_DIE`: arch byte, `num_bits`, `num_cff_bits`, `num_unvm_bits`, `num_option_reg_bits` (u32), 4 strings, then maps/vectors.
  - `num_cff_bits`: e50f 51,101; d6_gtf150 113,922; gx25f 54,083; gt75f 90,162; gt300f 130,828; sx50f 80,505; sx120f 99,574.
  - e50f and d6_gtf150 equal the PRAM bit counts read from cleartext images (`cyclonev-pram.md`); same number found independently.
- `ASMDB_BLOCK_INFO` records are found by their address-space string `a : b : nseg : size...` (u32 length prefix), followed by version string, ICD block name, `m_block_lists` (count; per entry key u32, flag byte, count u32, int32 values).
  - Space `0 : 0 : 1 : 832` = one segment of 832 bits (fPLL); `0 : 0 : 4 : 836 : 256 : 256 : 256` = DQS16, 4 segments.
  - Segment j uses list key 3+j (`get_block_data` loop 3..7).
- List values are delta-coded over instances (first absolute), arithmetic mod `num_cff_bits`. Segment j>0: first value is relative to segment j-1 of instance 0.
  - Chosen by the vendor-only check: all extents of a die tile the CFF space with 0 overlap. Alternatives (per-list absolute, any size/key permutation, segments relative to segment 0) leave 2,292 to 7,301 overlapping bits on e50f.
- Extent = `size` bits ending at address A (highest), bit b at `A - b`.
- Result, vendor tables alone (`stage tables`): extents tile the space with 0 double claims.

| die | num_cff_bits | extents | bits claimed |
|---|---|---|---|
| e50f | 51,101 | 182 | 51,101 |
| d6_gtf150 | 113,922 | 298 | 113,922 |
| gx25f | 54,083 | 154 | 54,083 |
| gt75f | 90,162 | 231 | 90,162 |
| gt300f | 130,828 | 346 | 130,828 |
| sx50f | 80,505 | 216 | 80,502 |
| sx120f | 99,574 | 269 | 99,571 |

## Oracle comparison (ORACLE: Mistral `pram.txt` + `cvd` strip sizes; run 2026-10-30)

- Oracle position converted to A by `A = N-1-L`, `L` = strip-concatenated serial position (convention found with the oracle, see Open).
- Per extent (A_high, size): matched 1,696 / (matched 1,696 + missing 0 + extra 0 + wrong 0) = 100 %; bits 620,169 / 620,175.
- The 6 bits (sx50f 3, sx120f 3) are unclaimed on both sides.
- Vendor extents straddling an oracle strip boundary: 0 (all dies).
- Block label agreement (hand map vendor ICD name to Mistral label, comparison only): not a score; SX dies have HPS blocks outside the map.

## Open (not assumed)

- Strip sizes / strip order / frame size (`fs`): not in V1-V3. Searched `*_pcf.ddb`, `*_npcf.ddb`; the image container fixes `mpram`, not per-strip sizes. `to_strip_pos` therefore takes strip sizes as an argument.
- `A = N-1-L` (reversal): found against the oracle, not yet derived from vendor code. `PGMIO_F2P::make_cff_frame` decompile failed (exception-table noise).
- In-block field positions (PLL M/N/C, GPIO drive, DQS16 internals): the parameter records are present in the same asmdb body (`ASMDB_PARAM_MASTER_*`, `ASMDB_ARCH_GROUP_*`, `m_export_port_to_bit_map`, 656 `pl_fpll_ip_*` names) but their object-reference serialization is not parsed. Field decode and image decode (cleartext PRAM, `docs/altera/cycloneV/cyclonev-pram.md`) are not redone here.
- `devxml` block models are encrypted; the unencrypted CSVs (`zb8/zb16`) have no proven BINDEX-to-bit map (`cyclonev-pram.md`).
- Instance order in the vendor lists is not positional (fPLL list order = strips 0, 10, 3, 7); instance identity to tile coordinates is not derived.
