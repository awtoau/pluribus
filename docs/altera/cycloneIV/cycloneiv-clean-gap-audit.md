# Cyclone IV GX (EP4CGX150, DJI m2001) decode gap audit (2026-10-31)

Documentation/audit only — no new decode work. Compiled from `docs/lightbridge-fpga.md`, `docs/altera/cycloneIV/cycloneiv-clean-*.md`, `docs/altera/cycloneIV/cycloneiv-manual-review.md`, `docs/altera/cycloneIV/cycloneiv-address-spaces.md`, `docs/reversing-errata.md`, `reference/rules.tsv` (159 rows), `tmp/dji_microcode/build/build.json` (machine-measured image counts), and issues #165/#169/#176/#177/#178 (bodies + comments).
Severity key: **A** = blocks the DJI image's own correctness (a real signal/mode in this image is wrong or unmodelled), **B** = blocks general-device / die-generic claims only (image doesn't exercise it, or it's a corpus/gate gap not an image gap), **C** = cosmetic / bookkeeping.
Tracking key: issue / doc / ledger id, or **UNTRACKED** (flagged in the final section).

## 0. Cross-check against docs/lightbridge-fpga.md

- Its section 10 and section 12 "Open" list calls PLL input clock source and PLL clock plan open. **Corrected (#181 point 2): this was never a stale counter — it was two unmerged analyses.** `docs/altera/cycloneIV/cycloneiv-clean-pll-clocks.md` + ledger P-011/P-014/P-015 + errata E-U6/E-U7 resolved the routing trace 2026-10-30/31 (CFF-space routing bits, not CRAM; image PLL_2/PLL_8 index 0 both trace to ball B14 via tile X57Y91 and element 666), but that trace lived only in the standalone script `cycloneiv_clean_image_pll_pads.py` — `emit.py`'s own `_hard` method had a separate, unconditional `nl.und["PLL: input clock source"] += len(nl.pll)` (citing #175) that never called the trace and so never saw the result. `tmp/dji_microcode/build/build.json`'s "PLL: input clock source": 2 was not a counter that needed "re-running" against existing results; it was counting correctly for code that never looked. Fixed by integrating the trace (now `pll.clkin_source`, shared by both call sites) into `emit.Builder._hard`: the netlist's own undecoded count for this cause drops to 0 on this image.
- Its AF3 section (8, 11a) matches `docs/altera/cycloneIV/cycloneiv-clean-af3-engine.md` exactly (same open items: per-op split, CRC-8/16, engine clock, T367/T369).
- Its M9K summary ("8 of 542 hold data... no packed/mixed width/byte enables") is consistent with `cycloneiv-clean-hardblocks.md`/`m9k.md` image counts, but does not mention the specific undecoded-in-use items (output-register CE select 14 tiles, output clear 101 tiles) — those are only in `cycloneiv-clean-m9k.md` line 190 and `build.json`'s absence (build.json has no M9K-control undecoded counters at all, a gap in the counter itself, see §5).
- Its "Open" section (12) omits the IO standard/termination ambiguity (75/44 instances) entirely — this is the single largest undecoded-item count in the whole image and isn't mentioned in the running summary at all.

## 1. Fabric routing (pips / nets)

| Item | Count | Source | Severity |
|---|---|---|---|
| Fast-tier gate (134 designs, run 45/46 per lightbridge; 117 designs per most recent hardblocks run): pips 656,759/2 missing (or 650,510/2 in the hardblocks-doc run) | 2 missing pips, both `IO_RAW_DATAIN -> PLL_CLKIN` | `docs/lightbridge-fpga.md` §2; `docs/altera/cycloneIV/cycloneiv-clean-pll-clocks.md` "Open"; issue #176 | B (PLL_2/PLL_8 "value 00, no literal" case — a rule gap, not image-specific; P-014 marks it SPECIMEN_ONLY, not yet CODE-confirmed) — tracked P-011/P-014, #176 |
| register_clock missing | 3 (lightbridge headline) vs 0 in the most-current `ffctl.md`/rules R-006 (16,938/0/0/0 fast, 50,514/0/0/0 full) | `docs/lightbridge-fpga.md` §2 vs `reference/rules.tsv` R-006 | C — **stale headline figure**, not re-synced into lightbridge-fpga.md; superseded by R-005/R-006 fixes. UNTRACKED staleness (§15) |
| Full-tier gate: 193 missing pips / 51 missing nets (#177 item 2) | 193 / 51 | issue #177 | B — not yet root-caused; fast tier is clean so this is corpus-wide, not image-specific |
| Image fan-in conflicts / undriven nodes / loops | "rerun pending" (3 of 4 sanity checks in `cycloneiv-clean-image.md` marked rerun pending under the vendor tracer rule, after the E-L2 fix) | `docs/altera/cycloneIV/cycloneiv-clean-image.md` "Sanity statistics" | C — stale image run predates the T-001/E-L2 tracer fix; needs a rerun to get current image routing-fault numbers. UNTRACKED (§15) |
| Image "4.2% fan-in conflicts" cited elsewhere | superseded (errata E-L2): old rule gave 3.7–4.2%, new tracer gives 0/64,375 on rb_000..009 controls; **image-specific rerun pending** | errata E-L2 | B |

## 2. LUT contents (LUT INIT)

- LAB LUT INIT (`LE_LUT_FUNCTION`): 2,396,160 CRAM bits, **fully claimed and oracle-validated**: 1,023/1,023 specimen sites (16,368 cells), 0 missing/extra/wrong. Fast-tier gate `lut_init` 0 missing in every cited run. — No gap. (`docs/altera/cycloneIV/cycloneiv-clean-fields.md` coverage table; ledger D-001/D-002.)
- Image: 89,280 of 149,760 LEs non-zero INIT (59.6%); 19 all-ones. No gap in the decode of this; the count itself is just the design's fill rate. (`docs/altera/cycloneIV/cycloneiv-clean-image.md`)
- Arithmetic-mode sum/carry mask combination not independently re-derived from code — decompile control flow partly broken (try/catch artefacts). Ledger D-002 notes "not independently re-derived." Severity **B** (gate scores 100% so it's empirically right; the *code-level* derivation is incomplete). Tracked: ledger D-002.

## 3. Register / FF controls

Exact image counts from `tmp/dji_microcode/build/build.json` (`undecoded` dict):

| Item | Count | Tracked |
|---|---|---|
| FF sync-load ASDATA (DATAC) source, undecoded | **0** (was 131; resolved 2026-10-31, F-020, #182 — 9 via register feedback checked before the LE_LUT_INPUT fallback, same as the LUT DATAC pin, F-010; 122 via the same "genuinely unselected mux = tie `1'b1`" vendor convention the LUT pin already used) | Resolved. Tracked: ledger F-020, `docs/altera/cycloneIV/cycloneiv-clean-ffctl.md` "ASDATA gap resolved", #182. |
| input pad with undecoded IO site (direction from routing only) | 1 | UNTRACKED; folded into the IO MISSING-sites fix history (E-R8) but build.json still shows 1 residual. Severity **A** (single pad, minor). |

Other FF-control facts (all CONFIRMED_BY_CODE, no gap):
- clock source, polarity, aclr, sclr, sload, carry-in: ledger F-001..F-019, checked 100% on sampled corpus (ena/aclr/sclr/sload/clock-polarity/ASDATA/carry-in all 0 missing/extra/wrong in both ffctl.md samples).
- 1,779 of 38,772 image `reg_used` claims were dropped as impossible (unconfigured clock mux); 0 dropped in corpus. Resolved (E-S1/E-S7/F-018). Not a gap, a decode fix already applied.
- Register-claim ambiguity (R-003/R-006): "3 missing / 3 extra" residual in one fast-gate sample is an **inherent ambiguity** (LUT on a used buffer + register on the third YGR path is indistinguishable from an unused path) — not fixable by more decoding. Severity **C**, tracked R-005.
- Global-network clock inversion through the clock control block (polarity of clocks from sources *other than* BLK_CLK_BUF lines / LAB_CONTROL_MUX) — **UNKNOWN**, no specimen exists. Ledger **C-003**. Severity **B** for general claims; unclear if the image uses such a source (not checked) — flag for the image specifically, since if the image's 6 clock domains include any non-fabric-sourced clock this would be **A**. UNTRACKED whether the image is affected.
- LE 8 <- LE 15-of-LAB-above ("skip-half-LABs") family flag for Stingray (0x30): not resolved in code (no carry-chain-monitor class registers for family 0x30); only specimen evidence (1,879/1,879 corpus links all use LE8<-LE7). Ledger F-015/F-016, errata E-T2. Severity **B**.

## 4. Carry chains / LAB control muxes

- Cross-LAB carry (LE0 <- LE15 of LAB at Y+1): CONFIRMED_BY_CODE + 3 specimen builds (6/6 links); no cross-LAB carry use anywhere in the 16,297-design corpus or (implicitly) checked against the image. Not a gap.
- LAB_INVERT table: CUDA 9-line table identifies 6 real LAB_INVERT lines (clk0/ce0/clk1/ce1/sload/sclr); lines 6–8 (aclr pair + second sload) are *not* LAB_INVERT lines for this die (aclr polarity lives in `LAB_CLR_INVERT_PAIR` instead) — resolved, not a gap (F-012, errata E-T1).
- LAB non-LUT, non-control residue: **12.0 M CRAM bits** in LAB tiles have no vendor record naming them at all (not even an address). This is the single largest unclaimed region in the whole device. `docs/altera/cycloneIV/cycloneiv-clean-hardblocks-reversing.md` §3/§4. Severity **B** (general-device/completeness; image-specific effect unknown — these bits may be entirely reserved/unused, per the "ever-set" check showing only 126 of 5.89M LAB-tile residue bits are *ever* set across 3,448 designs). Tracked: `docs/altera/cycloneIV/cycloneiv-clean-hardblocks-reversing.md`, part of #169.
- Value-to-bit-pattern maps for most *other* LAB groups beyond register control (LE_LUT_INPUT 6.59M bits, LAB_PIA_TO_INPUT 411,840 bits, LE_USE_CARRY/REGISTER_FEEDBACK/REG_CASCADE_ARM 149,760 bits each): address known, group selection mechanics known generically (asmdb_select classes), but not individually pair-validated beyond the LUT-input/carry/feedback rules already in ffctl.md/emit.md. Severity **C** (emit already consumes these correctly per the 100% pip/net gate scores — this is a "not independently re-verified by specimen" gap, not a functional gap). Tracked: `docs/altera/cycloneIV/cycloneiv-clean-hardblocks-reversing.md` §3.

## 5. M9K (block RAM)

Image-wide, from `docs/altera/cycloneIV/cycloneiv-clean-m9k.md` (2026-10-30 "M9K simple/true dual port" section) and `build.json` (build.json has **no explicit M9K-control undecoded counters** — this is itself a gap, see §15):

| Item | Count | Severity | Tracked |
|---|---|---|---|
| Output-register CE select, undecoded, in use | **14 tiles** | A | UNTRACKED as its own issue; recorded only in `docs/altera/cycloneIV/cycloneiv-clean-m9k.md` line 190. |
| Output clear (aclr), undecoded, in use | **101 tiles** | A | UNTRACKED as its own issue; same line. |
| Read enable | undecoded (no count given) | A/B | UNTRACKED |
| Address stall | undecoded (no count given) | A/B | UNTRACKED |
| Mixed-width ports | **0 tiles** (image uses none) | — | n/a, not a gap for this image |
| Byte enables | **0 tiles in image** (builds that use byte enables: 62 of ~831 gxm9k specimens fail sim — all 16-bit-with-byte-enable families); manual review B4 gives the documented old/new-data output rule as the likely fix | B for general corpus; **not applicable to image** (0 tiles) |
| Read-during-write beyond default (`RAM_NEW_DATA_MODE`) in Don't-Care / two-clock same-address cases | undefined per Cyclone IV handbook (B5) — expected, not a fault | manual-review B5 | C |
| Packed mode (two half-size RAMs/block) | 0 of 8 populated image blocks; specimen-only in general (M-007/B9) | B | ledger M-007 |
| Port-B wiring/width in the 8 content-bearing dump blocks | not decoded | A (these are the 8 blocks that actually hold data in the image, including the AF3 engine's own tiles) | UNTRACKED specifically for port-B of the dump set; general gap is M9K agent's open item in `cycloneiv-clean-hardblocks.md` §M9K content dump |
| Which port reads which half in the 2 TDP dual-port-view blocks (x36 word vs 2×x18 view) | not decoded | A (one of these pairs is 7_85/7_86, the AF3 RAM — see §13) | same as above |
| Image non-content-content MEAB residue | **14,047,344 bits** (tile) + 102,970 (bands) unclaimed by any vendor record | B | `docs/altera/cycloneIV/cycloneiv-address-spaces.md` §5 |
| Mode breakdown (from CRAM, image, all decoded structurally): single port 359 (267 w1, 44 w2, 20 w4, 23 w8, 25 w9, 6 w16, 7 w18, 149 w36-class... — note the hardblocks-doc figures (359/178/3/2) and the newer m9k_modes.py figures differ slightly in categorization language but agree on totals) | 359 single / 178 SDP / 3 ROM / 2 TDP | — | not a gap, well-covered |

Manual-review cross-check: B4 (byte-enable old/new-data output rule) and B9 (packed mode legality) are **GAP** status in the handbook-comparison table — the manual *defines* the behaviour but pluribus hasn't implemented it; ranked #1 in the manual-review's own "GAPs ranked for the DJI lift" list, but **0 image tiles use byte enables or packed mode**, so severity is **B only**, not A.

## 6. MAC (DSP / multiplier)

- All 17 asmdb group types for block 41 are now exercised and CONFIRMED_BY_CODE (ledger M-009, MA-002, MA-003, MA-004). No accumulate/saturate/round/shift/chain groups exist in this device's hardware at all (E-T4, confirmed from the asmdb survey, not just absence-of-evidence) — **not a gap, a documented hardware absence** (manual review C2 CONSISTENT).
- Image: 87 of 360 instances used, all decoded (registers, signs, pins, 2 in 9-bit mode). `build.json`: 0 undecoded MAC items.
- Multi-tile 36-bit composition (several 18×18 tiles + LE adders forming one wide multiply) explicitly "not modelled" as a MAC *mode* — correct, because the handbook (C2) says there is no such wide hardware mode; it's ordinary LE logic, already lifted as LAB adders. Not a gap.
- **No remaining MAC gap beyond #169's resolved items.** Severity: none / closed.

## 7. PLL

| Item | Status | Severity | Tracked |
|---|---|---|---|
| PLL_CLKIN source select (which of 4 parents feeds each PLL) | **RESOLVED** 2026-10-30/31: lives in CFF address space (T-007), not CRAM; image PLL_2 + PLL_8 index-0 both trace to ball B14 via element 666/tile X57Y91, no cascade | was A, now closed | P-011/P-014/P-015, errata E-U6/E-U7, #176 |
| `build.json` counted "PLL: input clock source: 2" undecoded | **was NOT a stale counter — `emit.py`'s `_hard` never called the routing trace that resolved the row above; two unmerged analyses, not bookkeeping lag.** Fixed #181 point 2: `pll.clkin_source` (shared with the standalone tracer script) now runs inside `emit.Builder._hard`; the netlist reports `clkin_ball` and the undecoded count for this cause is 0 on this image | was C, now closed | #181 point 2 |
| 2 missing pips in fast gate (`IO_RAW_DATAIN -> PLL_CLKIN`, value-00 case) | open rule gap (PLL_2/PLL_8-shaped edges with no literal never fire under the current flag rule) — **separate from the row above**: `cycloneiv_clean_pll_gate.py` unaffected by the #181 point 2 emit.py integration, still shows the same missing pip on `gxhb_pllmp_sw`/`site6`/`site7` (PLLREFCLKMUX path, not element 666) | B | #176, ledger P-014 (SPECIMEN_ONLY) |
| Switchover, scan chain layout (144 bits), dynamic reconfiguration | groups present (`PLL_CLOCK_SWITCH_*`, `PLL_SCAN_*`) but writers not decompiled | B (image uses neither: 2 PLLs, no switchover evidence) | `cycloneiv-clean-hardblocks.md` "PLL leftovers"; manual-review D5/D6/D8 GAP |
| Lock-detect, areset/pfdena/clkswitch/scan* input muxes | edges exist but PHASEUPDOWN/PHASESTEP/PHASECOUNTERSELECT/EXTCLK_ENABLE unspecimened (by elimination only) | B | ledger P-013 |
| PLL_6/PLL_7 "not placeable" claim | **WRONG** — F896 has all 8 PLLs; PLL_6/PLL_7 are mode-limited (No-Compensation/Deterministic-Latency, C0/C4 only), not package-limited | B — corrected but specimens for those modes not yet built | errata E-U3, manual-review D1/D2/G8, ledger P-002 |
| ZERO_DELAY_BUFFER / LVDS PLL modes | fail in `quartus_map` — not buildable, so not a decode gap | n/a | hardblocks.md "Not decoded" line |
| Loop filter R/C, charge pump, VCO post-scale, bandwidth preset | **decoded and scored**, 308/0/0/0 over 28 builds | closed | hardblocks.md "PLL leftovers" |
| M/N/C output-counter encoding | CONFIRMED_BY_CODE + 224/0/0/0 scored | closed | P-003 |
| PLL element-descriptor object stream (`ddb_stingray4_hdr.ddb` xz payload) | not located (only 2 of unknown-many objects parse, neither carries 2D data) | B | hardblocks.md §"PLL element descriptor" |

Image: 2 PLLs enabled (PLL_2 M14/N1/c0 50:50; PLL_8 M20/N1/c0 4:4/c3 8:8, VCO post-scale 2). Fin interval known only as [54.9, 83.3] MHz (shared crystal through B14) — the *board-level* crystal value is a hardware fact, not a bitstream decode gap (outside pluribus's scope).

## 8. IO (pads)

Exact image counts from `build.json`:

| Item | Count | Severity | Tracked |
|---|---|---|---|
| IO standard, undecoded (ambiguous between several CFF-identical standards) | **75** (44 outputs: 2.5V or SSTL-2 Class I; 31 inputs: 2.5V / 3.0V / 3.3V LVTTL/LVCMOS / 3.0V PCI) | A — largest single undecoded-item count on the whole image | UNTRACKED as a numbered issue; covered narratively in `cycloneiv-clean-io.md` "Value laws..." §"CFF-indistinguishable pairs" and in `cycloneiv-clean-image.md` decode table, but no issue tracks the 75-instance figure specifically. This is a genuine hardware CFF-indistinguishability (manual review A19 CONSISTENT — these ARE electrically identical standards sharing one input buffer), so it may be **unresolvable in principle**, not merely undecoded — worth flagging that distinction in any filed issue. |
| IO termination, ambiguous (none or 50-ohm-series: CFF-identical) | **44** | A for completeness, but likely **unresolvable** (manual review: 50-ohm-series-without-calibration is the *default* driver with 0 CFF bits — G1/A21 CONSISTENT) | UNTRACKED; same CFF-identity caveat as above |
| Input pad, undecoded IO site (direction from routing only) | 1 | A (minor) | UNTRACKED |
| Slew | 53 decoded (all "fast", value 2); 31 n/a (inputs) | — | not a gap |
| Direction | 84/84 decoded | — | not a gap |
| Pull-up / bus-hold / open-drain / drive | 84/84 default (off/default) | — | not a gap |
| Registered input/output/OE | 84/84 decoded OFF | — | not a gap |
| MISSING IO sites | **0** (was 6/13, fixed by the K-006/E-R8 frame-end-check-cell discovery) | closed | K-006 |
| Constant output pads | 6 (5 HIO + 1 VIO), all decoded | closed | K-008 |
| VREF pad -> pin map | not decoded; hypothesis ("nearest VREF by site index") holds 19/20, unverified, not used by decoder | B (image: does the image use any voltage-referenced standard needing VREF? Not stated — the 75-ambiguous-standard set does NOT include SSTL/HSTL per the decode table, so likely no image impact) | manual-review A6/A7/G4, ledger I-012 (UNKNOWN) |
| Package inference | **F672, exact** (82/82 unbonded sites accounted) | closed | K-005, K-007 |
| Drive strength beyond 4/8/12/16mA/min/max, and drive under non-2.5V standards | not built (image uses only 2.5V default, so no image impact) | B | manual-review A20 GAP |
| Differential pairing / LVDS | decoded for input + `_E_3R`-style pseudo-diff outputs; true LVDS/mini-LVDS outputs refused by fitter outside banks 5/6 (device rule, not a gap) | — | mostly closed; 6 image sites with stray IOST/strength bits (IOST 3 or 7) still **MISSING**, matching none of the known LVDS/pseudo-diff patterns | `cycloneiv-clean-io.md` "Stingray IO value path" tail — **UNTRACKED**, 6-site residual |
| Dual-purpose config pads (nCEO, DATA0-7/ASDO, nCSO, DCLK, CLKUSR, INIT_DONE, CRC_ERROR, DEV_OE, DEV_CLRn) | mostly decoded (option-dependent cells for INIT_DONE/CRC_ERROR/nCEO/DCLK); ASDO/nCSO/CLKUSR-as-regular-IO option-dependent cells **not built** | B | manual-review A14/F9, ledger K-009 |

## 9. Clock network beyond PLL

- Global clock tree structure (CLKBUF_OUT -> GLOBAL_CLK_H -> GLOBAL_CLK_V -> SCLK_TO_ROWCLK_BUF -> LAB_CLK(fanin 30) -> BLK_CLK_BUF): CONFIRMED_BY_CODE as routing-graph structure (C-001); edge *programming* rules: T-001 (CONFIRMED_BY_CODE) for normal edges, **T-003/T-004 remain SPECIMEN_ONLY** — "no code reading of default-list conduction" for the H->V clock edge (120 edges) and "no code located" for the empty-group fan-in-1 structural edges (145,283 edges, all clock). Severity **B** (empirically scored 100% via the gate, but the *rule* driving it is unverified against assembler code). Tracked T-003, T-004.
- Clock buffer site order (30 sites = 5 tiles × 6): CONFIRMED_BY_CODE for site->tile mapping (B-011) and PARENTS (B-015); the *z-within-run* ordering is "specimen-confirmed only" at 4 sampled sites — B-011 notes `resolve_clock_buffer_index_for_blk_type` (a runtime-built std::map) is "not read." Severity **C**.
- Dedicated-buffer element 666 chain (feeding `CLKPIN_TO_PLLCLKIN_MUX`, hence PLL input in this image): decoded 2026-10-31, P-015, MIXED derivation (image-only, no corpus build selects element 666) — **this is the "LAB_CLK/dedicated-buffer/666-element chain already partly traced" the task mentions; it is now FULLY traced for the image's actual path**, severity closed for the image, **B** for general-device claims (no corpus specimen exists; SPECIMEN_ONLY equivalent, though ledger marks P-015 as a MIXED row not formally SPECIMEN_ONLY).
- Clock switchover (device feature, D6/D8 in manual review): no asmdb group named for it anywhere in the tree. Severity **B**, image doesn't appear to use it (2 PLLs, no switchover evidence in the decode).
- Global-network clock inversion (C-003): see §3 above, duplicated here because it's as much a clock-network gap as an FF-control gap. **UNKNOWN status**, no specimen. Severity **B**, possible **A** if the image's non-dominant clock domains (2–5, totaling ~13,000+ FFs) use such a source — not checked.

## 10. Option/config bits

From `docs/altera/cycloneIV/cycloneiv-clean-options.md` + `docs/altera/cycloneIV/cycloneiv-address-spaces.md`:

| Item | Count | Severity | Tracked |
|---|---|---|---|
| Option bits with no decoded function (35 forced + 95 default) | **130 of 160** | B (image: all 130 read the constant `1` in the image, same as every Quartus/vendor build — so functionally this is "known to always be 1," just not *why*) | options.md §9, address-spaces.md §7, ledger O-002 |
| Image: option bits differing from a Quartus-built reference | **14 of 320** (lanes 0,1,3) | A — these 14 differing bits have **no decoded meaning at all** (`cycloneiv-clean-image.md` line 41: "meaning not decoded: all MISSING") | UNTRACKED as its own issue — only noted inline in cycloneiv-clean-image.md's decode table |
| JTAG option-register classes (`OPTION_REG_JTAG_CORE_ACCESS`, `_USE_JTAG_PIN_SHARE`) | have no asmdb group on this die at all — 0 bits, confirmed absent, not merely undecoded | closed (E-A1) | — |
| USERCODE / header-lane mechanics | fully decoded (checksum formula, K-002) | closed | — |

## 11. JTAG / remote update / other periphery (CFF)

- TAP state machine, IR/DR shift mechanics: **no address space, no sof tag, no rbf region exists for them at all** — confirmed absent (not a decode gap; it's hardened logic outside the assembler's config model). `docs/altera/cycloneIV/cycloneiv-address-spaces.md` §4.
- 15 `ASM_JTAG_*` classes: 4 of 15 have an asmdb group on this die (2 groups × 16 CRAM bits = core-side TDOUSER/TDOUTAP routing muxes; TDOUTAP is fitter-rejected if driven); the other 11 have **no group at all** (core-side TCK/TDI/TMS/CORECTL routing + 5 `_INVERT` classes + `ENABLE_BST_SUPPORT`) — confirmed not configurable on this die, not undecoded. options.md §5.
- Remote update (RSU): AN "Remote system upgrade fails to revert on GX" errata item exists (manual-review errata table) but RSU option ids in the option table are **untested** ("not needed for a plain lift"). Severity **B**, likely **not applicable** — lightbridge-fpga.md infers remote update is "in use (I)" from hardblock survey but this was never confirmed against actual option-bit evidence. **Flag**: the "remote update in use" claim in lightbridge-fpga.md §1 is **I (inferred)**, not verified — worth downgrading or checking against the option-bit decode. UNTRACKED discrepancy.
- Image JTAG tile frames 6134-6145: 66 residue set-bits, 29/23/14 split (set-in-all / set-in-none / varies) — unexplained but tiny; `docs/altera/cycloneIV/cycloneiv-clean-image.md` "Residue set bits by region". Severity **C**.
- CFF: 31,060 bits total; 104 default-list addresses decoded, **0 of 31,060 field values decoded by function** (only by pair-diff/anchor-offset table, which covers IO fields specifically — non-IO CFF content, if any exists beyond IO/PLL/clock-buffer/JTAG, is unaccounted). Address-spaces.md §5.5 / §6 coverage table.

## 12. Transceiver / PCIe / other hard IP

- Confirmed **absent from use** (not merely unchecked): lightbridge-fpga.md §11 states "no transceiver or PCIe cells differ from idle (positive control missing)" — but this is explicitly flagged in the same line as "positive control missing," meaning it's an **absence-of-evidence**, not a vendor-confirmed absence.
- GX transceiver settings (604 `GX_*` group names across RX_PCS/TX_PCS/RX_PMA/CMU/TX_PMA/CALIBRATION, plus HSSI_PCIE_HIP/HSSI_STRIP): written by generic `ASMGX_*` CGA classes (143 group types), model class `ASMGX_HCXIV_MODEL`; the per-group CGA-enum -> setting-name table and the "other 3,460 asmgx cases" walk are **not decoded** — `docs/altera/cycloneIV/cycloneiv-clean-hardblocks-reversing.md` §1/§3.
- Absolute-address GX/HSSI CRAM claimed-but-undecoded: GX_TX_PCS 5,948 + GX_RX_PCS 1,852 + GX_CMU 984 + GX_RX_PMA 896 + GX_CALIBRATION 55 + HSSI_STRIP 10,275 + HSSI_PCIE_HIP 11,550 bits = **~31,560 bits claimed (address known) but field-undecoded**. hardblocks-reversing.md §2.
- **Conclusion**: transceiver/PCIe hard IP is "**not checked**" for this image, not "verified absent." Severity **B** for the general claim; **A if wrong** for the image (if the image silently uses a transceiver feature DJI relies on, that's currently invisible to the lift). This distinction (verified-absent vs not-checked) is NOT clearly drawn anywhere in the existing docs — `lightbridge-fpga.md`'s phrasing ("no ... cells differ from idle") undersells how little was actually checked. **UNTRACKED finding**: recommend an explicit issue to either (a) run the CGA-class walk against the image's GX/HSSI claimed bits to get a real used/unused count, or (b) soften the lightbridge-fpga.md claim.

## 13. AF3 / SHA-1 engine

Per `docs/altera/cycloneIV/cycloneiv-clean-af3-engine.md` "Open" + lightbridge-fpga.md §11a:

| Item | Status | Severity | Tracked |
|---|---|---|---|
| Per-op split of SHA-1 round-body ops 3/4/7/8/9/B | **I** (inferred) — loop gives bit-exact SHA-1, but which op does what inside the round is not verified | A (it's this image's own mechanism) | #165 (af3-engine comments), af3-engine.md |
| CRC-8 (ROM) / CRC-16 (data) handling | not decoded; the 8-FF and 10-FF registers are "CRC-shaped" (I) only | A | af3-engine.md |
| Derived engine clock source (which counter divides Fin to the 20-40MHz 1-Wire rate) | **U**, unknown | A | af3-engine.md |
| Serial-loader source types T367/T369 | not analysed | A | af3-engine.md |
| Provenance of the two SHA-1 key words (W0/W12, program-derived from bus-read bytes) | not analysed, explicit "stop point for a decision" | A | af3-engine.md "Open" |
| RAM_WRITE_ENABLE_INVERT bug | **FIXED** for the 2 AF3 tiles (7_85/7_86) | closed for these 2 tiles | #178 |

## 14. The #178 48-tile question (7_85/7_86 generalization)

- #178: tiles 7_85/7_86 are 2 of 542 with raw `RAM_WRITE_ENABLE_INVERT` pair (1,0); **492 tiles have (0,1)**, **48 tiles have (1,1)**, **2 tiles have (1,0)** [these 2 are 7_85/7_86]. Wait — re-reading #178 precisely: "492 tiles (0,1), 48 tiles (1,1), 2 tiles (1,0)" — the 2 fixed tiles are the (1,0) pair; the **48-tile (1,1) group is explicitly unchecked**.
- `emit.py` never reads `RAM_WRITE_ENABLE_INVERT` at all (only `ce_invert`) — so this is a **systematic gap across all 542 M9K tiles**, not just the 48: the group is simply not consumed by emit anywhere. The 492-tile (0,1) default case was *assumed* correct by the prior single-port rule but was never specifically verified post-fix either.
- Separately: `m9k_tdp.py`'s A-we=gi9/B-we=gi11 TDP convention **disagrees** with the hardblocks/m9k docs' single-port PORTAWE=gi11 rule, confirmed swapped on the 2 checked TDP tiles (7_85/7_86) via `scripts/cycloneiv_clean_tdp_we_check.py`.
- **Severity A** for the 48 (1,1) tiles and the 492 (0,1) tiles (any of them could be silently wrong in emit/RTL/sim) — tracked #178, explicitly left open ("needs a specimen check before any claim" — issue body's own words). Already tracked, not untracked, but worth restating as the single clearest highest-severity *tracked* image-correctness gap: **it affects up to 542 of 542 M9K tiles' write-enable correctness**, not just the 2 originally found.

## 15. Readable RTL lift: 418 remaining flat LUTs

From `docs/altera/cycloneIV/cycloneiv-clean-rtl.md` "Third-party image" table (HEAD a080869a1, "after" column):

- 418 of 89,282 LUTs remain `FLAT_LUT` (0.47%), down from 10,178 before the mixed-polarity/dead-flop/head-ambiguity fixes.
- Breakdown given: **"40 chains, all `no_operand_form`"** — the doc names exactly 3 categories inline: *"multi-LE result tails after the adder bits, AND-gated operand incrementers, bits whose second operand repeats one signal."* No per-category count is recorded anywhere (the task's "~3 categories, exact count per category if recorded" — **not recorded**, only the chain total of 40 chains / categories named, not split). Severity **C** (these are leftover flat LUTs in an already-96%+ lifted netlist; cosmetic for RTL readability, not a correctness gap — `rtl_check` chain verification shows 0 mismatches over 2,061 recognized chains). UNTRACKED as a numbered issue but fully described in the doc; filing would only be to track the per-category split, not the existence of the gap.

## 16. Found during this audit, not in any prior chat summary

- **Stale "undecoded" counters in `cycloneiv_clean_image_build.py`'s `build.json` output**: "PLL: input clock source": 2 is stale post-P-011-fix (§7). The script's undecoded-counter set also has **no M9K-control counters at all** (§5) despite `cycloneiv-clean-m9k.md` independently recording 14/101-tile gaps — meaning the single machine-measured source of truth the task asked us to treat as authoritative is itself **incomplete and partly stale**, and these two facts contradict each other silently (the build.json undecoded dict and the m9k.md prose were never reconciled).
- **The 14-bit image/reference option-register difference** (§10) has zero narrative discussion anywhere outside one inline table cell in `cycloneiv-clean-image.md`. No issue, no ledger row.
- **6 image IO sites with stray IOST 3/7 or single-strength-bit patterns** matching none of the known differential/pseudo-diff builds (§8) — explicitly still MISSING as of the latest io.md entry, no issue number.
- **75-instance IO-standard and 44-instance IO-termination ambiguity** (§8) is the single largest *named, counted* undecoded item in the whole image per build.json, yet has no issue of its own — it's mentioned only in doc prose. Given the manual-review's own finding that several of these ambiguities may be **physically unresolvable** (true CFF-level equivalence classes, not decoder gaps), an issue should distinguish "want to resolve" vs "document as inherently ambiguous and close."
- **Transceiver/PCIe "verified absent" overclaim** (§12): lightbridge-fpga.md's phrasing reads stronger than the underlying evidence (which is closer to "not checked" than "verified absent"). No contradiction was filed anywhere; this audit is the first place the distinction is drawn explicitly.
- **"Remote update in use" inference** (§11) in lightbridge-fpga.md §1 is tagged (I) but never cross-checked against the option-bit decode (which has the RSU-related option ids available but untested) — a cheap check was never run.
- **Full-tier gate 193 missing / 51 missing nets** (#177 item 2) has no root-cause breakdown by category anywhere (the task asked for breakdown "if the gate breaks it down" — it does not; #177 only gives the two headline totals).
- **C-003 global-network clock inversion** doubles as both an FF-control gap (§3) and a clock-network gap (§9) in the existing docs' own cross-references, but no doc states which (if any) of the image's non-dominant clock domains might depend on it — this was never checked against the image specifically, only noted as a general-device unknown.

## Summary

- **Total distinct gap items catalogued above: ~55** (counting each table row / bullet with its own evidence as one item; exact count depends on how finely sub-items are split — see per-section tables).
- **Already tracked** (issue number, ledger row, or named doc section with an explicit "Open"/status marker): the large majority — essentially everything in §§1–4, 6–7 (the PLL-source row is now RESOLVED via #181 point 2, not a tracked-open item), 9, 11 (except the RSU cross-check), 12 (the absence-of-evidence framing itself is new), 13, 14, 15.
- **UNTRACKED** (no issue, no ledger row, found or re-flagged by this audit): §3 (ASDATA gap — now tracked F-020/#182, fully resolved 131 -> 0; the separate C-003 global-network clock-inversion item is still untracked), §5 (14-tile output-CE-select gap, 101-tile output-clear gap, port-B/TDP-view gaps in the 8 content-bearing + 2 TDP blocks as standalone issues), §8 (75-instance IO-standard gap, 44-instance IO-termination gap, 6-site stray-IOST residual, each as a standalone issue — noting the IO-standard/termination items may be inherently unresolvable and worth closing-as-documented rather than fixing), §10 (14-bit image/reference option difference), §11 (remote-update-in-use inference never cross-checked), §12 (transceiver/PCIe "not checked" vs "verified absent" distinction), §16 (build.json counter set incompleteness/staleness itself).
