# Cyclone IV GX non-LAB blocks: assembler class -> group binding and address rule (#169)

Static analysis of Quartus 25.1 (`libcomp_asm`, `libcomp_asmgx`, `libdb_asmdb`), EP4CGX150, measured 2026-10-30. Vendor-derived only.
Code: `lifters/cycloneiv_clean/hardblocks.py`, table `lifters/cycloneiv_clean/class_groups_table.json` (every row `source` = factory@vaddr + case).
Scripts: `scripts/cycloneiv_clean_class_bind.py`, `scripts/cycloneiv_clean_asm_classes.py`, `scripts/cycloneiv_clean_unclaimed_map.py`. Tests: `tests/cycloneiv_clean/test_hardblocks.py`.
Owned elsewhere (not touched): IO value encoders (`io*.py`, `options.py`), routing flags (`tracer.py`, muxsel, bim, lab_control, clocks), M9K / MAC / PLL modules.

## 1. Findings

- Class -> group binding is in the factories, not in the classes.
  - `ASM_ASMDBIO::search_for_{io,le,lab,pll,oct,option_register,clockspine,cdr,hssi,dll,tsd,unvm,osc,adc}_arch_groups`, `asm_search_for_a5_serdes_dpa_arch_groups` (libcomp_asm), `asmgx_search_for_arch_groups` (libcomp_asmgx).
  - Each switches on `group + 0xc` (ASMDB_ARCH_GROUP_TYPE) and `new`s the `ASM_*` processing class. Case value = group type enum.
  - Class name == group name only for 317 of 1,012 rows; the other rows (e.g. PLL, GX) need the switch.
  - Validation: 13 of 13 option groups pair-confirmed in `options_table.json` reproduce their `group_type` (test); `ASM_IO_USE_BUS_HOLD` = 165 equals the earlier decompile finding.
- Address rule (`ASMDB_BLOCK_INFO::calculate_bits_traditional` libdb_asmdb 0x8e8a4; all 8 BLOCK_INFOs of IV GX have empty icd / bcm strings, so this is the only branch):
  - CRAM: `(off / ram_cols + hi) * ram_cols + off % ram_cols + lo` = `off + hi * 6154 + lo`, (hi, lo) from list key 1 element i.
  - CFF (tag 0xA): `off + list3[i]`. Markers 0xC.. pass unchanged.
  - Applied to calc groups only (they hold the BLOCK_INFO pointer). std / dumb / stlmap groups already store absolute addresses: CRAM tag 0, CFF 0xA, option 0x88, DPRIO 0x84.
  - Corrects "HIO / VIO / PLL / clock / GX / HSSI offsets are relative" (errata E-N1). HIO / VIO key-1 lists are bases for calc groups only; their std / dumb groups were never base + offset.
- Group objects are created per class in the factories; classes have no static instances and no `ASM_X::ASM_X` symbols (vtable store inline). `ASM_MODEL_GENERATOR_YGR::create_models` (0x101f66) registers only models (CDB_NODE_MODEL_YGR, CHAIN_AND_CLA_MONITOR_YGR, FINP_CZAR_YGR, GID_MONITOR).
- GX transceiver settings (604 GX_* group names, blocks GX_RX_PCS / TX_PCS / RX_PMA / CMU / TX_PMA / CALIBRATION / HSSI_PCIE_HIP / HSSI_STRIP):
  - Not written by libcomp_asm classes. Written by the generic CGA classes of libcomp_asmgx (`ASMGX_CENTRAL_CGA_ENUM`, `_CGA_BOOL`, `ASMGX_PMA_CGA_ENUM`, `ASMGX_PLL_CGA_INT`, ...), 143 group types bound by `asmgx_search_for_arch_groups`; model class for IV GX = `ASMGX_HCXIV_MODEL` (process_atom 0x8075e).
  - `ASMGX_CENTRAL_CGA_ENUM::process_atom` (0x4c33a): CGA parameter id chosen by group type (0x40 for 0x45c / 0x658, 0x84 for 0x438, 0x43 for 0x477, 0x7e for 0x64e / 0x64f); the enum ordinal goes straight to `mux_select`.
  - Open: ordinal -> setting-name table per CGA enum (QTL enum vtables `PTR__QTL_ENUM_TYPE_001d9508..9588`), the per-group walk of the other 3,460 asmgx cases (shared stubs, not bound), HCXIV port maps.

## 2. Counts (2026-10-30)

| item | count |
|---|---|
| ASM_* classes with process_atom / process_end_of_phase / process_beginning_of_phase (libcomp_asm, asm2, asmgx, asmcc nm) | 778 |
| factory rows (group enum -> class), 18 factories incl. 1 asmgx | 1,012 rows, 388 distinct classes |
| classes bound to a group present in this die's asmdb | 110 |
| of those: pair-confirmed (value map known) / placed (address known, no value map) / grouped (no bits) | 27 / 71 / 12 |
| classes with no walk group (other families, libs asmio / asmram / asmmac / asmpll not yet in the Ghidra project, GX through asmgx) | 668 |

- Per block (bits of bound classes): LAB 11,353,680 CRAM (14 of 20 classes pair-confirmed); FAST_PLL 2,516 and GENERAL_PLL 2,504 (CFF + CRAM, 0 pair); CLKBUF_GCLK 1,898; CONTROL 192; OCT_CALIBRATION 180; DEVICE 30 (13 of 13 pair).
- Absolute-address groups, new CRAM bits claimed (not in asm.ddb, default list, LAB / MEAB / MAC groups): HIO 23,711; VIO 38,010; HSSI_STRIP 10,275; HSSI_PCIE_HIP 11,550; GX_TX_PCS 5,948; GX_RX_PCS 1,852; FAST_PLL 840; GENERAL_PLL 420; CLKBUF_GCLK 1,128; GX_CMU 984; GX_RX_PMA 896; CONTROL 192; OCT 96; GX_CALIBRATION 55.
  - Total +95,957 CRAM bits: claimed 26,385,923 -> 26,481,880; unclaimed 12,655,053 -> 12,559,096 of 39,040,976 (32.2 %).
  - CFF / option / DPRIO addresses of the same groups (DEDICATED_CLOCK 50 + 40 CFF, FAST_PLL 2,034 CFF, GX 0x84 DPRIO) are listed by `hardblocks.absolute_bits`; their values are not decoded here.
- Where the 12.56 M unclaimed bits sit (`tmp/cycloneiv_clean/unclaimed_map.json`): LAB tile 5,862,467; M9K tile 6,098,088; MUL tile 195,884; pre-column / IOL / bands ~0.3 M. No remaining asmdb group places them: LAB and M9K residue is outside every calc group offset list (M9K owner: RAM content is 9,216 of ~20,500 bits per site; see M9K agent).

## 3. Not decoded (ranked by undecoded CRAM bits)

- LAB / M9K residue 12.0 M: no vendor record names them (not hard-block groups). Needs the RCF / ddb element for the tile, not an ASM_* class.
- Value maps of the placed LAB classes: LE_LUT_INPUT 6,589,440 bits, LAB_PIA_TO_INPUT 411,840, LE_USE_CARRY / REGISTER_FEEDBACK / REG_CASCADE_ARM 149,760 each (address known; selection value -> bit pattern is the asmdb mux, parameter -> value is the class `process_atom`).
- HIO / VIO / CLKBUF / DEDICATED_CLOCK / PLL / CONTROL CFF fields: IO agent and PLL agent own the value maps.
- GX / HSSI (~60 k absolute bits): through asmgx CGA classes (section 1).
- Classes of libcomp_asmio / asmram / asmmac / asmpll: not in the Ghidra project (`import` them first); factories `asmio_/asmram_/asmmac_/asmpll_search_for_arch_groups` are PLT stubs.
