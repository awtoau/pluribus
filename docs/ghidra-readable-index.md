# Ghidra readable-code index (#165, #168)

Names, addresses and purposes only; pseudo-code is local under `vendor-analysis/altera/analysis/readable/` (gitignored). How to build it: [ghidra-workflow.md](ghidra-workflow.md).

## Layers

| Enum | Constants | Source table |
|---|---|---|
| `ASMDB_ARCH_GROUP_BLOCK_TYPE` | 542 | `enums.tsv` (vendor debug-string table) |
| `ASMDB_ARCH_GROUP_TYPE` | 4663 | `enums.tsv` (vendor debug-string table) |
| `ASMDB_DIRT_TYPE` | 303 | `enums.tsv` (vendor debug-string table) |
| `DEV_ELEMENT_ENUM` | 2715 | `enums.tsv` (vendor debug-string table) |

## Library inventory (`scripts/ghidra_inventory.py`)

893 files in `linux64` classified; 181 adjacent, 96 core (imported into the project by `ghidra_apply_names.py import-core`).

| Core lib | Dynamic symbols | Symbol hits (stingray/ygr/asmdb/cut/...) |
|---|---|---|
| libatm_astr.so | 34374 | 869 |
| libatm_autil.so | 37 | 11 |
| libatm_aygr.so | 162 | 2 |
| libcbx_stingray.so | 195 | 3 |
| libcomp_asm.so | 2046 | 471 |
| libcomp_asm2.so | 368 | 30 |
| libcomp_asmcc.so | 846 | 180 |
| libcomp_asmdbg.so | 274 | 48 |
| libcomp_asmdd.so | 644 | 12 |
| libcomp_asmgx.so | 807 | 128 |
| libcomp_asmio.so | 430 | 123 |
| libcomp_asmmac.so | 313 | 78 |
| libcomp_asmpll.so | 160 | 27 |
| libcomp_asmram.so | 480 | 74 |
| libdb_asmdb.so | 1456 | 1297 |
| libdb_cdb.so | 918 | 235 |
| libdb_cdb_atom.so | 4284 | 271 |
| libdb_cdb_atom_cuda.so | 4547 | 519 |
| libdb_cdb_atom_dynamic.so | 2021 | 70 |
| libdb_cdb_atom_generic.so | 1872 | 70 |
| libdb_cdb_atom_stingray.so | 2532 | 238 |
| libdb_cdb_atom_syn.so | 2075 | 115 |
| libdb_cdb_atom_ygr.so | 3594 | 1411 |
| libdb_cut.so | 8299 | 4021 |
| libdb_cut_dev.so | 387 | 174 |
| libdb_pdb.so | 232 | 80 |
| libdb_rbc.so | 5406 | 222 |
| libdb_rcf.so | 491 | 119 |
| libdb_u2b.so | 999 | 76 |
| libdb_u2b2_cdb.so | 2265 | 217 |
| libdb_u2b2_cdb_tcl.so | 258 | 15 |
| libdb_u2b2_cfg.so | 195 | 29 |
| libdb_u2b2_core.so | 1031 | 41 |
| libdb_u2b2_routing.so | 292 | 10 |
| libdb_u2b_bcm.so | 201 | 66 |
| libdb_u2b_cfg.so | 443 | 135 |
| libdb_u2b_tcl.so | 82 | 3 |
| libddb_asmmdb.so | 381 | 8 |
| libddb_bcm2bits.so | 173 | 2 |
| libddb_dbcm.so | 1178 | 239 |
| libddb_dbcm_tcl.so | 364 | 7 |
| libddb_dcalc.so | 644 | 32 |
| libddb_dev.so | 2634 | 2184 |
| libddb_dlib.so | 431 | 38 |
| libddb_dloc.so | 174 | 93 |
| libddb_dmgr.so | 367 | 229 |
| libddb_dmig.so | 446 | 187 |
| libddb_dpow.so | 1147 | 95 |
| libddb_dspf.so | 575 | 111 |
| libddb_dstr.so | 18175 | 18125 |
| libddb_dtcl.so | 443 | 242 |
| libddb_dtm.so | 824 | 195 |
| libddb_dygr.so | 2840 | 2414 |
| libddb_dygr_fdi.so | 1202 | 946 |
| libddb_dygr_qdl.so | 334 | 158 |
| libddb_fdi_build.so | 505 | 156 |
| libddb_fdi_data.so | 865 | 277 |
| libddb_ihc.so | 214 | 22 |
| libddb_ihc_tcl.so | 160 | 3 |
| libfitter_fhssi.so | 853 | 126 |
| libfitter_fygr.so | 1791 | 748 |
| libperiph_cclk.so | 1522 | 240 |
| libperiph_cio.so | 925 | 290 |
| libperiph_cpll.so | 420 | 50 |
| libperiph_cpll_dc.so | 13 | 2 |
| libperiph_hssi.so | 1150 | 312 |
| libpgm_build_npcf.so | 700 | 198 |
| libpgm_common.so | 592 | 268 |
| libpgm_cpfq.so | 1029 | 39 |
| libpgm_cseq.so | 504 | 15 |
| libpgm_dev.so | 315 | 60 |
| libpgm_fbgen.so | 397 | 1 |
| libpgm_fidq.so | 694 | 11 |
| libpgm_fidq_common.so | 442 | 56 |
| libpgm_gfpdb.so | 291 | 148 |
| libpgm_gfpq.so | 707 | 51 |
| libpgm_japi.so | 144 | 4 |
| libpgm_jbc2.so | 118 | 2 |
| libpgm_nios2.so | 199 | 5 |
| libpgm_npcf.so | 486 | 167 |
| libpgm_pgmalgo.so | 285 | 18 |
| libpgm_pgmasst.so | 93 | 1 |
| libpgm_pgmd_common.so | 393 | 26 |
| libpgm_pgmdq.so | 665 | 11 |
| libpgm_pgme.so | 550 | 154 |
| libpgm_pgmio.so | 2462 | 863 |
| libpgm_pgmtq.so | 802 | 24 |
| libpgm_pgmwq.so | 1421 | 103 |
| libpgm_sppv_ddb.so | 591 | 94 |
| libpower_patfam_ygr.so | 305 | 84 |
| quartus_asm | 278 | 29 |
| quartus_cdb | 743 | 72 |
| quartus_cpf | 334 | 36 |
| quartus_fit | 85 | 0 |
| quartus_map | 734 | 51 |
| quartus_pow | 229 | 22 |

## Per library

| Lib | Classes with vtable | Mined structs | Exported class files |
|---|---|---|---|
| libcomp_asm | 960 | 0 | 790 |
| libcomp_asm2 | 114 | 0 | 0 |
| libcomp_asmcc | 19 | 0 | 10 |
| libcomp_asmgx | 480 | 0 | 184 |
| libcomp_asmio | 259 | 0 | 246 |
| libcomp_asmmac | 188 | 0 | 181 |
| libcomp_asmpll | 47 | 0 | 30 |
| libcomp_asmram | 128 | 0 | 122 |
| libdb_asmdb | 10 | 30 | 53 |
| libdb_cdb_atom_stingray | 1 | 0 | 0 |
| libdb_cdb_atom_ygr | 2 | 0 | 21 |
| libdb_cut | 290 | 0 | 1 |
| libdb_pdb | 15 | 0 | 2 |
| libdb_u2b_bcm | 1 | 0 | 0 |
| libddb_bcm2bits | 22 | 0 | 0 |
| libddb_dbcm | 44 | 0 | 0 |
| libddb_dev | 10 | 4 | 46 |
| libddb_dstr | 46 | 0 | 0 |
| libddb_dygr | 28 | 0 | 59 |
| libpgm_fbgen | 26 | 0 | 0 |
| libpgm_pgmio | 74 | 0 | 40 |
| libpgm_pof | 54 | 0 | 0 |

## Key functions

| Lib | Vaddr | Function | Purpose | Clean-tree user |
|---|---|---|---|---|
| libcomp_asm | `0x19101c` | `ASM_IO_PIN_MODE::process_atom` | this + atom + streams: demangled signature lacked this | lifters/cycloneiv_clean/cycloneiv_io.py, scripts/cycloneiv_clean_io_od.py |
| libcomp_asm | `0x183e34` | `ASM_IO_USE_BUS_HOLD::process_atom` | - | scripts/cycloneiv_clean_asm_classes.py, scripts/cycloneiv_clean_class_bind.py |
| libcomp_asm | `0x190e70` | `ASM_IO_PIN_MODE::handle_ygr_dual_pin_iost` | non-virtual member: demangled args + this | lifters/cycloneiv_clean/cycloneiv_io.py, scripts/cycloneiv_clean_io_od.py |
| libcomp_asmcc | `0x1a240` | `ASM_BITFIELD::silent_set_bits` | settings = std::vector<DB_BIT_SETTING> (uint32 address, value byte) | lifters/cycloneiv_clean/cycloneiv_io.py, lifters/cycloneiv_clean/m9k.py, scripts/cycloneiv_clean_options_build.py |
| libcomp_asmcc | `0x1aca0` | `ASM_BITFIELD::set_bits` | settings = std::vector<DB_BIT_SETTING> | lifters/cycloneiv_clean/cycloneiv_io.py, lifters/cycloneiv_clean/m9k.py, scripts/cycloneiv_clean_options_build.py |
| libcomp_asmcc | `0x28526` | `ASM_ARCH_GROUP::mux_select` | parameter roles from IO direction use | lifters/cycloneiv_clean/io_encode.py, lifters/cycloneiv_clean/io_line.py |
| libdb_asmdb | `0x9dbbc` | `ASMDB_BLOCK_INFO::operator<<` | - | lifters/cycloneiv_clean/asmdb_walk.py, lifters/cycloneiv_clean/hardblocks.py |
| libdb_asmdb | `0x9d8f0` | `ASMDB_DIE::operator<<` | - | lifters/cycloneiv_clean/asmdb_walk.py, lifters/cycloneiv_clean/cycloneiv_io.py, scripts/cycloneiv_clean_cff_tables.py |
| libddb_dev | `0x15e930` | `DEV_PIN::operator<<` | - | lifters/cycloneiv_clean/pkginfer.py, lifters/cycloneiv_clean/pkgpad.py |
| libddb_dev | `0x16aac0` | `DEV_PKG_INFO_BODY::operator<<` | - | - |
| libddb_dygr | `0x2caf80` | `DYGR_ROUTE_ASM_BIT::operator<<` | - | lifters/cycloneiv_clean/tracer.py |
| libddb_dygr | `0x2cae40` | `DYGR_ROUTE_ASM_NODE::operator<<` | - | - |
| libcomp_asmcc | `0x28612` | `ASM_ARCH_GROUP::mux_select` | overload with a bool value | lifters/cycloneiv_clean/io_encode.py, lifters/cycloneiv_clean/io_line.py |
| libcomp_asmcc | `0x286c0` | `ASM_ARCH_GROUP::mux_select` | overload with a value list | lifters/cycloneiv_clean/io_encode.py, lifters/cycloneiv_clean/io_line.py |
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
| libcomp_asmcc | `0x2891c` | `ASM_ARCH_GROUP::resolve_io_index_for_block` | Returns the IO index of the current atom's pin for this group's block type; 0xffffffff = none | lifters/cycloneiv_clean/io_encode.py, lifters/cycloneiv_clean/io_line.py |
| libdb_asmdb | `0x94c16` | `asmdb_get_debug_string` | Block-type enum -> name via ASMDB_TRANSLATOR::m_asmdb_arch_group_block_type_debug_string_table | - |
| libdb_pdb | `0xdf50` | `PDB_SEGMENT_READER::xfr_ptr` | Pointer tag u32: 0 null; bit0 set = u16 adjust + u16 class idx follow; bit1 set = back-reference, id = (tag>>2 | lifters/cycloneiv_clean/asmdb_walk.py, scripts/cycloneiv_clean_dirt.py |
| libdb_pdb | `0xec50` | `PDB_SEGMENT_READER::finish_reading_all` | Pool order: stack (LIFO) of static pointer types with pending objects; pop head, read ALL its pending objects  | lifters/cycloneiv_clean/asmdb_walk.py, scripts/cycloneiv_clean_dirt.py |
| libdb_pdb | `0xd3e0` | `PDB_SEGMENT_READER::xfr_int_delta` | Value = stream i32 + same field of the reference object (previous object of the pool / previous element), not  | lifters/cycloneiv_clean/asmdb_walk.py, scripts/cycloneiv_clean_dirt.py |
| libdb_pdb | `0x17990` | `PDB_SEGMENT_READER::xfr_stl_ptr` | STL container of pointers (serializer slot +0x28) | lifters/cycloneiv_clean/asmdb_walk.py, scripts/cycloneiv_clean_dirt.py |
| libdb_pdb | `0xe930` | `PDB_SEGMENT_READER::xfr_new` | Allocate/register object; vtable slot index 0x28 | lifters/cycloneiv_clean/asmdb_walk.py, scripts/cycloneiv_clean_dirt.py |
| libddb_dev | `0x1751a0` | `operator<<` | QTL_BOOL_VECTOR serializer: u32 nbits (xfr_int) then ceil(nbits/32) words, each xfr_int_delta against the prev | lifters/cycloneiv_clean/asmdb_walk.py, lifters/cycloneiv_clean/blockiface.py, lifters/cycloneiv_clean/cycloneiv_io.py |
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
| libcomp_asm | `0x1a278c` | `ASM_PLL_VCO_DIVIDE_BY_2::process_atom` | mux_select(vco_post_scale == 2); only values 1 and 2 legal | lifters/cycloneiv_clean/pll.py |
| libcomp_asm | `0x1a2d56` | `ASM_PLL_OUTPUT_COUNTER_PHASE::process_atom` | Per counter (atom field +8); phase shift of altpll shows in OUTPUT_COUNTER_PRESET (c#_initial), not here (0 in | - |
| libcomp_asm | `0x1aa232` | `ASM_PLL_OUTPUT_COUNTER_HIGH_COUNTER::process_atom` | Output counter high count = netlist c#_high; group gi = counter index | - |
| libcomp_asm | `0x1a03ea` | `ASM_PLL_MODEL_STINGRAY::process_atom` | Dispatch: pll_index (static) selects ASM_SINGLE_PLL_MODEL_STINGRAY in m_plls; each ASM_PLL_* class then writes | - |
| libcomp_asm | `0x1e14b2` | `ASM_EAB_BLOCK_PORTS::write_block` | M9K port-list writer (asm_ram_extra | - |
| libcomp_asm | `0x1e2cf0` | `ASM_MAC_BLOCK_PORTS::write_block` | MAC port-list writer (asm_mac_extra | - |
| libcomp_asm | `0x1e2a8a` | `ASM_MAC_BLOCK_PORTS::find_mac_row_offset` | Row offset of a MAC within its column from the die location (4 probes) | - |
| libdb_asmdb | `0x7a3ac` | `ASMDB_ARCH_GROUP_STD::select` | select(site, value, streams): per mux_data entry i mux=paths[site][i]; bits=mux | lifters/cycloneiv_clean/asmdb_select.py, lifters/cycloneiv_clean/ffctl.py, lifters/cycloneiv_clean/io_encode.py |
| libdb_asmdb | `0x8c0ba` | `ASMDB_ENCODED_MUX::select` | Bit k of the mux (m_mux_bits[k]) = (value >> k) & 1; value >= 2^nbits is an internal error (ENCODED_MUX::selec | lifters/cycloneiv_clean/asmdb_select.py, lifters/cycloneiv_clean/io_encode.py |
| libdb_asmdb | `0x8c19a` | `ASMDB_MAPPED_ENCODED_MUX::select` | value = m_map_mux | lifters/cycloneiv_clean/io_encode.py |
| libdb_asmdb | `0x78f4c` | `ASMDB_ARCH_GROUP_DUMB::select` | One bit per site (m_bits[site]); value must be 0/1; bit = (value == 0) when arch_value == 0 else (value != 0) | lifters/cycloneiv_clean/asmdb_select.py, lifters/cycloneiv_clean/io_encode.py |
| libcomp_asm | `0x18a892` | `ASM_IO_SELECT_IOST::process_atom` | IOST value = mux_select(group, io_index, v): v = 3 for a reserved / unused pin (cut_io_util vcall 0x28 flag 3) | - |
| libcomp_asm | `0x18f446` | `ASM_IO_USE_PCI_DIODE_CLAMP::process_atom` | PCI diode clamp bit = atom flag (byte at +8, bit 5, is_pci_io_enabled) via mux_select(group, io_index, flag);  | - |
| libcomp_asmio | `0x622d2` | `ASMIO_MIO_SELECT_IOST_DIRT::process_atom` | Stingray IOST: value = get_settings(std, block) from the asmdb dirt ARCH_GROUPS table (IO_STANDARD -> SETTINGS | - |
| libcomp_asmio | `0x5def4` | `ASMIO_MIO_SET_PULLDOWN_STRENGTH::process_atom` | Pull-down strength = CGA integer parameter 0xf6 written as is via mux_select(group, io, value); value > 0 requ | - |
| libcomp_asmio | `0x5e18e` | `ASMIO_MIO_SET_PULLUP_STRENGTH::process_atom` | Pull-up strength = CGA integer parameter written as is via mux_select (same structure as the pull-down writer) | - |
| libcomp_asmio | `0x63960` | `ASMIO_MIO_SET_SLEW_RATE::process_atom` | Slew = CGA integer parameter 0x11d written as is: QSF slew 0 / 1 / 2 = mux value 0 / 1 / 2 | - |
| libdb_asmdb | `0x8c334` | `ASMDB_HETEROGENEOUS_ENCODED_MUX::select` | value = ASMDB_MUX::get_bit_value(m_map_mux, value), then ASMDB_ENCODED_MUX::select; class 20 of the asmdb ddb  | lifters/cycloneiv_clean/asmdb_select.py, lifters/cycloneiv_clean/io_line.py |
| libdb_asmdb | `0x868e8` | `ASMDB_MUX::get_bit_value` | m_mux_bits[index]; index >= size is an internal error | lifters/cycloneiv_clean/asmdb_select.py, lifters/cycloneiv_clean/asmdb_walk.py |
| libcomp_asmio | `0x4d874` | `ASMIO_MIO_LABLINE_TO_DATA::process_atom` | Pad data pin: value passed to ASM_ARCH_GROUP::mux_select(group, io index, value) is ASM_RE_PROXY::get_index of | lifters/cycloneiv_clean/io_line.py |
| libcomp_asm | `0x15e138` | `ASM_LAB_CLOCK_FAST_MUX::process_end_of_phase` | LAB clock fast mux writer: gi k first level = LAB_CONTROL_MUX 0 | lifters/cycloneiv_clean/emit.py |
| libcomp_asm | `0x15f628` | `ASM_LAB_ENABLE_CE::process_atom` | LAB_ENABLE_CE group: gi k = 1 iff clock-enable k is used (ledger F-004) | - |
| libcomp_asm | `0x158d76` | `ASM_LAB_INVERT::process_end_of_phase` | LAB_INVERT group i <- look_up_signal_polarity(signal i) (ledger F-012) | - |
| libcomp_asm | `0x1563ae` | `ASM_SINGLE_LAB_MODEL_BASE::look_up_signal_polarity` | Signal polarity: xor for source classes in mask 0x1f80 (ledger F-013) | - |
| libcomp_asm | `0x161508` | `ASM_SINGLE_LAB_MODEL_BASE::ASM_SINGLE_LAB_MODEL_BASE` | LAB model base ctor; family jump table 0x3cd61c indexed by base_family-6, {0xe,0x30} share a handler (ledger F | - |
| libcomp_asm | `0x165038` | `ASM_LAB_MODEL_CUDA::ASM_LAB_MODEL_CUDA` | CUDA LAB model ctor (model IV GX uses): 9 VIRTUAL_LAB_LINE entries at 0x3cd760, masks clk ce clk ce sload sclr | - |
| libcomp_asm | `0x166e26` | `ASM_LAB_MODEL_TITAN::ASM_LAB_MODEL_TITAN` | TITAN LAB model ctor: 11-line VIRTUAL_LAB_LINE table at 0x3cda00, line 5 = clock; NOT the IV GX table (errata  | lifters/cycloneiv_clean/emit.py |
| libcomp_asm | `0x16ba06` | `ASM_LE_CLOCK_SELECT::process_atom` | LE_CLOCK_SELECT writes the LAB clock signal index; no polarity bit (ledger F-007) | lifters/cycloneiv_clean/emit.py |
| libcomp_asm | `0x16b05c` | `ASM_LE_LUT_FUNCTION::process_atom` | LE_LUT_FUNCTION: forwards the post-fit LUT mask to mux_select, no permutation (ledger D-002/E-A5) | - |
| libcomp_asm | `0x16c186` | `ASM_LE_USE_CARRY::process_atom` | LE_USE_CARRY: value 1 (bit clear when arch 0) = carry-in connected (ledger F-011) | lifters/cycloneiv_clean/emit.py, scripts/cycloneiv_clean_class_bind.py |
| libcomp_asm | `0x16c464` | `ASM_LE_LUT_INPUT::process_atom` | LE_LUT_INPUT: gi 0 | lifters/cycloneiv_clean/emit.py |
| libcomp_asm | `0x16e326` | `ASM_LE_REG_OUT_YGR::process_end_of_phase` | LE_REG_OUT_YGR end-of-phase writer (ledger R-001) | - |
| libcomp_asm | `0x16e66a` | `ASM_LE_REG_OUT_YGR::process_atom` | LE_REG_OUT_YGR path mapping gi 0/1/2, value = registered + 1 (ledger R-001) | - |
| libcomp_asm | `0x10a830` | `ASM_MODEL_GENERATOR_STINGRAY::create_models` | Stingray model registration: registers ASM_LAB_MODEL_CUDA, ASM_GID_MONITOR, ASM_MAC_MODEL, ASM_PLL_MODEL_STING | - |
| libcomp_asm | `0x102824` | `ASM_LUT_PORT_MAPPER::get_iterm` | Base LUT port mapper: get_iterm(atom, port) = the atom input, identity, no C/D swap (ledger L-018) | - |
| libcomp_asm | `0x1b1e2a` | `ASM_SINGLE_PLL_MODEL_STINGRAY::get_cp_and_lp_value` | PLL charge-pump / loop-filter value: returns the position of the input parameter in a row of the PLL element 2 | - |
| libcomp_asm | `0x2fd9f8` | `ASM_CLKBUF_CLK_INPUT_SELECT_CYCLONEII::process_atom` | CLKBUF_CLK_INPUT_SELECT_CYCLONEII (block 73, 30 sites): value = CLKBUF_IN index of the source (ledger B-010) | lifters/cycloneiv_clean/clkbuf.py |
| libcomp_asm | `0xfb2b6` | `ASM_CARRY_CHAIN_MONITOR_BASIC::validate_chain_le_locations` | Carry chain monitor: accepts base families 6, 0xe, 0x10, 0x38 only, none for 0x30 (ledger F-015/F-016, errata  | lifters/cycloneiv_clean/emit.py |
| libcomp_asmcc | `0x2cc36` | `ASM_RE_PROXY::get_first_useful_re_source` | ASM_RE_PROXY: skips the BIM index; mux_select takes the LI index (errata E-R6) | lifters/cycloneiv_clean/bim.py, lifters/cycloneiv_clean/clkbuf.py, lifters/cycloneiv_clean/io_line.py |
| libdb_asmdb | `0x7a566` | `ASMDB_ARCH_GROUP_CALC::select` | CALC arch group select: base + offset groups (LAB/MEAB/MAC) (ledger B-002/L-010) | lifters/cycloneiv_clean/muxsel.py |
| libdb_asmdb | `0x7b28c` | `ASMDB_ARCH_GROUP_STLMAP::select` | STLMAP arch group select (ledger L-010) | lifters/cycloneiv_clean/asmdb_select.py |
| libdb_asmdb | `0x8bec8` | `ASMDB_SIMPLE_BANK_MUX::select` | Mux class 21/SIMPLE_BANK select (ledger B-004) | - |
| libdb_asmdb | `0x8bfac` | `ASMDB_ENCODED_BANK_MUX::select` | Mux class 21 ENCODED_BANK: value bit k drives bank_size bits [bank_size*k | lifters/cycloneiv_clean/asmdb_select.py |
| libdb_asmdb | `0x86bc4` | `ASMDB_RAM_MUX::select` | Mux class 22 RAM_MUX select (overload 1 of 2, other 0x8bdca): bit i = (value>>i)&1, flipped when polarity mux  | lifters/cycloneiv_clean/asmdb_select.py |
| libdb_asmdb | `0x8bdca` | `ASMDB_RAM_MUX::select` | Mux class 22 RAM_MUX select (overload 2 of 2, bool variant) (ledger B-004) | lifters/cycloneiv_clean/asmdb_select.py |
| libdb_asmdb | `0x8c4ac` | `ASMDB_SIMPLE_MUX::select` | SIMPLE_MUX select: one-hot, bit i written (i == value) (ledger M-004/B-003) | lifters/cycloneiv_clean/asmdb_select.py, lifters/cycloneiv_clean/m9k.py, lifters/cycloneiv_clean/macctl.py |
| libdb_asmdb | `0x8c36e` | `ASMDB_DECISION_MUX::select` | DECISION_MUX select (ledger B-003) | lifters/cycloneiv_clean/asmdb_select.py |
| libdb_asmdb | `0x8c5b8` | `ASMDB_MAPPED_SIMPLE_MUX::select` | MAPPED_SIMPLE_MUX select (ledger B-002/B-003) | - |
| libdb_asmdb | `0x9b658` | `ASMDB_INDEX_MAP_WRAPPER::operator<<` | ASMDB_INDEX_MAP_WRAPPER serializer (stlmap group index map) | lifters/cycloneiv_clean/asmdb_walk.py |
| libcomp_asmio | `0x74d96` | `ASMIO_MIO_TERMINATION_CONTROL_SELECT::process_atom` | MIO_TERMINATION_CONTROL_SELECT writer (IO termination; fitter value written as is) | - |
| libcomp_asmram | `0x1efc6` | `ASM_RAM_USAGE_MODE::process_end_of_phase` | RAM_USAGE_MODE port A: flags bit1->0; else bit4->1; else (flags&0x40000008) or bit31->2 (ledger M-003) | lifters/cycloneiv_clean/m9k.py |
| libcomp_asmram | `0x1f106` | `ASM_RAM_USAGE_MODE_B::process_end_of_phase` | RAM_USAGE_MODE_B: same rule on port B flags (ledger M-003) | lifters/cycloneiv_clean/m9k.py |
| libcomp_asmram | `0x7de60` | `ASM_RAM_REG_DATA_OUT::process_end_of_phase` | RAM_REG_DATA_OUT: value = flag bit 9 (RAM_REG_DATA_OUT) of port A flags; group MAPPED_ENCODED map [1,0] (errat | lifters/cycloneiv_clean/m9k.py |
| libcomp_asmram | `0x1f6fe` | `ASM_RAM_NEW_DATA_MODE::process_end_of_phase` | RAM_NEW_DATA_MODE: set when same-port feed-through flags (bits 77/78 region, word2 0x6000) and mode bits 4/30/ | lifters/cycloneiv_clean/m9k.py |
| libcomp_asmram | `0x1fa72` | `ASM_RAM_IS_ROM_ONLY::process_end_of_phase` | RAM_IS_ROM_ONLY: value = is_intrinsic_rom(port A) and is_intrinsic_rom(port B) | lifters/cycloneiv_clean/m9k.py |
| libcomp_asmram | `0x1fd68` | `ASM_RAM_WRITE_OPTION::process_end_of_phase` | RAM_WRITE_OPTION: values 0 | lifters/cycloneiv_clean/m9k.py |
| libcomp_asmram | `0x6663e` | `ASM_RAM_MS_DATA_INPUT::process_end_of_phase` | RAM_MS_DATA_INPUT: port-input mux value = RE line index of the port source plus PIA/extra-line offsets by RE t | lifters/cycloneiv_clean/m9k.py |
| libcomp_asmram | `0x4066c` | `ASM_RAM_MODEL_YGR_MEAB::process_atom` | RAM model process_atom: dispatch and port-usage bookkeeping only; no bit tables | - |
| libcomp_asmram | `0x3e9ec` | `ASM_SINGLE_RAM_MODEL_BASE::process_ram_atom` | ASM_SINGLE_RAM_MODEL_BASE::process_ram_atom: dispatch and port-usage bookkeeping only | - |
| libcomp_asmram | `0x4a624` | `ASM_SINGLE_RAM_MODEL_YGR_MEAB::cache_ram_mode` | Caches per-port RAM flag vectors (QTL_BOOL_VECTOR) from CUT_RAM_UTIL::get_ram_mode(atom,port) at model+0x240 ( | - |
| libcomp_asmram | `0x6142c` | `ASM_SINGLE_RAM_MODEL_YGR_MEAB::cache_pia_usage` | ASM_SINGLE_RAM_MODEL_YGR_MEAB virtual: cache_pia_usage | - |
| libcomp_asmram | `0x447fc` | `ASM_SINGLE_RAM_MODEL_YGR_MEAB::plot_data_in_mapping` | ASM_SINGLE_RAM_MODEL_YGR_MEAB virtual: plot_data_in_mapping | - |
| libcomp_asmmac | `0x2ded6` | `ASM_MAC_IREG_SIGN::process_end_of_phase` | MAC_IREG_SIGN writer (ledger M-009) | lifters/cycloneiv_clean/mac.py |
| libcomp_asmmac | `0x2e4ee` | `ASM_MAC_PREG_SIGN::process_end_of_phase` | MAC_PREG_SIGN writer (ledger M-009) | lifters/cycloneiv_clean/mac.py |
| libcomp_asmmac | `0x2ed7e` | `ASM_MAC_OREG_SHFTR::process_end_of_phase` | MAC_OREG_SHFTR writer (ledger M-009) | lifters/cycloneiv_clean/mac.py |
| libcomp_asmmac | `0x501b0` | `ASM_MAC_IREG_SMODE::process_end_of_phase` | MAC_IREG_SMODE writer (ledger M-009) | lifters/cycloneiv_clean/mac.py |
| libcomp_asmmac | `0x50d56` | `ASM_MAC_USAGE_MODE::process_end_of_phase` | MAC_USAGE_MODE writer (ledger M-009) | lifters/cycloneiv_clean/mac.py |
| libcomp_asmmac | `0x55e98` | `ASM_MAC_PIA_TO_CLK::process_end_of_phase` | MAC_PIA_TO_CLK writer (ledger M-009) | lifters/cycloneiv_clean/mac.py |
| libcomp_asmmac | `0x579e0` | `ASM_MAC_CLK_INVERT::process_end_of_phase` | MAC_CLK_INVERT writer (ledger M-009) | lifters/cycloneiv_clean/mac.py |
| libcomp_asmmac | `0x5e232` | `ASM_MAC_MODEL::process_atom_mac_mult` | MAC model process_atom_mac_mult: computes MAC location and mode only; adds no bit tables | - |
| libcomp_asmmac | `0x5e42e` | `ASM_MAC_MODEL::process_atom_mac_out` | MAC model process_atom_mac_out: computes MAC location and mode only | - |
| libcomp_asmmac | `0x4e0d6` | `ASM_MAC_ROW_DATA_INPUT::process_end_of_phase` | MAC_ROW_DATA_INPUT: writes only the RE index of a LAB-line source (RE type 0xbf); does NOT choose the data reg | - |
| libcomp_asmmac | `0x4e264` | `ASM_MAC_ROW_DATA_INVERT::process_end_of_phase` | MAC_ROW_DATA_INVERT writer | - |
| libdb_cdb_atom_ygr | `0x16dfe0` | `CDB_ATOM_YGR_EC::set_ram_mode` | CDB_ATOM_YGR_EC::set_ram_mode: sets RAM flag bits (CDB_RAM_FLAG_ENUM) on the atom | - |
| libdb_cdb_atom_ygr | `0x16e180` | `CDB_ATOM_YGR_EC::clear_ram_mode` | CDB_ATOM_YGR_EC::clear_ram_mode: clears RAM flag bits on the atom | - |
| libdb_cut | `0x2fb590` | `CUT_ATOM_LE::create_util` | CUT_ATOM_LE::create_util: LE util factory (family 0x30 -> CUT_ATOM_CUDA_LE) (ledger D-002) | - |
| libdb_cut | `0x2fc120` | `CUT_ATOM_CUDA_LE::get_assembler_lutmask` | CUDA LE get_assembler_lutmask: four invert_input + complement, no pin permutation (ledger D-002, errata E-T3) | - |
| libddb_dev | `0x15afa0` | `DEV_ELEMENT_DESC::operator<<` | DEV_ELEMENT_DESC serializer | - |
| libddb_dev | `0x168f60` | `DEV_ELEMENT_DESC_BODY::operator<<` | DEV_ELEMENT_DESC_BODY serializer: 49 bools, 11 strings, 36 2D int tables (counts equal the astr DEV_ELEMENT_DE | - |
| libddb_dev | `0x165170` | `DEV_PAD_BODY::operator<<` | DEV_PAD_BODY serializer | lifters/cycloneiv_clean/pkgpad.py |
| libddb_dev | `0x84810` | `DEV_ELEMENT_DESC_BODY::get_2d_int_data` | DEV_ELEMENT_DESC_BODY::get_2d_int_data: slot lookup, key below 0x24 | - |
| libddb_dev | `0x80940` | `DEV_ELEMENT_DESC::get_2d_int_data` | DEV_ELEMENT_DESC::get_2d_int_data | - |
| libddb_dev | `0x85000` | `DEV_ELEMENT_DESC_BODY::set_2d_int_data_from_string` | DEV_ELEMENT_DESC_BODY::set_2d_int_data_from_string: 2D tables can be set from text | - |
| libddb_dygr | `0x2cfca0` | `DYGR_ROUTE_BLOCK_INTERFACE::operator<<` | DYGR_ROUTE_BLOCK_INTERFACE serializer: 28 interfaces then 983 nodes (ledger B-005/B-013) | lifters/cycloneiv_clean/blockiface.py |
| libddb_dygr | `0x2c7190` | `DYGR_ROUTE_BLOCK_INTERFACE_NODE::operator<<` | DYGR_ROUTE_BLOCK_INTERFACE_NODE serializer (element, index, alias, connections) (ledger B-005) | lifters/cycloneiv_clean/blockiface.py |
| libddb_dygr | `0x2c6fd0` | `DYGR_ROUTE_BLOCK_INTERFACE_CONNECTION::operator<<` | DYGR_ROUTE_BLOCK_INTERFACE_CONNECTION serializer (ledger B-009) | - |
| libpgm_pgmio | `0x3b6540` | `PGMIO_BITFIELD::set_auto_usercode` | Auto USERCODE: calls compute_checksum; rbf header lane 0 bits 8 | - |
| libpgm_pgmio | `0x3b6240` | `PGMIO_BITFIELD::compute_checksum` | Byte-sum checksum of the bitfield (CRAM + CFF bytes) (ledger K-002) | - |
| libpgm_pgmio | `0x43be30` | `PGMIO_F2P::reverse_address_counter_frames` | rbf side: per-device table (0x1c-byte records, u16 count; start = u16@0 + u16@0xe, length = u16@0x10, 0 skippe | - |
| libpgm_pgmio | `0x42cf60` | `PGMIO_F2P::get_pgmio_f2p_flip_bits` | SEU-simulation flip-bit option list (not part of normal bit layout) | - |
| libpgm_pgmio | `0x425a90` | `PGMIO_F2P::flip_frame_bits` | SEU bit flipping | - |
| libpgm_pgmio | `0x425ba0` | `PGMIO_F2P::get_flipped_bits_list` | SEU flipped-bit list | - |
| libpgm_pgmio | `0x3b47f0` | `PGMIO_BITFIELD::write_bitstream_by_location` | Plain LSB-first bit-range copy (offset,count), no mapping; 3 callers, all in write_zb_icb_data_for_sof (ICB op | - |
| libpgm_pgmio | `0x496240` | `PGMIO_POFIO::write_pof` | POF writer (decompiles to a stub; callees marked non-returning, read by disassembly) | - |
| libpgm_pgmio | `0x4a0f00` | `PGMIO_ASSEMBLER_SCRIBE::write_all_files` | Programming-file writer entry (overload 1 of 2, other 0x5a4ac0); decompiles to a stub | - |
| libpgm_pgmio | `0x4a4ac0` | `PGMIO_ASSEMBLER_SCRIBE::write_all_files` | Programming-file writer entry (overload 2 of 2); decompiles to a stub | - |
| libpgm_pgmio | `0x5e5040` | `PGMIO_POF2_IO::write_sof_data` | sof data writer: checksum + memmove only, no per-bit/per-frame loop (sof CRAM payload = bitfield bytes) | - |
| libpgm_pgmio | `0x43acd0` | `PGMIO_F2P::make_ygr1es_cff_frame` | Frame maker for a different family (ygr1es CFF frame); not analysed for Cyclone IV | - |
| libpgm_pgmio | `0x3b1650` | `PGMIO_BITFIELD::get_base_address` | PGMIO_BITFIELD::get_base_address (overload 1 of 2, other 0x3b1670): plain getter of the array start, 0 when un | - |
| libpgm_pgmio | `0x3b1670` | `PGMIO_BITFIELD::get_base_address` | PGMIO_BITFIELD::get_base_address (overload 2 of 2) | - |
| libpgm_npcf | `0x29428` | `NPCF_MANAGER::convert_sof_frame_to_bs_frame` | sof frame -> bs frame index conversion (data-driven; frame/lane/padding come from data files) | - |
| libpgm_npcf | `0x29362` | `NPCF_MANAGER::convert_bs_frame_to_sof_frame` | bs frame -> sof frame index conversion | - |
| libpgm_npcf | `0x28c08` | `NPCF_MANAGER::get_quartus_cram_map_path` | Locates the family CRAM map CSV for (family, RBA cram type) | - |
| libpgm_npcf | `0x18e76` | `NPCF_DATA_SERVER::get_device_fid` | NPCF device fid loader (data file, not compiled-in) | - |
| libpgm_npcf | `0x1c56c` | `NPCF_DATA_SERVER::get_device_rba` | NPCF device rba loader (data file) | - |
| libpgm_npcf | `0x193c6` | `NPCF_DATA_SERVER::get_family_cram_map` | NPCF family cram map loader (data file) | - |
| libpgm_fbgen | `0x128d00` | `FBGEN_SBLOCK::write_option_bits` | FBGEN option-bit writer (newer-family frame builder; Cyclone IV applicability unchecked) | - |
| libpgm_fbgen | `0x129460` | `FBGEN_SBLOCK::calculate_and_write_crc` | FBGEN CRC calculation + write | - |
| libpgm_common | `0x3134c` | `PGM_COMMON::convert_dat_to_rbf` | PGM_COMMON::convert_dat_to_rbf helper | - |
| libpgm_common | `0x19934` | `PGM_COMMON::calculate_crc16` | PGM_COMMON::calculate_crc16 (candidate for sof/rbf CRC16 rule L-004; not compared) | - |
| libpgm_pof | `0xad22b` | `pof_create_floorplan2sof` | pof_create_floorplan2sof: POF/SOF protobuf container (newer families), not the Cyclone IV bit layout | - |
| libatm_astr | `0xd87034` | `astr_get_debug_string` | astr_get_debug_string: enum value -> debug name (CDB_RAM_FLAG_ENUM table at 0x185b800) | lifters/cycloneiv_clean/m9k.py |

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
