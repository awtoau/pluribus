# Cyclone IV GX (EP4CGX150) hard blocks: PLL, M9K, MAC (#169)

Code: `lifters/cycloneiv_clean/{pll,m9k,mac}.py`. Tests: `tests/cycloneiv_clean/test_{pll,m9k,mac}.py`.
Scripts: `scripts/cycloneiv_clean_hardblocks_build.py` (specimen builds), `scripts/cycloneiv_clean_hardblocks_score.py` (scores). Logs: `tmp/logs/cycloneiv_clean_hardblocks_{build,score}.log`.
Measured 2026-10-30, Quartus 25.1, EP4CGX150DF31C7. Ground truth = Quartus post-fit netlist (`postfit.vo`) of each specimen.
Counts are matched / missing / extra / wrong; ambiguous = missing.

## Method

- Vendor code first: `ASM_PLL_*::process_atom` decompiled (libcomp_asm); rows in `reference/ghidra/functions.tsv`.
- Pair builds only confirm: one feature per pair, tiny designs, fit + asm only, 12 jobs max.
- No fitted constants: addresses are vendor group offsets; placement tables are measured by specimens and cited per entry.

## PLL

- Config lives in CFF (periphery frames), not CRAM. Pair diffs of altpll builds change periphery frames 1..4 and the header CRC only; CRAM diff = 0 for 17 of 21 pairs (the 4 others re-route: c1, c1m3, no_comp, null_seed).
- Block types 43 FAST_PLL (74 groups) and 45 GENERAL_PLL (73 groups): every group carries CFF-tagged absolute addresses. Group path k = PLL index k (6 paths in 43, 2 in 45). No instance base needed.
- Field value = mux bits LSB first.
- PLL_k to (block type, path), measured by `PLL_ENABLE_PLL` bit under `set_location_assignment PLL_k`:

| PLL | (type, path) | builds |
|---|---|---|
| PLL_1 | (43, 0) | gxhb_pllsite_1 |
| PLL_2 | (43, 5) | gxhb_pllsite_2 |
| PLL_3 | (45, 0) | gxhb_pllsite_3 |
| PLL_4 | (45, 1) | gxhb_pllsite_4 |
| PLL_5 | (43, 1) | gxhb_pllsite_5 |
| PLL_8 | (43, 4) | gxhb_pllsite_8 |
| PLL_6, PLL_7 | not placeable in this package (fit fails); paths (43, 2), (43, 3) unassigned | missing |

- Encodings (code + netlist agree):
  - M and N: high = (count + 1) >> 1, low = count >> 1; count = high + low. Mult-factor group: even 0 / odd 2 (M); N observed 1 (n = 1) and 2 (n = 7).
  - Output counter c0..c4 (group gi): high / low = netlist c#_high / c#_low, PRESET = c#_initial (phase shift lands here), MULT_FACTOR 0 even / 2 odd. Unused counter reads 15 / 15 / mult factor 3.
  - CHARGE_PUMP_CURRENT = charge_pump_current_bits. USAGE_MODE 4 for NO_COMPENSATION (1 of 1), 0 otherwise.
  - LOOP_FILTER_R / C: read, not an altpll parameter (depends on M, N, bandwidth); no ground truth, not scored.
- Score `pll.py` vs netlist (m, n, charge pump, c0..c4 mode / high / low / initial, 8 params per build): 28 builds, 224 matched / 0 missing / 0 extra / 0 wrong.
- Not decoded (missing): clock switchover, PFD / scan / areset input muxes, lock-detect and VCO range fields, loop filter value table, bandwidth preset mapping, `ZERO_DELAY_BUFFER` and `LVDS` modes (fail in `quartus_map`).
- Residual diffs of the pair builds: CFF bits outside any PLL group (fitter clock routing in the periphery, 16 K range) change with the seed; not PLL config.

## M9K

- Instance: `m9k.instance(x, y)` = column rank * 90 + (Y - 1); 8 columns from the fitter geometry file.
- Content: `RAM_CONTENT_YGR_MEAB` (one 9,216-bit mux per instance, 720 instances = 6,635,520 bits). Mux position p holds mem_init bit `(p mod 256) * 36 + p div 256`.
- Logical (word, bit) to mem_init index per port width (parity cells are holes): widths 1/2/4/8 `lg + lg // 8`; 9 and 18 identity; 16 `word * 18 + bit`; 32 and 36 two lanes of 18 (`4608` apart; the 32-bit lane A uses bits 0..13). Measured by `gxm9k_hb{W}_k0..13` (bincode over every logical bit), 9 widths.
- Score `score_m9k_content`: 9 bincode builds (every position of every width) plus 123 random-fill builds across the M9K columns and rows (width 1, 9, 16); 132 specimens, 1,210,368 position checks, 1,210,368 matched / 0 missing / 0 extra / 0 wrong.
- WYSIWYG `mem_init` index c = word * W + bit (not the physical index); the `index` layouts above apply to it.
- Mode / control bits (cross-site: signature from the pair at X23_Y40, scored at X65_Y40 and X7_Y60; 15 features x 2 sites = 30 pair-sites): 47 matched / 4 missing / 12 extra / 1 wrong.
  - Stable across sites: output register A/B (`RAM_REG_DATA_OUT[_B]`, `RAM_SELECT_CLK_DATA_OUT[_B]`, `RAM_CE_SELECT_OUTPUT`), read-during-write old data (`RAM_NEW_DATA_MODE`), clock-enable none / ena0 (`RAM_CE_SELECT_{INPUT,CORE,OUTPUT}`), aclr (`RAM_USE_CLR_DATA_OUT`, `RAM_USE_CLR_READ_ADDRESS`), write clock.
  - Operation modes: simple dual port clears `RAM_USE_TRUE_DUAL_PORT_MODE` (set in single-port altsyncram builds) and sets `RAM_DATA_WRITE_MODE_B`; bidir sets `RAM_NEW_DATA_MODE_B`; widths 32 / 36 set `RAM_USE_PACKED_MODE`. Single-site observations (altsyncram pairs, X23_Y40 only), not cross-site scored.
  - Width and depth: no mode group changes between widths 1..18; the width is set by which data / address ports are wired (port-input muxes) plus packed mode at 32 / 36.
- `byteena`: 1 wrong, 1 missing across sites (fitter-routed byte-enable input differs); not decoded.
- Port-input muxes (`RAM_MS_*`, `RAM_PIA_TO_INPUT_YGR`): selection depends on the net; not isolated by a single-feature pair (missing).
- ECC: none on Cyclone IV (no group). FIFO: soft logic, no M9K mode.
- `ASM_EAB_BLOCK_PORTS::write_block` writes dirt port lists (routing), not mode bits; the mode groups are set through generic arch-group selection.

## MAC

- Instance: `mac.instance(x, y)` = column rank * 90 + (Y - 1); 4 MUL columns.
- Pair builds at two MAC sites (X103_Y87, X43_Y87), 12 features: 32 matched / 3 missing / 2 extra / 0 wrong.
  - Clean one-cell signatures (both columns): `MAC_SIGN_INVERT` gi 0 = signa, gi 1 = signb (unsigned = bit set, signed = cleared); dynamic sign ports set `MAC_PIA_TO_SIGN` gi 0 / 1; 9-bit width sets `MAC_USE_NINE_BIT_DATA_WIDTH_PER_ROW`.
  - Input / multiplier register: all three give the same signature (`MAC_CLK_FAST_MUX`, `MAC_PIA_TO_CLK`): the clock connection is decoded, which register is enabled is not (missing).
  - Output register: `MAC_CLK_FAST_MUX` + `MAC_ROW_OREG_UPPER_DATA`; the second column placed at another instance in the pinned build, so cross-column score is 0 / 3 / 2 / 0.
- Not decoded (missing): operation mode beyond signed / 9-bit (accumulator, chain, shift, rotate, saturation, rounding), coefficient data, row data input muxes. 210,960 CRAM bits claimed by group, 1 mode field isolated per pair.
- Dedicated build for the 36x36 / 9x18 / two-multiplier modes exists (`gxhb_mac_w36`, `gxhb_mac_w9x18`, `gxhb_mac_two_mult_w9`) but landed on different instances than any base; not scored.

## DPRIO / GX / HSSI / other

- No BLOCK_INFO instance list for GX_* / HSSI_* / OCT_CAL / CONTROL / DEVICE blocks (docs/cycloneiv-clean-fields.md). Their group offsets have a CFF or CRAM tag per address; CFF-tagged ones are absolute (same property as PLL) but were not specimen-tested here: documented unknown.
- DPRIO has no address space of its own (aliases CFF, docs/cycloneiv-address-spaces.md).

## Third-party image (counts only, `scripts/cycloneiv_clean_image.py`)

| Item | Count |
|---|---|
| PLLs enabled (CFF) | 2 (PLL_2, PLL_8); 0 enabled paths outside the placeable table |
| PLL_2 | M 14, N 1, c0 high / low 50 / 50, other counters bypass |
| PLL_8 | M 20, N 1, c0 4 / 4, c3 8 / 8, other counters bypass |
| M9K instances with content bits set | 8 of 720 (12,993 of 6,635,520 content bits set); content address map: 0 unmapped |
| M9K instances with `RAM_USE_TRUE_DUAL_PORT_MODE` set / `RAM_REG_DATA_OUT` set | 364 / 454 |
| MAC instances with any set control bit | 87 of 360; mode decode = MISSING (542 M9K tiles carry output edges, 0 MAC edges) |

- Port width of an image M9K is not in the config bits (set by wired ports), so content is mapped to mem_init order only; logical (word, bit) needs the width from routing.

## Code-derived M9K writer rules (libcomp_asmram, #169)

- Select rule: `ASMDB_SIMPLE_MUX::select@0x8c4ac`: mux_select(value) writes every mux bit, bit i = (i == value) (one-hot). `silent_set_bits@0x1a240` stores the written bit as is. On a 1-bit mux the one-hot rule makes the stored bit `(0 == value)`: value 1 clears it, value 0 sets it. That is the whole 'inversion' seen on REG_DATA_OUT and NEW_DATA_MODE: flag bit 9 is `RAM_REG_DATA_OUT` (output registered; flag names `m9k.RAM_FLAGS`, index = bit) and a registered output writes value 1, i.e. cell 0.
- Writers decompiled (function@vaddr, table `m9k.WRITERS`): `ASM_RAM_USAGE_MODE@0x1efc6`, `_B@0x1f106`, `ASM_RAM_REG_DATA_OUT@0x7de60`, `ASM_RAM_NEW_DATA_MODE@0x1f6fe`, `ASM_RAM_IS_ROM_ONLY@0x1fa72`, `ASM_RAM_WRITE_OPTION@0x1fd68`, `ASM_RAM_MS_DATA_INPUT@0x6663e` (port input mux value = RE line index of the port source).
- Check (`score_m9k_code_rules`): REG_DATA_OUT and NEW_DATA_MODE expected from the build parameter via the rule, 51 builds, 102 matched / 0 missing / 0 extra / 0 wrong.
- Not yet code-derived (still pair-derived, missing as code): port-input mux value tables (flags word fields come from `ASM_RAM_MODEL_YGR_MEAB`), byte enables, clock / clear / CE selects, packed mode; MAC (`ASM_MAC_*::process_end_of_phase`, `ASM_MAC_MODEL::process_atom_mac_mult@0x5e232`, `_mac_out@0x5e42e`) and PLL leftovers (libcomp_asmpll) are decompiled-to-do.

## Code-derived MAC writer rules (libcomp_asmmac, #169)

- Table `mac.WRITERS` (function@vaddr). Register flags per signal: flag byte bit 3 = input register (IREG_*), bit 4 = pipeline / multiplier register (PREG_*), bit 5 = output register (OREG_*); IREG / PREG / OREG groups exist for SIGN, SMODE, SATAC, SATRS, SHFTR.
- `MAC_ROW_DATA_INPUT` is a routing mux: `ASM_MAC_ROW_DATA_INPUT::process_end_of_phase@0x4e0d6` writes the RE index of the row-data source when the source RE type is 0xbf (LAB line); the other source types (0x6ef, 0x7d8/0x7d9, 0x804) write nothing from this group. So the `in_a_reg` / `in_b_reg` / `mult_reg` pair diffs in that group are fitter re-routing, not the register choice. Which group encodes the data-register choice: open (missing); the per-signal I/P/O register flags above cover sign / smode / saturate / shift only.
- Port-flag word builders for M9K: `CUT_RAM_UTIL::get_ram_mode` is in libdb_cut (not yet in the Ghidra project; import requested); `ASM_SINGLE_RAM_MODEL_YGR_MEAB::cache_ram_mode@0x4a624` copies those flag vectors (bit 14..18, 24..27 masks) into the per-port model.

## PLL leftovers (code reading, #169)

- `libcomp_asmpll` is the 28 nm (Arria V / Cyclone V) PLL set; the Cyclone IV GX writers are `ASM_PLL_*` / `ASM_SINGLE_PLL_MODEL_STINGRAY` in libcomp_asm.
- Loop filter R / C, charge pump and VCO post-scale are now decoded and scored. Netlist `loop_filter_r_bits`, `loop_filter_c_bits`, `charge_pump_current_bits`, `vco_post_scale` equal the CFF field values (`PLL_LOOP_FILTER_R`, `_C`, `PLL_CHARGE_PUMP_CURRENT`; `PLL_VCO_DIVIDE_BY_2` stores NOT(post_scale == 2) by the one-hot rule). PLL score: 28 builds, 308 matched / 0 missing / 0 extra / 0 wrong.
- Physical values: vendor text tables `ddb_stingray_basic.pll` (`pll.basic_tables`: field value -> current / resistor / capacitor, e.g. R field 27 = 4000 ohm, 8 = 14000, 24 = 6000; CP field 1 = 20, 3 = 40) and the bandwidth settings table `ddb_stingray_bandwidth_gpll.pll` (`pll.bandwidth_rows`: 10 rows, M * post-scale range -> ICP / R / C field values). Low / medium bandwidth use the GPLL table (ICP 1); high bandwidth takes the ICP 3 rows of `ddb_stingray_bandwidth_mpll.pll` (same R / C, input-frequency range column differs). `pll.bandwidth_settings(m, post, bandwidth)` reproduces ICP / R / C of 28 of 28 builds.
- The earlier statement that these values are an index into a device-DB element table (`get_cp_and_lp_value@0x1b1e2a`) stands for the code path, but the data is also available as the text tables above; the element-descriptor decoder is not needed for them.
- Switchover, scan, lock detect, areset / pfdena input muxes: groups present (`PLL_CLOCK_SWITCH_*`, `PLL_SCAN_*`, `PLL_LOCK_*`, 16-bit input muxes whose value is an RE index like the M9K input muxes); writers not yet decompiled: missing.

## PLL element descriptor (decoder status, #169)

- `DEV_ELEMENT_DESC_BODY::operator<<@0x168f60` field order: bool vector (49 bits), 15 ints (i32 deltas), 11 strings, 36 x `vector<vector<int>>` (`m_2d_int_data`, key = `DEV_ELEMENT_DESC_2D_INT_DATA_ENUM` < 0x24; `get_2d_int_data@0x84810` returns slot `key`), `m_locations` (ptr vector), `m_location_enums` (i32 deltas), ports (ptr vector), one int, then four enum-valid bool vectors (49, 30, 11, 36 bits). Tables can also be set from text (`set_2d_int_data_from_string@0x85000`).
- Not decoded: the element objects in `ddb_stingray4_hdr.ddb` (xz payload, 108,689 bytes). A direct parse of the field order above from the 49-bit bool-vector marker found 2 objects that parse and neither carries 2D data; the object-stream start / ptr-tag framing (DEV_BASIC_INFO root) is not yet located. Loop-filter / charge-pump / bandwidth tables remain missing.

## Plain-text / data files of the Quartus install for Cyclone IV GX (sweep, #169)

| file (quartus/common/devinfo/cycloneivgx unless noted) | holds | used |
|---|---|---|
| `ddb_stingray_basic.pll` | PLL structure limits; field value -> physical tables (charge pump, loop-filter R / C); counter limits; reconfig scan-chain order; lock-window / lock defaults | yes (`pll.basic_tables`) |
| `ddb_stingray_bandwidth_{gpll,mpll}.pll` | M * post-scale range -> ICP / R / C field values (ICP 1 and 3) | yes (`pll.bandwidth_settings`) |
| `ddb_stingray{1..4}[_v1,_v2].pll`, `ddb_stingray.pll` (include list) | per part / speed grade PLL timing limits (vco, pfd, input / output min / max) | no (timing only) |
| `ddb_stingray_*.dxf` (ram, dsp, pll, io, io_group, lab, le, clkbuf, quad*) and `ddb_yeager_*.dxf`, `ddb_arm_meab.dxf` | CAD drawings of block structure: layers, port names, lines (PORTS / SIMPLE layers); geometry and connectivity only, no bit mappings found | no |
| `ddb_stingray.ref` | die grid (nx, ny) and per-site type map (EP4CGX15 header) | no |
| `ddb_stingray*_timing.ddb`, `_mv_*.ddb` | timing models | no |
| `quartus/eda/ibis/cycloneivgx_ibis_*.xml`, `cycloneivgx_package_rlc.xml` | IBIS electrical models per IO standard / drive / slew (names, not bit values) | no |
| `quartus/eda/hspice/cycloneivgx_hspo.hsd` | HSPICE option set | no |
- No plain-text table for M9K modes, MAC modes or IO drive / slew bit values exists in the install: the field encodings for those come from code (writers) and the asmdb groups. The PLL switchover, scan and lock-detect muxes are RE-index routing muxes (same writer pattern as the M9K input muxes), not tables.

## Mux select semantics from code (`asmdb_select.py`, #169)

- `ASMDB_*_MUX::select` (libdb_asmdb): SIMPLE@0x8c4ac one-hot; ENCODED@0x8c0ba bit k = (value >> k) & 1; MAPPED_SIMPLE@0x8c5b8 / MAPPED_ENCODED@0x8c19a look the value up in the group's map mux first (a SIMPLE mux whose bit list is the table), then select; DECISION@0x8c36e writes the lower / upper half with its two settings; RAM_MUX@0x86bc4 encoded with a polarity mux. Classes 20 (heterogeneous), 21 (bank), 22 (RAM), 24 (STL mapped) not implemented.
- This replaces the 'one-hot on a 1-bit mux' reading for REG_DATA_OUT: that group is MAPPED_ENCODED with map [1, 0] (value 0 -> 1, value 1 -> 0), so value 1 stores 0 (matches 102 of 102 checks). E-P3 stands as 'no die-flag inversion'; the cause is the group's value map, not one-hot.
- `RAM_USAGE_MODE` (MAPPED_ENCODED, 17 bits, map [0x1ff81, 0x1ff81, 0x1ff81, DUMMY, DUMMY]): usage 0 (ROM), 1 (single port), 2 (dual / bidir) all write 0x1ff81; usage 3, 4 illegal. This is why ROM, single, dual and bidir builds read the same 17 bits (`10000001111111111`); the mode is carried by other groups (`RAM_USE_TRUE_DUAL_PORT_MODE`, `RAM_USE_PACKED_MODE`, `RAM_DATA_WRITE_MODE`, ...). The bit-55 question is closed: no distinction exists in this group.
- `RAM_DATA_WRITE_MODE`: MAPPED_SIMPLE, 6 bits, map [0, 1, 2, 3, 4, 3, 4, 5, 5] (writer values 0..3 from `ASM_RAM_WRITE_OPTION`).

## M9K mode groups from writer rules (#169)

- `RAM_USE_TRUE_DUAL_PORT_MODE` (`ASM_RAM_USE_TRUE_DUAL_PORT_MODE`): value 1 if `RAM_BIDIR_DUAL_PORT`, else `RAM_PACKED`; forced to 1 when `RAM_READ_ONLY` or `RAM_SINGLE_PORT` is set and `RAM_SINGLE_PORT_IMPLEMENTED_IN_SIMPLE_DUAL_PORT` (flag 55) is clear. So ROM, single port and bidir read 1 and simple dual port reads 0; this is the only mode distinction in the CRAM and flag 55 is what separates a single port implemented as simple dual.
- `RAM_USE_PACKED_MODE` (`ASM_RAM_USE_PACKED_MODE`): `RAM_PACKED` (flag 32), set by widths 32 and 36.
- Score `score_m9k_modes` (4 altsyncram mode builds + 9 width builds, both groups): 26 matched / 0 missing / 0 extra / 0 wrong. Flag sets per build are the Quartus ram mode of the atom (names `m9k.RAM_FLAGS`); the family / model condition in the first writer is assumed true.
