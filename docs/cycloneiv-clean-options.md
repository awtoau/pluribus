# Cyclone IV GX (EP4CGX150) option register: decoded bit map (#169)

Static analysis of the vendor install only (authorised #165); no key / decrypt work. Builds: Quartus 25.1 `quartus_map/fit/asm/cpf` black box.
Measured 2026-10-30. Table: `lifters/cycloneiv_clean/options_table.json` (per-entry `source`), code `lifters/cycloneiv_clean/options.py`, tests `tests/cycloneiv_clean/test_options.py`.
Builders: `scripts/cycloneiv_clean_options_build.py` (table), `scripts/cycloneiv_clean_option_pairs.py` (pair builds). Context: [cycloneiv-address-spaces.md](cycloneiv-address-spaces.md) section 3.

## 1. Headline

- 160 option bits = 30 group bits + 35 forced + 95 default. Every bit is in exactly one class (0 unlisted).
- Function decoded: **30 / 160** (13 asmdb option groups). Missing: **130 / 160** (35 forced, 95 default: no group, no setting changed any of them).
- Group bits: 22 / 30 confirmed by a QSF pair (the setting flips the bit); 8 / 30 (POF id, 11-18) decoded from the assembler + 9 vendor sofs, no QSF setting reaches them.
- Encoder (`options.encode`) vs 197 pair builds: group bits 5,910 matched / 0 wrong; forced 6,895 / 0; default 18,715 / 0 (value bits, all builds).
  - Pair flips (spec vs reference): matched 74, missing 0, extra 0. Flag half (tag-18 bits 160..319) changed in 0 builds.
  - 0 forced or default bit changed in any build; 22 distinct group bits flipped.
- Settings tried: 103 pair ids x 2 base designs. 27 change the option register, 71 change nothing in it, 5 rejected by Quartus (illegal value / obsolete pin).
- JTAG interface (section 5): 15 classes -> 4 have an asmdb group on this die; 11 have none (0 bits). 2 groups with 16 CRAM bits each, 2 invert groups with a DB_ILLEGAL marker (no bit).

## 2. Layout

- sof tag 18 = 40 B = 320 bits. Bit i (0..159) = value of option bit i. Bit 160+i = flag of option bit i.
- Flag semantics (static, `ASM_BITFIELD`):
  - `set_bits` (libcomp_asmcc 0x118000) writes the value, a "written" mask and the shadow buffer (= flag half); `silent_set_bits` (0x117e50) writes the value only.
  - flag 0 <=> default-list bit (95); flag 1 <=> forced-list or group bit (65). Vendor sof: 95 / 95 match (`test_flag_half_is_default_list`).
- Value half: 1 for every forced and default bit in all 197 builds and all vendor GX sofs.
- rbf: option cells only in rbf frame 0 (`cff2rbf.npz` `option` table); flag half never reaches the rbf. 35 value bits have cells; 125 do not.
  - With cells: group 28 (0, 2-10, 12-18, 27-34, 91-93, 128), forced 3 (7, 38, 94), default 4 (71, 106, 112, 130). Total 35.
  - Cell counts > 1: bit 8 = 15 cells, bits 29 and 93 = 2 cells each (the table in the json has every cell).
- Polarity rule (8 dumb groups): `arch` byte 0 -> bit = NOT setting (7 groups: 0, 2, 3, 4, 5, 91, 93); `arch` 1 -> bit = setting (bit 6). 8 / 8 consistent with pairs.

## 3. Bit map

Columns: bit | asmdb group (enum) | function and QSF setting | values | Ghidra function (libcomp_asm vaddr) | pair ids | rbf cells.
"inv" = bit is NOT the setting.

| bit | group | function (QSF) | values | Ghidra | pairs | rbf cells |
|---|---|---|---|---|---|---|
| 0 | OPTION_REG_USE_CLKUSR (2365) | user-supplied start-up clock (`USER_START_UP_CLOCK`), inv | ON -> 0 | `ASM_OPTION_REG_USE_CLKUSR::process_end_of_phase` 0x1caa60 | user_clk_on | 1 |
| 1 | forced list | unknown | 1 | - | none | 0 |
| 2 | OPTION_REG_RELEASE_CLEAR_BEFORE_TRI (2368) | release clears before tri-states (`RELEASE_CLEARS_BEFORE_TRI_STATES`), inv | ON -> 0 | `..._RELEASE_CLEAR_BEFORE_TRI::process_end_of_phase` 0x1caafc | release_clears_on | 1 |
| 3 | OPTION_REG_USE_INITDONE (2369) | INIT_DONE output (`ENABLE_INIT_DONE_OUTPUT`), inv | ON -> 0 | `..._USE_INITDONE::process_end_of_phase` 0x1cac7a | init_done_on | 1 |
| 4 | DEVICE_USE_GLOBAL_CLEAR (2336) | device-wide reset DEV_CLRn (`ENABLE_DEVICE_WIDE_RESET`), inv | ON -> 0 | `ASM_DEVICE_USE_GLOBAL_CLEAR::process_end_of_phase` 0x18e112 | dev_reset_on | 1 |
| 5 | DEVICE_USE_GLOBAL_TRI (2337) | device-wide output enable DEV_OE (`ENABLE_DEVICE_WIDE_OE`), inv | ON -> 0 | `ASM_DEVICE_USE_GLOBAL_TRI::process_end_of_phase` 0x18e158 | dev_oe_on | 1 |
| 6 | OPTION_REG_ENABLE_AUTO_RECONFIGURE (2370) | auto-restart configuration (`AUTO_RESTART_CONFIGURATION`), direct | default ON = 1; OFF -> 0 | `..._ENABLE_AUTO_RECONFIGURE::process_end_of_phase` 0x1cab5a | auto_restart_off | 1 |
| 7 | forced list | unknown | 1 | - | none | 1 |
| 8 | OPTION_REG_USE_ERROR_DETECT (2371), bit 0 of 2 | CRC error detection used (QSF option or crcblock atom), inv | on -> 0 | `..._USE_ERROR_DETECT::process_atom` 0x1cacc0, `process_end_of_phase` 0x1cd832 | crc_check_on, crcblock_div1..256 | 15 |
| 9-10 | OPTION_REG_SELECT_SPI_PIN_STATE (2372) | SPI pin state, 2-bit value (bit 9 = LSB) | PS / FPP 3; active serial 2 (default); AS + `TRI_STATE_SPI_PINS` 0 | `..._SELECT_SPI_PIN_STATE::process_end_of_phase` 0x1cb268 | scheme_ps, scheme_fpp, spi_tristate_on | 1, 1 |
| 11-18 | OPTION_REG_SET_POF_ID (2373) | POF id, 8-bit, bit 11 = LSB | 1 on all 9 IV GX sfl sofs | `..._SET_POF_ID::process_end_of_phase` 0x1cbc2e | none (no QSF setting) | 0, then 1 each |
| 19-26 | default list | unknown | 1 | - | none | 0 |
| 27-34 | OPTION_REG_SELECT_CRC_FREQUENCY_DIVIDER (2375) | CRC clock divider, one-hot: divisor 2^k sets bit 26+k (k 1..8); divisor 1 = 0 | `ERROR_CHECK_FREQUENCY_DIVISOR` (needs `CRC_ERROR_CHECKING` ON) or crcblock `oscillator_divider` | `..._SELECT_CRC_FREQUENCY_DIVIDER::process_atom` 0x1caef6, `process_end_of_phase` 0x1cbf96 | crc_on_div_32, crc_on_div_256, crcblock_div2..256 | 1 each (bit 29: 2) |
| 35-37, 39-86, 88-90, 96-127, 130 | default list (95 with 19-26) | unknown | 1 | - | none | 71, 106, 112, 130 have 1 |
| 38, 87, 94-95, 131-159 | forced list | unknown | 1 | - | none | 38 and 94 have 1 |
| 91 | OPTION_REG_USE_NCEO (2378) | nCEO pin kept as programming pin; 'USE AS REGULAR IO' sets the bit (`CYCLONEII_RESERVE_NCEO_AFTER_CONFIGURATION`), inv | regular IO -> 1 | `..._USE_NCEO::process_end_of_phase` 0x1cb48a | nceo_io | 1 |
| 92 | OPTION_REG_USE_ERROR_DETECT, bit 1 of 2 | set only by the QSF `CRC_ERROR_CHECKING` option (not by a crcblock atom) | ON -> 1 | same as bit 8 | crc_check_on | 1 |
| 93 | OPTION_REG_WAIT_FOR_OCTDONE (2379) | wait for OCT calibration done (`ENABLE_OCT_DONE`), inv | ON -> 0 | `..._WAIT_FOR_OCTDONE::process_end_of_phase` 0x1cb4d6 | oct_done_on | 2 |
| 128-129 | OPTION_REG_EXTERNAL_CLK_SPI (2472) | active-serial clock (`ACTIVE_SERIAL_CLOCK`), 2-bit value (128 = LSB) via asmdb map {262:3, 263:1, 264:0} | FREQ_20MHz 3; FREQ_40MHz 1 (default); CLKUSR 0 | `..._EXTERNAL_CLK_SPI::process_end_of_phase` 0x1cb676 | as_clk_20, as_clk_40, as_clk_clkusr | 128: 1, 129: 0 |

- Forced list (35): 1, 7, 38, 87, 94-95, 131-159. Default list (95): 19-26, 35-37, 39-86, 88-90, 96-127, 130 (the 95 + 35 + 30 sets are disjoint and cover 0..159).
- Quartus accepts `ACTIVE_SERIAL_CLOCK` values CLKUSR, FREQ_20MHz, FREQ_40MHz only (assembler warning text); FREQ_12_5 / 25 / 50 / 100MHz were rejected with a warning and left the register at the default.
- The other 20 ASM_OPTION_REG_* classes (nCE, nCONFIG, JTAG pin share, JTAG core access, CVP, PR, scrubbing, quad IO, well-bias, ...) have no asmdb group on this die and write no bit (`process_*` on a missing group; ENABLE_PR / USE_NCE etc. in `reference/ghidra/functions.tsv`).
- Same 13 groups at the same indices, and the same forced list, in `ddb_stingray1/2/3_asmdb.ddb` (other IV GX dies); sfl sofs of 9 GX parts carry POF id 1.

## 4. Counts by bit class

Metric per class: matched / (matched + missing + extra + wrong), headline = bits with a decoded function.

| class | bits | function decoded | QSF pair confirms | encoder vs 197 builds (matched / wrong) | missing |
|---|---|---|---|---|---|
| group | 30 | 30 | 22 | 5,910 / 0 | 0 |
| forced | 35 | 0 | 0 | 6,895 / 0 (value 1 only) | 35 |
| default | 95 | 0 | 0 | 18,715 / 0 (value 1 only) | 95 |
| total | 160 | 30 (18.75 %) | 22 | 31,520 / 0 | 130 |

- The forced / default "matched" counts are the constant 1, not a decoded function. They stay in the missing column.
- Pair flips: matched 74, missing 0, extra 0, wrong 0 (the encoder predicts every flip and no other).
- Extra bits that changed outside the 30 group bits: 0 of 197 builds.

## 5. JTAG interface bits (15 classes)

Source: `libcomp_asm` `ASM_JTAG_*` classes, asmdb groups (block CONTROL), pairs with a `cycloneiv_jtag` atom (designs jtag_*).

| class | asmdb group on this die | bits | measured |
|---|---|---|---|
| ASM_JTAG_PIA_TO_TDOUSER | JTAG_PIA_TO_TDOUSER (523), std, 1 site, muxes of 14 + 2 bits | 16 CRAM (frames 6134-6141, rows 862-863) | tdouser driven from pin / LUT / register / all: 2 of 16 set in 4 / 4 builds |
| ASM_JTAG_PIA_TO_TDOUTAP | JTAG_PIA_TO_TDOUTAP (524), std, muxes 14 + 2 | 16 CRAM (frames 6134-6141, rows 864-865) | 0 set: the fitter rejects a driven `tdoutap` port ("JTAG block does not support input port TDOUTAP") |
| ASM_JTAG_TDOUSER_INVERT, ASM_JTAG_TDOUTAP_INVERT | dumb groups (529, 530) | address `0xfffffffd` = DB_ILLEGAL marker: no bit, writing a value is an internal error | not testable; inversion unsupported on this die |
| ASM_JTAG_PIA, _PIA_TO_CORE_CTL, _PIA_TO_TCKCORE, _PIA_TO_TDICORE, _PIA_TO_TMSCORE, _TCKCORE_INVERT, _TDICORE_INVERT, _TMSCORE_INVERT, _CORECTL_INVERT | none | 0 | no group, no bit: core-side routing not configurable on IV GX |
| ASM_JTAG_ENABLE_BST_SUPPORT | none | 0 | `ENABLE_JTAG_BST_SUPPORT` ON / OFF: 0 option bits, 0 CRAM bits changed |
| ASM_JTAG_WRITE_USER_CODE | none | 0 option bits | writes sof tag 19 (section 6) |

- Option-register JTAG bits: `OPTION_REG_JTAG_CORE_ACCESS` and `OPTION_REG_USE_JTAG_PIN_SHARE` have no group on this die: the "2 option bits" of the address-space doc do not exist for IV GX. `ENABLE_JTAG_PIN_SHARING` ON: 0 bits changed.
- The 8 `cycloneiv_jtag` output-only variants each flip the same 20 CRAM cells in the combinational base (80 in the registered base, includes placement); these cells belong to no JTAG group and stay unclaimed.
- TAP state machine: no group, no bit (unchanged conclusion of the address-space doc).

## 6. USERCODE (tag 19, rbf header lane 0)

- Pairs (base `min`, 32 bits at tag 19 payload bytes 12..15, little endian):
  - default build: per-build value (checksum; e.g. 0x0071f278); `USE_CHECKSUM_AS_USERCODE` ON gives the same value.
  - `USE_CHECKSUM_AS_USERCODE` OFF: 0xffffffff (unset).
  - OFF + `STRATIX_JTAG_USER_CODE AABBCCDD`: 0xaabbccdd. `JTAG_USER_CODE` and `STRATIX_JTAG_USER_CODE` with the checksum default: no change.
- 0 option bits change in these pairs.

## 7. Settings tried (EP4CGX150DF31C7, all as global QSF assignments, base `min` and `reg`, sampling plan = the two bases; option register is one global register, not a tile grid)

- Change the register (27 ids): ENABLE_INIT_DONE_OUTPUT, USER_START_UP_CLOCK, RELEASE_CLEARS_BEFORE_TRI_STATES, ENABLE_DEVICE_WIDE_RESET, ENABLE_DEVICE_WIDE_OE, CRC_ERROR_CHECKING (and STRATIX_ alias), ERROR_CHECK_FREQUENCY_DIVISOR (32, 256 with CRC on), CYCLONEII_RESERVE_NCEO_AFTER_CONFIGURATION, ENABLE_OCT_DONE, CYCLONEIII_CONFIGURATION_SCHEME PASSIVE SERIAL / FAST PASSIVE PARALLEL, TRI_STATE_SPI_PINS, ACTIVE_SERIAL_CLOCK 20MHz / CLKUSR, AUTO_RESTART_CONFIGURATION OFF, crcblock atom oscillator_divider 1..256 and deduce-location variant.
- No effect on the option register (71 ids): ENABLE_ED_CRC_CHECK, ENABLE_CRC_ERROR_PIN, ERROR_CHECK_FREQUENCY_DIVISOR without CRC ON, ENABLE_NCEO_OUTPUT, ENABLE_NCE_PIN, ENABLE_JTAG_BST_SUPPORT, ENABLE_JTAG_PIN_SHARING, ENABLE_NCONFIG_FROM_CORE, ENABLE_CVP_CONFDONE, ENABLE_CVPCIE_CONFDONE, INTERNAL_SCRUBBING, ENABLE_PR_PINS, ENABLE_SPI_MODE_CHECK, EN_SPI_IO_WEAK_PULLUP, ACTIVE SERIAL / ACTIVE PARALLEL scheme (= default), CONFIGURATION_CLOCK_DIVISOR / FREQUENCY, USE_CONFIGURATION_DEVICE, STRATIXII_CONFIGURATION_DEVICE, CONFIGURATION_VCCIO_LEVEL 3.3V, FORCE_CONFIGURATION_VCCIO, ON_CHIP_BITSTREAM_DECOMPRESSION, GENERATE_RBF_FILE, POF_VERIFY_PROTECT, SECURITY_BIT, RESERVE_DATA0 / DCLK / FLASH_NCE_AFTER_CONFIGURATION, RESERVE_ALL_UNUSED_PINS, ENABLE_BOOT_SEL_PIN, ENABLE_ASMI_FOR_FLASH_LOADER, ENABLE_FALLBACK_TO_EXTERNAL_FLASH, ENABLE_ADV_SEU_DETECTION, USE_CONF_DONE, ENABLE_LOW_VOLT_MODE, ACTIVE_SERIAL_CLOCK FREQ_40MHz (default) and the illegal values, the usercode pairs, the JTAG-atom designs.
  - Several of these change CRAM, IO config or tag 19 (pin reservations, VCCIO, the checksum usercode) but never an option bit.
  - "No effect" is per design context; a setting that needs a feature absent from the tiny designs (a CVP / PR / scrubbing design) is not excluded.
- Rejected by Quartus (5): CONFIGURATION_SCHEME `INTERNAL CONFIGURATION` (illegal value), CONFIGURATION_VCCIO_LEVEL 1.8V (not supported by active serial), RESERVE_ASDO_AFTER_CONFIGURATION (obsolete for IV GX), a `CYCLONEIII_JTAG_USER_CODE` name (unreadable QSF), one jtag design variant.
- Options for the other 130 bits: none found. Counted as missing.

## 8. Method

- Group bits: asmdb walk (`asmdb_walk.py`): option-space addresses (`0x88000000 | index`) in the std / dumb / stl groups of block type DEVICE. 13 groups, 30 bits: exactly the 30 bits that were in neither list (address-space doc 3.1).
- Names and semantics: Ghidra decompile of `ASM_OPTION_REG_*::process_atom / process_end_of_phase`, `ASM_DEVICE_USE_GLOBAL_*`, `ASM_JTAG_*` (`reference/ghidra/functions.tsv`, source `#169`). Each calls `ASM_ARCH_GROUP::mux_select(group, 0, value)`.
- Confirmation: `scripts/cycloneiv_clean_option_pairs.py` (detached, 12 jobs, memory lease via `heavy_guard`, 60 s stall guard in `cycloneiv_fuzz.run`, step limits 63 / 75 / 30 / 8 s = io_pairs pilot). Each pair = base + ONE assignment (chain pairs: reference carries the context assignment). Local results `databases/cycloneiv/option_pairs.json`.
- Model: `options.encode(Config)` -> 160 bits. Rules per group are in the code, bit positions from the table.

## 9. Open

- Function of the 130 forced / default bits (7 of them reach the rbf header: 7, 38, 94 forced; 71, 106, 112, 130 default). No group, no setting, no decompiled writer. Candidates: the cpf header overlay (die variant, length, flag bits) and constants of the config controller.
- Bit 11 (POF id LSB) has no rbf cell; bits 12-18 do. Bit 129 has none.
- `ASM_OPTION_REG_SELECT_SPI_PIN_STATE` value table vs the observed AS default (2) and tri-state (0): the decompile maps flash mode 1 to 2 and flash mode 0 + tri-state to 0; which flash mode the base build runs is not read from the decompile.
- JTAG block presence flips 20 unclaimed CRAM cells (combinational base); not decoded.
- The 21-field `ASM_OPTION_REGISTER_CZAR` logical register is not mapped to these bits (family tables for other families are in the same constructor).
