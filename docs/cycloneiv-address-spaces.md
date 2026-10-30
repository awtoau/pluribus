# Cyclone IV GX (EP4CGX150) address spaces, JTAG, option bits, unclaimed bits

Static analysis of the vendor install only (authorised #165); no key / decrypt work.
Local, gitignored: Ghidra outputs under `vendor-analysis/altera/analysis/` (this doc's pass: `addrspaces/`).
Measured 2026-10-30 on the EP4CGX150 files of Quartus 25.1: `ddb_stingray4_asm.ddb`, `ddb_stingray4_asmdb.ddb`, `ep4cgx150_pcf.ddb`, vendor `sfl_ep4cgx150.sof`, 29 Quartus-converted uncompressed rbfs (26 bit-plane builds + original + 2 sfl), one Quartus-built GX150 sof from the corpus.
Related: [cycloneiv-clean-io.md](cycloneiv-clean-io.md) (#168), [cycloneiv-clean-pipeline.md](cycloneiv-clean-pipeline.md) (A4-A6), [cycloneiv-bit-inventory.md](cycloneiv-bit-inventory.md) (specimen-based tiers).

## 1. Answers

- Config = 5 address spaces named by the assembler, 3 populated on this die: CRAM 39,040,976, CFF 31,060, option register 160. UNVM = 0. DPRIO has no size of its own (writes alias the CFF buffer, section 2.1).
- Sections not fully decoded: option register (30 of 160 bits decoded to a function, `cycloneiv-clean-options.md`), CFF fields (0 of 31,060), all CRAM outside LUT INIT and asm.ddb routing.
- JTAG: no address space, no sof section, no rbf region of its own. The TAP state machine is not configurable by any bit the assembler knows. The assembler writes only the user-logic interface of one JTAG block (15 classes) plus 2 option-register bits plus the 32-bit USERCODE (section 4).
- Present in the device model but claimed by no decoded record: 29,023,893 of 39,040,976 CRAM bits (74.34 %), counted by region in section 5. These are NOT shown to be reserved: the asmdb group vectors that would claim most of them (M9K / MUL / IO / clock / PLL / transceiver blocks, LAB non-LUT) are not decoded.
- Nothing in the vendor files labels any CRAM / CFF bit reserved, spare, redundancy or test for IV GX (symbol and field-name search, section 5.4). Absence of a label is not evidence of absence.

## 2. Address spaces

### 2.1 Space table

Writer for all spaces: `ASM_BITFIELD::silent_set_bits` (libcomp_asmcc, Ghidra 0x117e50; static decompile). Input = list of (uint32 address, value byte); tag tests in this order.

| space | tag (all bits set) | index | size, source | sof | rbf | owner |
|---|---|---|---|---|---|---|
| literal / sentinel | `0xC0000000` | - | n/a | none | none | assembler markers DB_ILLEGAL_{HIGH,LOW,ALWAYS}=`0xfffffffd/c/e`, DB_MCF_ILLEGAL_ALWAYS=`0xfffffffa`: writing a wrong value raises an internal error; `0xfffffffb` passes silently |
| CRAM | bit 31 clear | a | 39,040,976 = 6,154 x 6,344; asmdb body +5, pcf payload word 38, hdr `frame_bits` 6,344 | tag 17: 12 + 4,880,122 = 4,880,134 B | CRAM frames 37..6190, data bytes 1..793, LSB first; A5 mirror blocks | fabric (LAB / LE / routing), M9K, MUL, IO routing, clocks, PLL, transceiver, block setup |
| CFF | `0xA0000000` | a & `0x5fffffff` | 31,060; asmdb body +9 | tag 21: 12 + 3,883 = 3,895 B | periphery frames 1..36, 4 replica cells per bit | IO pin config (IOE), 104 default bits; field map undecoded |
| UNVM | `0x90000000` | a & `0x6fffffff` | 0; asmdb body +13 | none (no such tag in the 3 EP4CGX150 sofs examined) | none | not applicable; "UNVM bits don't exist for this device family" error path |
| option register | `0x88000000` | a & `0x77ffffff` | 160; asmdb body +17 | tag 18: 40 B = 320 bits (160 values + 160 flags, section 3) | frame 0 (header), 35 bits reach 51 cells | config control / security-adjacent options: start-up, nCE, CRC, SPI (section 3) |
| DPRIO | `0x84000000` | a & `0x7bffffff` | no field in the die record | none | none of its own | transceiver dynamic-reconfig space; written into the CFF buffer |

- DPRIO branch of `silent_set_bits` tests the CFF base pointer for null ("DPRIO bits don't exist for this device family") and bounds-checks and stores through the CFF buffer, not a fifth buffer. So DPRIO addresses, if any exist for a die, occupy the CFF bit range.
- Census on this die: 51,565,365 asm.ddb addresses are all CRAM (0 CFF / UNVM / option / DPRIO / literal), min 3,105, max 39,037,932. asmdb default bit list (2,518) = 2,319 CRAM + 104 CFF + 95 option; forced list (35) = 35 option. No address with the DPRIO tag exists in any list decoded.
- ASM_BITFIELD constructor (0x117e40) allocates four buffers from four bit counts: CRAM, CFF (also carrying DPRIO), UNVM, option register; parameter order inferred from which buffer each `silent_set_bits` branch bounds against.

### 2.2 sof sections (EP4CGX150 vendor sof)

| tag | bytes | content |
|---|---|---|
| 1 | 79 | Quartus version string |
| 2 | 16 | device name string |
| 3 | 27 | design / project string |
| 18 | 40 | option register, 320 bits (section 3) |
| 19 | 16 | u16 x 6 constants `0,0,0x20,0x20,0,1` (meaning not derived) + u32 JTAG USERCODE (section 4) |
| 36 | 339 | Quartus-built sofs only: embedded file `design_hash.bin` (metadata, no config) |
| 17 | 4,880,134 | CRAM: 12-byte header, then 4,880,122 data bytes |
| 21 | 3,895 | CFF: 12-byte header, then 3,883 data bytes |
| 8 | 2 | trailer CRC-16 (reflected 0x8408, init 0xFFFF, complemented) |

- Tag 17 / 21 header = 6 zero bytes + u32 bit count (39,040,976 / 31,060) + 2 bytes that vary: tag 17 bytes 10..11 = `41 00` (sfl), `41 30` (sfl-enhanced), `01 00` (Quartus-built); tag 21 = `01 00`. Meaning not derived.
- The 3 EP4CGX150 sofs examined (vendor sfl, vendor sfl-enhanced, one Quartus-built) carry exactly tags 1, 2, 3, 18, 19, 17, 21, 8 (+ 36 on the Quartus-built one). Over all 377 vendor sofs (all families) tag 18 is in 336 and 19 / 17 / 21 / 8 in all; 14 other tags occur on other families or images (not examined).

### 2.3 rbf layout, bit accounting (uncompressed, 4,928,127 B = 39,425,016 bits, identical in 29 / 29 files)

| region | bytes | bits | claimed by | source |
|---|---|---|---|---|
| preamble | 32 | 256 | none: 0xFF in 29 / 29 | rbf bytes 0..31 |
| frame 0 sync | 1 | 8 | none: 0x6a | rbf byte 32 |
| frame 0 option lanes | 40 | 320 | option register + USERCODE + cpf constants (section 3, 4) | rbf bytes 33..72 |
| frame 0 CRC-16 | 2 | 16 | none: `d2c7` in 29 / 29 | rbf bytes 73..74 |
| frame 0 fill | 753 | 6,024 | none: 0xFF, all set | rbf bytes 75..827 |
| periphery 36 frames x 796 B | 28,656 | 229,248 | CFF 124,496 cells; 104,752 not claimed | `cff2rbf` table + oracle rbfs |
| CRAM 6,154 frames x 796 B: data | 4,880,122 | 39,040,976 | CRAM | tag 17 |
| CRAM frames: pad byte 0 | 6,154 | 49,232 | none: 0 in 29 / 29 | rbf |
| CRAM frames: CRC-16 (init 0xFE54) | 12,308 | 98,464 | derived from data | docs/cycloneiv-bitstream.md |
| postamble | 59 | 472 | none: 0xFF in 29 / 29; = pcf payload word 25 | pcf word 25 |

- Total check: 256 + 6,368 + 229,248 + 6,154 x 6,368 + 472 = 39,425,016.
- Outside every sof-defined space (not CRAM, not CFF, not option): preamble 256 + frame-0 sync / CRC / fill 6,048 + CRAM pad 49,232 + CRAM CRC 98,464 + postamble 472 + periphery unclaimed 104,752 = 259,224 bits.
  - Periphery unclaimed: 172 set, 104,580 clear in the vendor rbf; constant across the 29 files. They are template cells, not tag bits (bit-plane flip test, `scripts/cycloneiv_clean_cff_tables.py`).
  - CFF cells span byte 0 (119 cells), data bytes 1..793 (124,071) and bytes 794..795 (306) of the periphery frames: a periphery frame has no pad / CRC byte split.
  - CFF cells per periphery frame 1..36: 1,348, 1,592, 1,592, 1,596, 1,584, 1,592, 1,592, 1,608, 1,584, 1,592, 1,592, 1,608, 1,584, 1,592, 1,592, 1,608, 2,268, 3,084, 4,824, 5,760, 6,336, 6,368, 6,368, 6,328, 6,336, 6,368, 6,368, 6,328, 6,336, 6,368, 6,368, 6,328, 6,336, 736, 0, 32. Frame 35 holds none; frames 21..33 are almost fully CFF.
- CFF multiplicity: 30,996 bits x 4 cells + 64 bits x 8 cells = 124,496 cells (#168 E6).

## 3. Option register (160 bits)

### 3.1 What is in the vendor data

- asmdb die record (`ASMDB_DIE::operator<<`, field order m_num_bits, m_num_cff_bits, m_num_unvm_bits, m_num_option_reg_bits, rba / bvp strings, block-info map, arch-group list, default-group list, default-bit list, forced-bit list, labeled simple muxes, local lists, 3 HardCopy node / wire vectors). Lists decoded as chained i32 deltas (element 0 relative to 0):
  - default-bit list: 2,518 addresses (`ASMDB_DIE::add_default_bit`, `get_default_bits`): 2,319 CRAM, 104 CFF, 95 option. Each is emitted as a set bit with value = die flag XOR 1; die flag is 0 here, so value 1.
  - forced-bit list: 35 addresses (`add_forced_bit`, `get_forced_bits`), all option. Same value rule.
  - default and forced option indices are disjoint: 95 + 35 = 130 of 160.
  - 30 option bits are in neither list: indices 0, 2-6, 8-18, 27-34, 91-93, 128, 129. These must be written by atom-driven settings or are unused.
  - 580 default groups, 6,087 + 225 arch groups (std 4,893 + 103, calc 277, dumb 913 + 119, map 4 + 3), 8 block types.
- Settings write option bits through the arch groups: `ASM_OPTION_REG_*::process_atom` / `process_end_of_phase` call `ASM_ARCH_GROUP::mux_select(group, value)` (33 classes in libcomp_asm; the three decompiled carry no address).
  - Examples read statically: `ASM_OPTION_REG_USE_NCE` = `CDB_CHIP_DB_ENTRY::is_nce()`; `ASM_OPTION_REG_USE_JTAG_PIN_SHARE` = `is_jtag_pin_sharing()`; `ASM_OPTION_REG_JTAG_CORE_ACCESS` = 1 iff the JTAG atom has its core-access input connected (input term type 0x39e), skipped if no JTAG node.
  - Class names (libcomp_asm symbols, family applicability to IV GX not established): CRAM control voltage, device start-up clock, auto reconfigure, CRC error location, CVP, IOCSR ready, PR enable, quad IO, external SPI clock, force-to-zero, JTAG core access, release clear before tri, CRC frequency divider, power-management control, SPI pin drive / state, CRC error delay, feature ID, internal scrubbing, POF ID, CLKUSR, ERAM skip, error detect, INIT_DONE, JTAG pin share, nCE, nCEO, nCONFIG, nCONFIG from core, wait for OCT done, well-bias.
- `ASM_OPTION_REGISTER_CZAR::read_option_settings` (libcomp_asm, Ghidra 0x1face6) computes a separate 21-field logical register printed as "Option Register value: 0x%X": fields 0..20 = constant 1, two bool options, user start-up clock, two SPI-mode terms, dev_clr, dev_oe, JTAG BST support, crc_error, init_done, nCEO reserved mode, one bool option, then one-hot CRC clock divisor 2 / 4 / 8 / 16 / 32 / 64 / 128 / 256. The mapping from these 21 fields to the 160 asmdb bits is not established.

### 3.2 sof tag 18 (40 B = 320 bits) and rbf header

- Tag 18 = 160 value bits (bits 0..159) + 160 flag bits (160..319), measured on the vendor sof:
  - flag bits: the 95 zeros are exactly the 95 default-bit option indices (95 / 95).
  - value bits: 19 zeros (indices 9, 12-18, 27-34, 91, 92, 129), all inside the 30 unclaimed-by-lists set; all 130 default + forced bits read 1.
  - Tag 18 is byte-identical in the vendor sof and the Quartus-built sof.
- rbf header option lanes (8 lanes x 40 bits; byte i of the 40 = bit i of every lane):
  - lane 0 = 8 ones + USERCODE (section 4).
  - lanes 1..4 equal tag-18 bits 0..159 in order (lane = 1 + k div 40, bit = k mod 40), 124 / 160 match; `quartus_cpf` overlays die-variant, length and flag bits (lane 1 bits 19, 20, 22-26; lane 2: 21 positions incl. the length field; lane 3 bits 1-6, 8, 10).
  - lanes 5..7 = 120 constant ones in every file; tag-18 bits 160..319 never reach the rbf.
  - Only 35 of the 160 value bits propagate (bit-plane flip test, 51 header cells, `option` table in `cff2rbf.npz`): indices 0, 2-10, 12-18, 27-34, 38, 71, 91-94, 106, 112, 128, 130. Of these, 28 are in the unclaimed-by-lists set, 4 default (71, 106, 112, 130), 3 forced (7, 38, 94). Unclaimed and not propagated: 11, 129.
- Function of the option bits: 30 of 160 decoded (`docs/cycloneiv-clean-options.md`).

## 4. JTAG and USERCODE

- Hardened vs config bits:
  - TAP state machine, IR / DR: no address space, no sof tag, no rbf region. No assembler class writes TAP behaviour. Treat as hardened logic (inference from absence: 51.6 M asm entries, 2,553 asmdb default / forced addresses, and the 776 `process_atom` / `process_end_of_phase` classes of libcomp_asm, all families, none named for TAP state).
  - JTAG block = one fabric-visible node: `ASM_MODEL::s_jtag_node_index` / `s_jtag_pad_index`; every JTAG class returns at once when the index is -1 (`ASM_JTAG_PIA::process_atom` 0x288b78 checked).
  - 15 JTAG classes (libcomp_asm): `ASM_JTAG_PIA`, `_PIA_TO_CORE_CTL`, `_PIA_TO_TCKCORE`, `_PIA_TO_TDICORE`, `_PIA_TO_TMSCORE`, `_PIA_TO_TDOUSER`, `_PIA_TO_TDOUTAP`, five `_*_INVERT` (TCKCORE, TDICORE, TMSCORE, TDOUSER, TDOUTAP) plus `_CORECTL_INVERT`, `_ENABLE_BST_SUPPORT`, `_WRITE_USER_CODE`. They select the core-side routing of tck / tdi / tms / tdo-user / tdo-tap and polarity through `mux_select`.
  - No option bits: `OPTION_REG_JTAG_CORE_ACCESS` and `OPTION_REG_USE_JTAG_PIN_SHARE` have no asmdb group on this die (E-A1). BST support = field 7 of the 21-field logical register.
  - Address space of the JTAG interface bits: CRAM, 4 of 15 classes have a group (`docs/cycloneiv-clean-options.md` section 5).
  - Also present for fabric-reachable config blocks, same style: CRC (6 classes), remote update RU (12), SPI (8), OSC (4), OPREG (4), TSD (7), UFM (1).
- Programmer side (host, not config): `ep4cgx150_pcf.ddb` type table lists `PGMIO_PCF_ENTRY`, `PGMIO_PCF_FILE_INFO`, `PGMIO_PCF_FIELD`, `PGMIO_F2P_CONSTANTS`, `PGMIO_JTAG_CONSTANTS` (with two `PGM_BIT_ARRAY`), `PGMIO_DEVICE_CONSTANTS`, `PGMIO_PCF_OPTIONS`, `PGMIO_ERAM_LOCATIONS`, `PGMIO_PRESERVATION_INFO`. Payload (3,160 B inflated, 790 words) tied so far: word 11 = 6,344 (frame bits), 25 = 59 (postamble bytes), 32 = 793 (bytes per lane), 37 = 6,154 (CRAM frames), 38 = 39,040,976 (CRAM bits), 33 = ASCII `EPCS`. Others (e.g. 24 = 6,506; 67 entries of 32 at words 46..112) not matched to fields.
- USERCODE (JTAG user code, 32 bit):
  - Writer: `ASM_BITFIELD::set_jtag_user_code(uint)` (libcomp_asmcc 0x19c82), class `ASM_JTAG_WRITE_USER_CODE`.
  - sof: tag 19 payload bytes 12..15, little-endian u32. Vendor GX sofs = `0xffffffff` (unset); Quartus-built GX150 sof = a per-build value; vendor IV E sofs = per-part values.
  - rbf: header lane 0 bits 8..39, LSB first (lane 0 bits 0..7 = ones). Measured equal in 4 / 4 converted images (3 IV E vendor sofs through `quartus_cpf`, 1 Quartus-built GX150 sof with its own rbf) and all-ones for the 29 GX150 images from sfl sofs.
  - Consequence: header lane 0 is not an unknown option block; the earlier "per-design usercode / checksum" note is the USERCODE.

## 5. CRAM / CFF bits no decoded record claims

### 5.1 Method

- Claim map over the 39,040,976 CRAM bits = union of three vendor sources, address = frame + 6,154 x v (sof bit index, A4):
  - asm.ddb routing entries: 51,565,365 entries, 7,620,908 distinct addresses (all CRAM).
  - asmdb LAB LUT INIT: 2,396,160 addresses (decoded run, disjoint from asm.ddb: overlap 0).
  - asmdb default-bit list, CRAM part: 2,319 addresses; 2,304 already in asm.ddb, 0 in the LUT run, so 15 new.
  - Union 7,620,908 + 2,396,160 + 15 = 10,017,083 claimed; 29,023,893 not claimed.
- Not claimed here (decoder gap, not an absence in the vendor data): asmdb group bit vectors other than the LUT run; the 277 calc groups, 1,032 dumb groups and std muxes were not associated to block types or instances. The pool run parsed so far (5,315 vectors, 131,730 elements) is all CRAM.
- Regions: asm frame s = address mod 6,154 split at the column anchors (the asmdb instance cell `lo` for LAB / M9K / MUL; the old FX - 61 anchor table is removed, E-C2); rows by v: tile rows = asm v 23..6322 (90 rows x 70), IO-row bands = v 0..22 and 6323..6343. Frame-to-rbf: sof identity then A5 (rbf CRAM frame = 6,153 - s, except mask cells in mirror blocks).

### 5.2 Per region (bits)

| column kind (asm frames) | rows | total | asm.ddb | LUT | default list | claimed | unclaimed | unclaimed % |
|---|---|---|---|---|---|---|---|---|
| IOL (32) | tile | 201,600 | 57,432 | 0 | 2 | 57,434 | 144,166 | 71.5 |
| IOL | IO bands | 1,408 | 8 | 0 | 0 | 8 | 1,400 | 99.4 |
| LAB x104 (3,648) | tile | 22,982,400 | 6,466,248 | 2,396,160 | 6 | 8,862,414 | 14,119,986 | 61.4 |
| LAB | IO bands | 160,512 | 47,254 | 0 | 0 | 47,254 | 113,258 | 70.6 |
| M9K x8 (2,344) | tile | 14,767,200 | 719,856 | 0 | 0 | 719,856 | 14,047,344 | 95.1 |
| M9K | IO bands | 103,136 | 166 | 0 | 0 | 166 | 102,970 | 99.8 |
| MUL x4 (100) | tile | 630,000 | 282,184 | 0 | 0 | 282,184 | 347,816 | 55.2 |
| MUL | IO bands | 4,400 | 56 | 0 | 0 | 56 | 4,344 | 98.7 |
| IOR (30) | tile | 189,000 | 47,693 | 0 | 7 | 47,700 | 141,300 | 74.8 |
| IOR | IO bands | 1,320 | 11 | 0 | 0 | 11 | 1,309 | 99.2 |
| total (6,154) | | 39,040,976 | 7,620,908 | 2,396,160 | 2,319 | 10,017,083 | 29,023,893 | 74.34 |

- "default list" = default-bit-list CRAM addresses inside the region (2 + 2,290 + 20 + 7 = 2,319); "claimed" is the union, each bit once (2,304 default bits overlap asm.ddb). Column kinds from the geometry file: 118 columns = 104 LAB + 8 M9K + 4 MUL + IOL + IOR.
- Zero-claim asm frames: 3,277 of 6,154 (IOL 18 / 32, LAB 1,030 / 3,648, M9K 2,170 / 2,344, MUL 44 / 100, IOR 15 / 30). Runs include 290..523 (234 frames) and, in LAB bands, repeating 3 / 7-frame gaps.
- Zero-claim v rows: 92 of 6,344 = v 57 + 70k for k = 0..89 (one row per tile row, 566,168 bits) + v 6341, 6342.

### 5.3 What the unclaimed regions are expected to hold (from vendor structure, not measured)

- M9K bands: memory data. `ASMDB_BLOCK_INFO` carries `m_num_ram_cols`, `m_block_bit_to_avalon_bit_map`, `m_export_port_to_bit_map`, `m_avalon_name_to_size_map`; not decoded. M9K tile bits unclaimed = 14,047,344.
- LAB non-routing, non-LUT: LE modes, FF config, control stripe, packing (31 `ASM_LE_*`, 34 `ASM_LAB_*` classes).
- IO columns / IO rows / clock tree / PLL / transceiver: block types in asmdb (8 block types); IO pin config is CFF, not CRAM (#168).
- Block power / freeze bits: `ASM_PR_AGENT_STINGRAY` exposes freeze, power-by-tile and RAM-array power-down getters; `get_block_power_bits_by_gid` raises "not supported for Stingray". Their addresses are not decoded.

### 5.4 Reserved / spare / redundancy / test

- libcomp_asm, libcomp_asmcc, libcomp_asmgx, libdb_asmdb symbol search for redundan / spare / reserved / dummy / test / scan: only transceiver and other-family classes (`ASM_CDR_QUAD_RX_TX_TEST_MODE`, `ASM_ADC_TESTBIT`, `ASM_HC_SCAN_CHAIN_BYPASS`), IO-pin "reserved" enum, dummy-oterm netlist helpers. No bit-level reserved / spare / redundancy marker for IV GX.
- Die geometry has no slack: CRAM 6,154 x 6,344 is exactly the sof section and the pcf bit count, so every sof CRAM bit is in the model. Redundancy, if present in silicon, is not visible to the assembler.
- Unclaimed periphery cells (104,752) and rbf padding (section 2.3) are template constants in every image seen; they are the only cells proven outside the model.

### 5.5 CFF

- CFF claims: the default-bit list marks 104 CFF addresses (range 0..31,059); asm.ddb has 0. The remaining 30,956 CFF bits are placed (bit to cell table, #168) but have no claim record decoded. All 31,060 are seen in the rbf periphery (31,060 / 31,060), so none is unused at the sof / rbf level.

## 6. Coverage table

Tier names: [cycloneiv-bit-inventory.md](cycloneiv-bit-inventory.md). "Claimed" = a decoder (pluribus) attributes the bit; "address known" = a vendor record names the address.

| space | bits | address known | claimed by decoder | tier |
|---|---|---|---|---|
| CRAM, LAB LUT INIT | 2,396,160 | yes (asmdb) | yes | verified (oracle, 301 designs) |
| CRAM, asm.ddb routing addresses | 7,620,908 | yes (asm.ddb) | address yes; which group fires = decoded-untested; clean tracer pending (P2) | decoded |
| CRAM, asmdb default bits not in asm.ddb | 15 | yes | no | decoded (address only) |
| CRAM, asm.ddb overlap with default list | 2,304 | yes | no (as defaults) | decoded (address only) |
| CRAM, unclaimed in LAB columns (tile rows 14,119,986 + IO bands 113,258) | 14,233,244 | no | no | unknown |
| CRAM, unclaimed in M9K columns (tile 14,047,344 + IO bands 102,970) | 14,150,314 | no | no (data cells have specimen tiers 4f / 4g, not vendor) | unknown |
| CRAM, unclaimed in MUL / IOL / IOR (IOL 145,566 + MUL 352,160 + IOR 142,609) | 640,335 | no | no | unknown |
| CRAM total unclaimed | 29,023,893 | no | no | unknown |
| CFF | 31,060 | placement measured; 104 default addresses decoded | no field decoded (0 of 31,060) | measured (placement) / unknown (fields) |
| UNVM | 0 | n/a | n/a | n/a |
| option register | 160 | 130 in default / forced lists; 30 in neither | 0 functions decoded; sof structure measured | measured (structure) / unknown (functions) |
| DPRIO | none on this die | none | n/a | n/a |
| rbf header lane 0 (USERCODE) | 40 (32 value) | yes (sof tag 19) | yes | measured (4 / 4) |
| rbf header lanes 1..4 | 160 | partly (35 propagate) | no | measured (map) / unknown (meaning) |
| rbf header lanes 5..7, fill, CRC, sync | 120 + 6,024 + 16 + 8 | constants | n/a | verified constants / CRC verified |
| rbf CRAM CRC | 98,464 | derived | yes | verified (70 / 70 pairs) |
| rbf CRAM pad byte | 49,232 | constant 0 | n/a | measured |
| rbf periphery unclaimed | 104,752 | constants | n/a | measured |
| rbf preamble / postamble | 256 / 472 | constants (postamble = pcf word 25) | n/a | measured |

- Unclaimed rows sum: 14,233,244 + 14,150,314 + 640,335 = 29,023,893.

## 7. Open

- asmdb group decode (block type per group, instance cell vectors for IO / clock / PLL / transceiver, calc groups) would turn most of the 29 M "unclaimed" into claimed or genuinely unused.
- Function of the 130 forced / default option bits (`docs/cycloneiv-clean-options.md` section 9).
- Tag 19 constants, tag 17 / 21 header bytes 10..11.
- Numbers here were produced by throwaway analysis (not committed); regenerate before relying on a count after any decoder change.
