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

- Select rule: `ASMDB_SIMPLE_MUX::select@0x8c4ac`: mux_select(value) writes every mux bit, bit i = (i == value) (one-hot). `silent_set_bits@0x1a240` stores the written bit as is (no inversion in the CRAM branch). The observed cell = NOT(registered) for REG_DATA_OUT therefore means the writer's flag bit 9 is set for an UNREGISTERED output; flag-word meaning comes from the port-flag builders (`ASM_SINGLE_RAM_MODEL_BASE`, not yet decompiled).
- Writers decompiled (function@vaddr, table `m9k.WRITERS`): `ASM_RAM_USAGE_MODE@0x1efc6`, `_B@0x1f106`, `ASM_RAM_REG_DATA_OUT@0x7de60`, `ASM_RAM_NEW_DATA_MODE@0x1f6fe`, `ASM_RAM_IS_ROM_ONLY@0x1fa72`, `ASM_RAM_WRITE_OPTION@0x1fd68`, `ASM_RAM_MS_DATA_INPUT@0x6663e` (port input mux value = RE line index of the port source).
- Check (`score_m9k_code_rules`): REG_DATA_OUT and NEW_DATA_MODE expected from the build parameter via the rule, 51 builds, 102 matched / 0 missing / 0 extra / 0 wrong.
- Not yet code-derived (still pair-derived, missing as code): port-input mux value tables (flags word fields come from `ASM_RAM_MODEL_YGR_MEAB`), byte enables, clock / clear / CE selects, packed mode; MAC (`ASM_MAC_*::process_end_of_phase`, `ASM_MAC_MODEL::process_atom_mac_mult@0x5e232`, `_mac_out@0x5e42e`) and PLL leftovers (libcomp_asmpll) are decompiled-to-do.

## Code-derived MAC writer rules (libcomp_asmmac, #169)

- Table `mac.WRITERS` (function@vaddr). Register flags per signal: flag byte bit 3 = input register (IREG_*), bit 4 = pipeline / multiplier register (PREG_*), bit 5 = output register (OREG_*); IREG / PREG / OREG groups exist for SIGN, SMODE, SATAC, SATRS, SHFTR.
- Data input / multiplier register selection for dataa / datab is therefore not a clock-fast-mux bit: the `in_a_reg`, `in_b_reg`, `mult_reg` pairs differ in `MAC_ROW_DATA_INPUT` (36 rows x 2 paths, excluded from the control signatures as routing); that group carries the register choice per data bit. Value table for it: not yet derived (missing).
- Port-flag word builders for M9K: `CUT_RAM_UTIL::get_ram_mode` is in libdb_cut (not yet in the Ghidra project; import requested); `ASM_SINGLE_RAM_MODEL_YGR_MEAB::cache_ram_mode@0x4a624` copies those flag vectors (bit 14..18, 24..27 masks) into the per-port model.

## PLL leftovers (code reading, #169)

- `libcomp_asmpll` is the 28 nm (Arria V / Cyclone V) PLL set; the Cyclone IV GX writers are `ASM_PLL_*` / `ASM_SINGLE_PLL_MODEL_STINGRAY` in libcomp_asm.
- Loop filter R, loop filter C and charge pump are INDICES into a device-DB 2D integer table: `ASM_SINGLE_PLL_MODEL_STINGRAY::get_cp_and_lp_value@0x1b1e2a` fetches `DEV_ELEMENT_DESC::get_2d_int_data(pll element 0x32, enum)`, picks row 0 or 1 by the bool argument, and returns the position of the input parameter in that row (error "Illegal PLL paramiter Found" if absent). The table lives in the main device ddb (element descriptor); that ddb record is not decoded, so loop-filter / bandwidth tables remain missing. Observed (28 builds): R 27 for the default VCO, 8 and 24 for two others; not scored.
- Switchover, scan, lock detect, areset / pfdena input muxes: groups present (`PLL_CLOCK_SWITCH_*`, `PLL_SCAN_*`, `PLL_LOCK_*`, 16-bit input muxes whose value is an RE index like the M9K input muxes); writers not yet decompiled: missing.
