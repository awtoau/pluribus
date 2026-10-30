# Ghidra readable-code index (#165, #168)

Names, addresses and purposes only; pseudo-code is local under `vendor-analysis/altera/analysis/readable/` (gitignored). How to build it: [ghidra-workflow.md](ghidra-workflow.md).

## Layers

| Enum | Constants | Source table |
|---|---|---|
| `ASMDB_ARCH_GROUP_BLOCK_TYPE` | 542 | `enums.tsv` (vendor debug-string table) |
| `ASMDB_ARCH_GROUP_TYPE` | 4663 | `enums.tsv` (vendor debug-string table) |
| `ASMDB_DIRT_TYPE` | 303 | `enums.tsv` (vendor debug-string table) |
| `DEV_ELEMENT_ENUM` | 2715 | `enums.tsv` (vendor debug-string table) |

## Per library

| Lib | Classes with vtable | Mined structs | Exported class files |
|---|---|---|---|
| libcomp_asm | 960 | 0 | 790 |
| libcomp_asm2 | 114 | 0 | 0 |
| libcomp_asmcc | 19 | 0 | 10 |
| libcomp_asmgx | 480 | 0 | 0 |
| libcomp_asmio | 259 | 0 | 246 |
| libcomp_asmmac | 188 | 0 | 181 |
| libcomp_asmpll | 47 | 0 | 30 |
| libcomp_asmram | 128 | 0 | 122 |
| libdb_asmdb | 10 | 30 | 53 |
| libdb_cdb_atom_stingray | 1 | 0 | 0 |
| libdb_pdb | 15 | 0 | 2 |
| libdb_u2b_bcm | 1 | 0 | 0 |
| libddb_bcm2bits | 22 | 0 | 0 |
| libddb_dbcm | 44 | 0 | 0 |
| libddb_dev | 10 | 4 | 46 |
| libddb_dstr | 46 | 0 | 0 |
| libddb_dygr | 28 | 0 | 59 |
| libpgm_fbgen | 26 | 0 | 0 |
| libpgm_pgmio | 74 | 0 | 0 |
| libpgm_pof | 54 | 0 | 0 |

## Key functions

| Lib | Vaddr | Function | Purpose | Clean-tree user |
|---|---|---|---|---|
| libcomp_asm | `0x19101c` | `ASM_IO_PIN_MODE::process_atom` | this + atom + streams: demangled signature lacked this | lifters/cycloneiv_clean/cycloneiv_io.py, scripts/cycloneiv_clean_io_od.py |
| libcomp_asm | `0x183e34` | `ASM_IO_USE_BUS_HOLD::process_atom` | - | scripts/cycloneiv_clean_asm_classes.py, scripts/cycloneiv_clean_class_bind.py |
| libcomp_asm | `0x190e70` | `ASM_IO_PIN_MODE::handle_ygr_dual_pin_iost` | non-virtual member: demangled args + this | lifters/cycloneiv_clean/cycloneiv_io.py, scripts/cycloneiv_clean_io_od.py |
| libcomp_asmcc | `0x1a240` | `ASM_BITFIELD::silent_set_bits` | settings = std::vector<DB_BIT_SETTING> (uint32 address, value byte) | lifters/cycloneiv_clean/cycloneiv_io.py, lifters/cycloneiv_clean/m9k.py, scripts/cycloneiv_clean_options_build.py |
| libcomp_asmcc | `0x1aca0` | `ASM_BITFIELD::set_bits` | settings = std::vector<DB_BIT_SETTING> | lifters/cycloneiv_clean/cycloneiv_io.py, lifters/cycloneiv_clean/m9k.py, scripts/cycloneiv_clean_options_build.py |
| libcomp_asmcc | `0x28526` | `ASM_ARCH_GROUP::mux_select` | parameter roles from IO direction use | lifters/cycloneiv_clean/io_encode.py |
| libdb_asmdb | `0x9dbbc` | `ASMDB_BLOCK_INFO::operator<<` | - | lifters/cycloneiv_clean/asmdb_walk.py, lifters/cycloneiv_clean/hardblocks.py |
| libdb_asmdb | `0x9d8f0` | `ASMDB_DIE::operator<<` | - | lifters/cycloneiv_clean/asmdb_walk.py, lifters/cycloneiv_clean/cycloneiv_io.py, scripts/cycloneiv_clean_cff_tables.py |
| libddb_dev | `0x15e930` | `DEV_PIN::operator<<` | - | lifters/cycloneiv_clean/pkgpad.py |
| libddb_dev | `0x16aac0` | `DEV_PKG_INFO_BODY::operator<<` | - | - |
| libddb_dygr | `0x2caf80` | `DYGR_ROUTE_ASM_BIT::operator<<` | - | lifters/cycloneiv_clean/tracer.py |
| libddb_dygr | `0x2cae40` | `DYGR_ROUTE_ASM_NODE::operator<<` | - | - |
| libcomp_asm | `0x182656` | `ASM_IO_PIN_MODEL::process_atom` | Per-pin model entry; resolves pin index for the arch groups | - |
| libcomp_asm | `0x190456` | `ASM_IO_PIN_MODEL::init_pin_modes_from_chip` | Builds per-pin mode table from CDB_CHIP_DB_ENTRY (pad info from ddb pad file) | - |
| libcomp_asm | `0x199bbe` | `ASM_IO_PIN_MODEL::construct_gid_to_pin_index_map` | gid -> pin index map; uses dirt index cache type 0x17 (INDEX_CACHE) | - |
| libcomp_asm | `0x19a474` | `ASM_IO_PIN_MODEL_YGR::ASM_IO_PIN_MODEL_YGR` | Pin model ctor takes (CDB_CHIP_DB_ENTRY, DEV_DIE_INFO, DEV_PAD_INFO): pad -> pin data comes from the pad ddb ( | - |
| libcomp_asm | `0x2b3795` | `asm_convert_db_to_asm_iost` | DEV_IO_STANDARD_ENUM -> asm IOST class 0 | - |
| libcomp_asm | `0x183f16` | `ASM_IO_USE_PULL_UP::process_atom` | Boolean mux in group IO_USE_PULL_UP (enum 178): value = cut_io_util->vtbl+0x88(atom) | - |
| libcomp_asm | `0x183f82` | `ASM_IO_USE_SLOW_SLEW::process_atom` | Boolean mux in group IO_USE_SLOW_SLEW (enum 180): value = atom vtbl+0xe58 | - |
| libcomp_asm | `0x1840a8` | `ASM_IO_USE_OPEN_DRAIN::process_atom` | Boolean mux in group IO_USE_OPEN_DRAIN (enum 182): value = asm_test_atom_bit(atom, 0x16); index from ASM_MODEL | - |
| libcomp_asm | `0x192f74` | `ASM_IO_SET_DRIVE_STRENGTH_YGR::process_atom` | Drive strength: value from get_settings(io_standard, current_strength, vio/hio pad,  | - |
| libcomp_asm | `0x192a02` | `ASM_IO_SET_DRIVE_STRENGTH_YGR::get_settings` | Walks the global dirt tree: IO -> IO_SET_DRIVE_STRENGTH_YGR -> IO_STANDARD(str) -> CURRENT_STRENGTH(str) -> VI | - |
| libcomp_asm | `0x191c12` | `ASM_IO_SELECT_IOST_DIRT::get_settings` | IO standard setting lookup in the dirt tree by DEV_IO_STANDARD_ENUM | - |
| libcomp_asmcc | `0x2891c` | `ASM_ARCH_GROUP::resolve_io_index_for_block` | Returns the IO index of the current atom's pin for this group's block type; 0xffffffff = none | lifters/cycloneiv_clean/io_encode.py |
| libdb_asmdb | `0x94c16` | `asmdb_get_debug_string` | Block-type enum -> name via ASMDB_TRANSLATOR::m_asmdb_arch_group_block_type_debug_string_table | - |
| libdb_pdb | `0xdf50` | `PDB_SEGMENT_READER::xfr_ptr` | Pointer tag u32: 0 null; bit0 set = u16 adjust + u16 class idx follow; bit1 set = back-reference, id = (tag>>2 | lifters/cycloneiv_clean/asmdb_walk.py, scripts/cycloneiv_clean_dirt.py |
| libdb_pdb | `0xec50` | `PDB_SEGMENT_READER::finish_reading_all` | Pool order: stack (LIFO) of static pointer types with pending objects; pop head, read ALL its pending objects  | lifters/cycloneiv_clean/asmdb_walk.py, scripts/cycloneiv_clean_dirt.py |
| libdb_pdb | `0xd3e0` | `PDB_SEGMENT_READER::xfr_int_delta` | Value = stream i32 + same field of the reference object (previous object of the pool / previous element), not  | lifters/cycloneiv_clean/asmdb_walk.py, scripts/cycloneiv_clean_dirt.py |
| libdb_pdb | `0x17990` | `PDB_SEGMENT_READER::xfr_stl_ptr` | STL container of pointers (serializer slot +0x28) | lifters/cycloneiv_clean/asmdb_walk.py, scripts/cycloneiv_clean_dirt.py |
| libdb_pdb | `0xe930` | `PDB_SEGMENT_READER::xfr_new` | Allocate/register object; vtable slot index 0x28 | lifters/cycloneiv_clean/asmdb_walk.py, scripts/cycloneiv_clean_dirt.py |
| libddb_dev | `0x1751a0` | `operator<<` | QTL_BOOL_VECTOR serializer: u32 nbits (xfr_int) then ceil(nbits/32) words, each xfr_int_delta against the prev | lifters/cycloneiv_clean/asmdb_walk.py, lifters/cycloneiv_clean/cycloneiv_io.py, lifters/cycloneiv_clean/pkgpad.py |
| libcomp_asm | `0x1caa60` | `ASM_OPTION_REG_USE_CLKUSR::process_end_of_phase` | Option bit 0 = NOT CDB_CHIP_DB_ENTRY::is_user_start_up_clock (QSF USER_START_UP_CLOCK ON -> 0) | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1caafc` | `ASM_OPTION_REG_RELEASE_CLEAR_BEFORE_TRI::process_end_of_phase` | Option bit 2 = NOT ACF bool option 0x4c6 (RELEASE_CLEARS_BEFORE_TRI_STATES) | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cab5a` | `ASM_OPTION_REG_ENABLE_AUTO_RECONFIGURE::process_end_of_phase` | Option bit 6 = ACF bool option 0x4c7 (AUTO_RESTART_CONFIGURATION), direct polarity (dumb group arch byte 1); d | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cac7a` | `ASM_OPTION_REG_USE_INITDONE::process_end_of_phase` | Option bit 3 = NOT is_init_done (ENABLE_INIT_DONE_OUTPUT ON -> 0) | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x18e112` | `ASM_DEVICE_USE_GLOBAL_CLEAR::process_end_of_phase` | Option bit 4 = NOT is_dev_clr (ENABLE_DEVICE_WIDE_RESET) | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x18e158` | `ASM_DEVICE_USE_GLOBAL_TRI::process_end_of_phase` | Option bit 5 = NOT is_dev_oe (ENABLE_DEVICE_WIDE_OE) | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cacc0` | `ASM_OPTION_REG_USE_ERROR_DETECT::process_atom` | crcblock atom sets m_value 1 (or 2 for internal scrubbing); option bit 8 cleared when m_value or the QSF CRC o | scripts/cycloneiv_clean_option_pairs.py, scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cd832` | `ASM_OPTION_REG_USE_ERROR_DETECT::process_end_of_phase` | Writes the USE_ERROR_DETECT mux from m_value; bit 92 set only by the QSF CRC_ERROR_CHECKING option (pair crc_c | scripts/cycloneiv_clean_option_pairs.py, scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1caef6` | `ASM_OPTION_REG_SELECT_CRC_FREQUENCY_DIVIDER::process_atom` | Reads the crcblock oscillator_divider via cga_interface param 0x32; all crcblock atoms must agree (internal er | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cbf96` | `ASM_OPTION_REG_SELECT_CRC_FREQUENCY_DIVIDER::process_end_of_phase` | get_settings(divisor) -> option bits 27 | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cb268` | `ASM_OPTION_REG_SELECT_SPI_PIN_STATE::process_end_of_phase` | Option bits 9,10 = 2-bit SPI pin state: programming mode PS/FPP etc 3; active serial flash mode 1 -> 2; flash  | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cbc2e` | `ASM_OPTION_REG_SET_POF_ID::process_end_of_phase` | Option bits 11 | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cb48a` | `ASM_OPTION_REG_USE_NCEO::process_end_of_phase` | Option bit 91 = NOT (get_nceo_reserved_mode != 5); QSF CYCLONEII_RESERVE_NCEO_AFTER_CONFIGURATION 'USE AS REGU | scripts/cycloneiv_clean_class_bind.py, scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cb4d6` | `ASM_OPTION_REG_WAIT_FOR_OCTDONE::process_end_of_phase` | Option bit 93 = NOT ACF bool option 0x4cd (ENABLE_OCT_DONE ON -> 0) | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cb676` | `ASM_OPTION_REG_EXTERNAL_CLK_SPI::process_end_of_phase` | Option bits 128,129 = ACF enum option 0x3ed (ACTIVE_SERIAL_CLOCK) through asmdb index map {262:3, 263:1, 264:0 | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1cb5ee` | `ASM_OPTION_REG_JTAG_CORE_ACCESS::process_atom` | No asmdb group on the EP4CGX150 die (no option bit written) | - |
| libcomp_asm | `0x1cb97a` | `ASM_OPTION_REG_USE_NCE::process_end_of_phase` | No asmdb group on the EP4CGX150 die (no option bit written); same for USE_JTAG_PIN_SHARE 1cb9c0, USE_NCONFIG 1 | scripts/cycloneiv_clean_class_bind.py, scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x18fdde` | `ASM_JTAG_WRITE_USER_CODE::process_end_of_phase` | No asmdb group on this die: USERCODE is written through ASM_BITFIELD::set_jtag_user_code to sof tag 19 (u32 at | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1877a2` | `ASM_JTAG_PIA_TO_TDOUSER::process_atom` | Std group JTAG_PIA_TO_TDOUSER (enum 523, block CONTROL): 16 CRAM bits (2 muxes 14 + 2); tdouser driven from th | scripts/cycloneiv_clean_options_build.py |
| libcomp_asm | `0x1878f0` | `ASM_JTAG_PIA_TO_TDOUTAP::process_atom` | Std group JTAG_PIA_TO_TDOUTAP (enum 524): 16 CRAM bits; the fitter rejects a driven tdoutap port on this die,  | scripts/cycloneiv_clean_options_build.py |
| libddb_dygr | `0x23bfe0` | `DYGR_ROUTE_ASM_INFO_BODY::get_bits_from_source_to_dest` | Conduction bit list of edge (src,dst): bits of src's group for dst (value 1 if not use-encoded, else encoded_h | lifters/cycloneiv_clean/tracer.py |
| libddb_dygr | `0x23c910` | `DYGR_ROUTE_ASM_INFO_BODY::check_routing_connection` | Verifier: use_encoded_setting of an exclusion group's first bit = 0 one-hot, 1 fully encoded, 2 inverted-encod | lifters/cycloneiv_clean/tracer.py |
| libddb_dygr | `0x23ab90` | `DYGR_ROUTE_ASM_BIT::use_encoded_setting` | 0 if bit31 flag clear (one-hot); else 1 + byte4 bit1 | lifters/cycloneiv_clean/tracer.py |
| libddb_dygr | `0x23abb0` | `DYGR_ROUTE_ASM_BIT::is_encoded_bit_high` | Value of an encoded bit = byte4 bit0 (only valid when use_encoded_setting != 0) | lifters/cycloneiv_clean/tracer.py |
| libddb_dygr | `0x23a830` | `DYGR_ROUTE_ASM_NODE::setup_bit_groups` | Group order in a node: destination (fan-out) groups first, exclusion groups last | - |
| libddb_dygr | `0x23bd40` | `DYGR_ROUTE_ASM_INFO_BODY::get_exclusion_bit_group` | Exclusion group i of node n = start index field of the node's route info + i | lifters/cycloneiv_clean/tracer.py |
| libddb_dygr | `0x23bdf0` | `DYGR_ROUTE_ASM_INFO_BODY::get_destination_bit_group` | Group index = position of dst in src's fan-out list (first_dest + offsets) | lifters/cycloneiv_clean/tracer.py |
| libdb_asmdb | `0x8e8a4` | `ASMDB_BLOCK_INFO::calculate_bits_traditional` | Used when both icd/bcm strings are empty (all IV GX BLOCK_INFOs) | lifters/cycloneiv_clean/asmdb_walk.py, lifters/cycloneiv_clean/hardblocks.py |
| libdb_asmdb | `0x8f9b6` | `ASMDB_BLOCK_INFO::calculate_bits` | Dispatch: icd name empty -> traditional; else bcm address-space string empty -> bcm_style_absolute; else bcm_s | lifters/cycloneiv_clean/asmdb_walk.py, lifters/cycloneiv_clean/hardblocks.py |
| libcomp_asm | `0x1976d0` | `ASM_ASMDBIO::search_for_io_arch_groups` | Factory: switch on ASMDB_ARCH_GROUP_TYPE (group+0xc), news the ASM_* processing class (vtable store) | lifters/cycloneiv_clean/hardblocks.py, scripts/cycloneiv_clean_class_bind.py |
| libcomp_asm | `0x1cc012` | `ASM_ASMDBIO::search_for_option_register_arch_groups` | Option-register factory; reproduces the group_type of all 13 pair-confirmed option groups (tests/cycloneiv_cle | lifters/cycloneiv_clean/hardblocks.py, scripts/cycloneiv_clean_class_bind.py |
| libcomp_asm | `0x17ae44` | `ASM_ASMDBIO::search_for_le_arch_groups` | LE factory (case 0xb = LE_USE_CARRY) | lifters/cycloneiv_clean/hardblocks.py, scripts/cycloneiv_clean_class_bind.py |
| libcomp_asm | `0x159466` | `ASM_ASMDBIO::search_for_lab_arch_groups` | LAB factory | lifters/cycloneiv_clean/hardblocks.py, scripts/cycloneiv_clean_class_bind.py |
| libcomp_asm | `0x1b41d8` | `ASM_ASMDBIO::search_for_pll_arch_groups` | PLL factory (74 PLL group types of this die bound) | lifters/cycloneiv_clean/hardblocks.py, scripts/cycloneiv_clean_class_bind.py |
| libcomp_asm | `0x2f9ff2` | `ASM_ASMDBIO::search_for_clockspine_arch_groups` | Clock spine / CLKBUF factory | lifters/cycloneiv_clean/hardblocks.py, scripts/cycloneiv_clean_class_bind.py |
| libcomp_asm | `0x101f66` | `ASM_MODEL_GENERATOR_YGR::create_models` | Stingray (YGR) model registration: ASM_CDB_NODE_MODEL_YGR, ASM_CHAIN_AND_CLA_MONITOR_YGR, ASM_FINP_CZAR_YGR, A | - |
| libcomp_asmgx | `0x38cd6` | `asmgx_search_for_arch_groups` | GX factory: one jump table, types 0x431 | lifters/cycloneiv_clean/hardblocks.py, scripts/cycloneiv_clean_class_bind.py |
| libcomp_asmgx | `0x4c33a` | `ASMGX_CENTRAL_CGA_ENUM::process_atom` | Generic CGA-enum writer: reads the atom's CGA param (ids 0x40 for group types 0x45c/0x658, 0x84 for 0x438, 0x4 | - |
| libcomp_asm | `0x1a1f54` | `ASM_PLL_M_HIGH_COUNTER::process_atom` | M counter high = (M+1)>>1 (uneven split); mux_select(PLL_M_HIGH_COUNTER, pll_index, value) | lifters/cycloneiv_clean/pll.py |
| libcomp_asm | `0x1a2022` | `ASM_PLL_M_LOW_COUNTER::process_atom` | M counter low = M>>1 | - |
| libcomp_asm | `0x1a223a` | `ASM_PLL_N_HIGH_COUNTER::process_atom` | N high = (N+1)>>1; low group is the N>>1 sibling | - |
| libcomp_asm | `0x1a246a` | `ASM_PLL_CHARGE_PUMP_CURRENT::process_atom` | Value = model getter (vtbl +0xf0) = netlist charge_pump_current_bits (28 of 28) | - |
| libcomp_asm | `0x1a24da` | `ASM_PLL_LOOP_FILTER_R::process_atom` | Value = model getter (vtbl +0x100); not an altpll parameter (value depends on M/N/bandwidth) | - |
| libcomp_asm | `0x1a278c` | `ASM_PLL_VCO_DIVIDE_BY_2::process_atom` | mux_select(vco_post_scale == 2); only values 1 and 2 legal | - |
| libcomp_asm | `0x1a2d56` | `ASM_PLL_OUTPUT_COUNTER_PHASE::process_atom` | Per counter (atom field +8); phase shift of altpll shows in OUTPUT_COUNTER_PRESET (c#_initial), not here (0 in | - |
| libcomp_asm | `0x1aa232` | `ASM_PLL_OUTPUT_COUNTER_HIGH_COUNTER::process_atom` | Output counter high count = netlist c#_high; group gi = counter index | - |
| libcomp_asm | `0x1a03ea` | `ASM_PLL_MODEL_STINGRAY::process_atom` | Dispatch: pll_index (static) selects ASM_SINGLE_PLL_MODEL_STINGRAY in m_plls; each ASM_PLL_* class then writes | - |
| libcomp_asm | `0x1e14b2` | `ASM_EAB_BLOCK_PORTS::write_block` | M9K port-list writer (asm_ram_extra | - |
| libcomp_asm | `0x1e2cf0` | `ASM_MAC_BLOCK_PORTS::write_block` | MAC port-list writer (asm_mac_extra | - |
| libcomp_asm | `0x1e2a8a` | `ASM_MAC_BLOCK_PORTS::find_mac_row_offset` | Row offset of a MAC within its column from the die location (4 probes) | - |
| libdb_asmdb | `0x7a3ac` | `ASMDB_ARCH_GROUP_STD::select` | select(site, value, streams): per mux_data entry i mux=paths[site][i]; bits=mux | lifters/cycloneiv_clean/io_encode.py |
| libdb_asmdb | `0x8c0ba` | `ASMDB_ENCODED_MUX::select` | Bit k of the mux (m_mux_bits[k]) = (value >> k) & 1; value >= 2^nbits is an internal error (ENCODED_MUX::selec | lifters/cycloneiv_clean/io_encode.py |
| libdb_asmdb | `0x8c19a` | `ASMDB_MAPPED_ENCODED_MUX::select` | value = m_map_mux | lifters/cycloneiv_clean/io_encode.py |
| libdb_asmdb | `0x78f4c` | `ASMDB_ARCH_GROUP_DUMB::select` | One bit per site (m_bits[site]); value must be 0/1; bit = (value == 0) when arch_value == 0 else (value != 0) | lifters/cycloneiv_clean/io_encode.py |
| libcomp_asm | `0x18a892` | `ASM_IO_SELECT_IOST::process_atom` | IOST value = mux_select(group, io_index, v): v = 3 for a reserved / unused pin (cut_io_util vcall 0x28 flag 3) | - |
| libcomp_asm | `0x18f446` | `ASM_IO_USE_PCI_DIODE_CLAMP::process_atom` | PCI diode clamp bit = atom flag (byte at +8, bit 5, is_pci_io_enabled) via mux_select(group, io_index, flag);  | - |

## Struct classes (serializer-mined)

| Lib | Struct | Size | Fields |
|---|---|---|---|
| libdb_asmdb | `ASMDB_ARCH_GROUP_BASE` | 24 | 3 |
| libdb_asmdb | `ASMDB_ARCH_GROUP_CALC` | 96 | 6 |
| libdb_asmdb | `ASMDB_ARCH_GROUP_CERBERUS` | 88 | 9 |
| libdb_asmdb | `ASMDB_ARCH_GROUP_DUMB` | 32 | 2 |
| libdb_asmdb | `ASMDB_ARCH_GROUP_STD` | 56 | 3 |
| libdb_asmdb | `ASMDB_AVALON_ADDRESS` | 16 | 2 |
| libdb_asmdb | `ASMDB_BLOCK_INFO` | 152 | 10 |
| libdb_asmdb | `ASMDB_DECISION_MUX` | 40 | 2 |
| libdb_asmdb | `ASMDB_DEFAULT_BIT_CALC` | 24 | 3 |
| libdb_asmdb | `ASMDB_DEFAULT_MUX_SETTING` | 24 | 3 |
| libdb_asmdb | `ASMDB_DIE` | 608 | 20 |
| libdb_asmdb | `ASMDB_DIRT` | 16 | 2 |
| libdb_asmdb | `ASMDB_DIRT_INNER` | 24 | 2 |
| libdb_asmdb | `ASMDB_DIRT_INTEGER` | 24 | 2 |
| libdb_asmdb | `ASMDB_DIRT_STRING` | 24 | 2 |
| libdb_asmdb | `ASMDB_ENCODED_BANK_MUX` | 40 | 3 |
| libdb_asmdb | `ASMDB_HC_WIRE_DATA` | 64 | 10 |
| libdb_asmdb | `ASMDB_LABELED_SIMPLE_MUX` | 40 | 2 |
| libdb_asmdb | `ASMDB_MAPPED_ENCODED_MUX` | 40 | 2 |
| libdb_asmdb | `ASMDB_MAPPED_SIMPLE_MUX` | 40 | 2 |
| libdb_asmdb | `ASMDB_MUX` | 32 | 1 |
| libdb_asmdb | `ASMDB_MUX_DATA` | 24 | 3 |
| libdb_asmdb | `ASMDB_MUX_STL_DATA` | 32 | 4 |
| libdb_asmdb | `ASMDB_PARAM_MASTER_BASE` | 48 | 6 |
| libdb_asmdb | `ASMDB_PARAM_MASTER_BITVEC` | 56 | 2 |
| libdb_asmdb | `ASMDB_PARAM_MASTER_ENUM` | 56 | 2 |
| libdb_asmdb | `ASMDB_RAM_MUX` | 40 | 2 |
| libdb_asmdb | `ASMDB_SIMPLE_BANK_MUX` | 40 | 3 |
| libdb_asmdb | `ASMDB_TABLE_ENCODED_MUX` | 48 | 3 |
| libdb_asmdb | `ASMDB_ZEROED_ENCODED_MUX` | 48 | 2 |
| libddb_dev | `DEV_PAD_BODY` | 968 | 14 |
| libddb_dev | `DEV_PAD_INFO_BODY` | 2008 | 18 |
| libddb_dev | `DEV_PIN` | 584 | 10 |
| libddb_dev | `DEV_PKG_INFO_BODY` | 656 | 1 |
