# Cyclone IV prior art (2026-10-29)

Verdict: **partial.** One project overlaps strongly on EP4CE6 (14sea/Cyclone_CRAM_Mapper). Two papers touch the format (LUT mapping, decompression), paywalled, no code or data found. Nothing else found for Cyclone III/IV fabric, routing, lifters, MAX 10 or Cyclone 10 LP.

## Venues and queries (negatives included)

Search engines are weak on code; empty results are "not found by this query", not proof of absence.

| Venue | Queries | Result |
|---|---|---|
| GitHub repos (`gh search repos`) | `cycloneive_lcell_comb`, `EP4CE6 reverse engineering`, `cyclone iv reverse engineering`, `cyclone iv bitstream`, `cyclone iii bitstream`, `altera bitstream`, `altera fpga reverse engineering`, `max10 bitstream`, `cyclone10lp`, `rbf parser quartus`, `cyclone iv nextpnr`, `cyclone iv open source toolchain`, `EP4CGX`, `intel fpga bitstream documentation`, `quartus bitstream decoder`, `cram fuzz fpga altera` | 0 relevant; boards and application projects only |
| GitHub code (`gh search code`) | `cyclone iv bitstream reverse`, `altera bitstream reverse engineering`, `cycloneive_lcell_comb lut_mask rbf`, `EP4CE10 bitstream rbf`, `prjquartus`, `cycloneiv rbf`, `MAX 10 bitstream rbf`, `cyclone iii rbf crc`, `cycloneive EP4CE bitstream rbf frame`, `EP4CE6 cram`, `cyclone iv cram frame`, `cyclone iii rbf bitstream frame crc`, `0xFE54 crc rbf`, `cycloneive tilegrid`, `altera rbf parser`, `quartus_cpf rbf decode`, `"Cyclone IV" bitstream`, `EP4CE6`, `nextpnr cyclone`, `prjcyclone`, `stratix bitstream reverse`, `cycloneiv chipdb`, `EP4CE22 bitstream`, `cyclone_iv bitstream` | only 14sea (`EP4CE6 cram`, `EP4CE6`) |
| GitHub code, rate-limited (403), not re-run | `cycloneive_lcell_comb`, `"Cyclone_CRAM_Mapper"`, `10M50 rbf format`, `cyclone 10 lp rbf`, `arria bitstream reverse`, `project mistral cyclone iv` | gap |
| GitHub issues | `cyclone iv bitstream`, `EP4CE6 bitstream`, `altera cyclone reverse engineering bitstream`, `cycloneive reverse`, `cyclone 10 lp bitstream`, `MAX 10 bitstream reverse` (global search returns noise); repo-scoped: nextpnr `cyclone`, `cyclone iv`; mistral `cyclone iv`; prjtrellis `altera` | mistral#20 (Cyclone IV not supported, "not ruled out"); nextpnr: Cyclone V only |
| GitLab, Codeberg, sr.ht, Bitbucket, SourceForge | DuckDuckGo `site:` queries (`cyclone iv bitstream`, `altera cyclone bitstream`, `cyclone iv bitstream rbf`, `altera rbf bitstream cyclone parser`) via playwrong | 0 relevant (SourceForge: OpenOCD altera pld patch, rapidsmith = Xilinx) |
| grep.app | `cycloneive_lcell_comb rbf` | no results |
| searchcode.com | `cycloneive bitstream` | page rendered the landing page only; query not executed (gap) |
| Web, English | `Cyclone IV bitstream reverse engineering rbf format EP4CE`; `"Cyclone IV" bitstream "reverse engineering" CRAM LUT mask open source toolchain`; `altera cyclone rbf file format frame CRC 0xFE54`; `Altera .sof .pof .rbf file format reverse engineered parser github Cyclone III`; `Cyclone III Cyclone IV compressed rbf bitstream decompression algorithm reverse`; `MAX 10 bitstream reverse engineering open source rbf cfm format`; `Cyclone 10 LP bitstream format reverse engineered open source`; `hackaday ... nextpnr cyclone iv support`; `eevblog reverse engineering Cyclone IV ...`; `"Cyclone_CRAM_Mapper" ... fork OR cites` | 14sea and derivatives, Altera forum threads, EEVblog parser, 2 decompression papers |
| Chinese | `Cyclone IV 比特流 逆向 rbf 格式 CRAM 解析`; `知乎 Altera Cyclone 比特流 逆向 rbf LUT ...`; `bilibili Cyclone IV 比特流 逆向 开源 工具链` | 14sea's own zh README only; CSDN/Zhihu hits are generic (title-level, one CSDN page read: generic Xilinx overview) |
| Russian | `Cyclone IV прошивка rbf формат реверс инжиниринг битстрим Altera`; `4pda Cyclone EP4CE прошивка rbf анализ формата` | 0 relevant (electronix.ru / Habr hits are board and programming threads, title-level) |
| Forums | EEVblog (3 queries above + thread read), Altera/Intel Community threads 20895, 189364, 81360 (listed), 167597 (listed) | no answers; "format is non-public" |
| Conferences / eprints | `arXiv reverse engineering Intel Altera Cyclone bitstream netlist recovery`; `eprint.iacr.org FPGA bitstream reverse engineering Altera Cyclone`; `FPT ReConFig ... Cyclone IV ...`; `CCC ... FPGA bitstream reverse engineering Altera Cyclone talk`; NAECON title search | PSE23, Ren et al.; CCC 34C3 talk is Xilinx/iCE40; IACR hits are Xilinx |
| SoK arXiv 2603.17883 v2 | full PDF text read (40 pp.) | see below |

### SoK 2603.17883 (Karadag et al., 187 papers): every Altera / Intel citation

- Table 1 (format RE) has 16 rows; one is Intel: **[PSE23]** (AMD/Intel, Cyclone IV/V, "All LUTs 100%").
- Text: "disproportionate focus on AMD ... especially from Intel, which remain drastically underrepresented"; no other Intel format-RE paper cited.
- **[SMOP15]** Swierczynski et al., Stratix II/III bitstream encryption (side channel), cited under F3 decryption. Not fabric RE.
- No Cyclone, MAX 10, 14sea or Mistral citation in the SoK.

## Hits

| Hit | Licence | Depth | Verdict |
|---|---|---|---|
| 14sea/Cyclone_CRAM_Mapper (EP4CE6F17C8, CE10 "jailbreak" columns) | code GPL-3.0-or-later; docs/findings CC BY-SA 4.0; bitstream data: no licence asserted | Deep. LUT mask codec, LAB column/row address model, LI/R4/C4 routing signatures (1,725 route cell-sets), M9K init codec, CRC patcher, FASM writer (`fasm2rbf`) + reverse (`rbf2fasm`), silicon-verified on a dev board. Uncompressed RBF only, EP4CE6/10 only. Direction is mostly write (netlist to RBF) plus a bit-level RBF to FASM round trip; no bitstream-to-netlist lifter | Overlaps our EP4CE6 LE model and frame/CRC layer. Does not cover compressed streams, GX parts, post-fit-oracle scoring or lifting. Treat as independent cross-validation, not a source |
| 14sea `bitstream-re` skill (skills.rest), LinkedIn post | same repo | Summary of the above | derivative, no new facts |
| Perumalla, Stowasser, Emmert, NAECON 2023 (PSE23) + US20240135077A1 | paper; patent | LUT-bit mapping only (XOR of a bitstream and its LUT-inverted twin); claims Xilinx 7-series and Intel Cyclone IV/V; routing listed as future work; no tables, code or device list found | LUT mask only; no data to compare. Patent is about the B / inverted-B method; note for freedom-to-operate if we ever publish that method |
| Ren, Zhang, Wang: EIT 2024 (IEEE 10762746), Int. J. Inf. Security 2025 (10.1007/s10207-025-00982-9) | paywalled; data "on request" | Decompression of Intel compressed bitstreams, "24 types, 6 families", 100% | Contradicts our earlier note "no public description of the compressed format". Abstract only; our decoder is 70/70 identical to Quartus output. Not read in full |
| Altera / Intel Community 20895, 189364; EEVblog "Parser for (Altera) FPGA programming files" (2017) | none | Questions and a closed-source container parser; reply: detailed format is non-public | no technical content |
| ivzeivze/altera_fmt_lib | none stated | JIC container parsing | container only |
| Ravenslofty/mistral#20 | n/a | Maintainer: Cyclone IV not supported | confirms gap |

## 14sea cross-check (EP4CE6)

Method: `scripts/cycloneiv_prior_art_xcheck.py` imports their `fuzz/config.py` from the gitignored clone (nothing copied), converts their byte addresses to (frame, byte, lane) with our 210-byte frame geometry, and compares with our LE model (`lifters/data/cycloneiv_ep4ce6_geom.json`). Log `tmp/logs/cycloneiv_prior_art_xcheck.log`. Clone at commit 221f790 (2026-09-30). Oracle for our side: Quartus post-fit netlist, 292 EP4CE6 LE cells in `lut_*`, `site_*`, `ho_*`, `ho2_*` (includes sites that trained the model; the fresh held-out `ho2_*` scored 0 bad, see `cycloneiv-bitstream.md`). Theirs: silicon.

| Item | Theirs | Ours | Result |
|---|---|---|---|
| File size, preamble, postamble | 368,011 B; 32 B FF; 59 B FF | same | agree |
| Frame size, CRAM frames | 210 B; frames 25..1751 | F = 210; 25 periphery + 1,727 CRAM | agree |
| Frame CRC | CRC-16/IBM (poly 0x8005 reflected), init 0xFE54, at frame bytes +208/+209 | poly 0xA001 reflected, init 0xFE54, last 2 bytes | agree |
| Header | `6A F7 F7 F7 F7 F7 F7 F3 FB` constant at 0x20; 12 design-dependent bytes at 0x29..0x34; checksum at 0x49..0x4A | same 9 bytes in 2 corpus files; bytes 41..52 vary; CRC-16/MODBUS of the 40 option bytes at 0x49..0x4A | agree |
| Column step | 7,350 B standard | 35 frames x 210 = 7,350 B | agree |
| Column bases, 27 consecutive LAB-column steps | e.g. X13 to X16 +76,230; X26 to X28 +68,880; X19 to X21 +12,600; X17 to X18 +8,190 | 363 / 328 / 60 / 39 frames = same bytes | agree, 0 of 27 steps differ |
| Column anchor | period start = base - 136 | their period start frame = our FX[X] - 7 for all 28 columns, byte 24 | agree (offset constant) |
| LAB columns | 22 whitelist + 6 "jailbreak" (X5, 9, 14, 30, 32, 33), described as M9K/DSP/PLL columns | all 28 are LAB columns in our geometry; our non-LAB columns are X15 (M9K), X20 (multiplier), X27 (M9K) | agree on positions; **disagree on what X5/9/14/30 are**: our LE decode is exact at X3..X33 incl. these (154 cells outside their grid) |
| LAB columns they never list | none | X1, X2 | we extend; exact on all our cells there |
| Cells per LE | 8 pairs, one ctrl pair per frame, 2 adjacent bytes, single bit | 8 consecutive frames, 2 adjacent v (bytes) per frame, same lane | agree: cell sets equal on 6,748 / 8,064 sites (83.7%) |
| Their "data" bytes | +48 B from ctrl, multi-bit, "XOR-linear" | none | **their data bytes are frame bytes 208/209 = the per-frame CRC** (0 of 129,024 mask bits land there). Matches their own later "CRC ghost" note. Our model: one cell per mask bit, no XOR |
| Y rows | `slot = (Y-2)%3`, base {136, 0, 70}, +3 per group, bit = 7 - group - (slot>0) | VY = 21 + 70 Y in lane-major v (70 v per row) | agree: their slot/group is the 70 v row pitch seen as bytes with lane steps; offset 1 byte (ctrl vs ctrl+1 = the two cells of a pair) |
| LE N offset | step -2/-6 pattern, extra -12 at N=16 | DN = 0, -3, -8, -11, ... -38 ... -65, mirror for odd LE | agree for 6,748 sites; see lane-join row |
| **Lane-join zone** | linear address, no lane change | bits at v 206/207 live in lane-7 tail bytes 206/207; v 413, 620, ... similar (`lane_swaps`) | **disagree on 1,316 / 8,064 sites (16.3%)**: rows Y3, 6, 9, 12, 18, 21 at N >= 12. Example X10 Y3 N12: ours (frame 389, byte 206, lane 7), theirs (389, byte 0, lane 6). Evidence favours ours: 16 / 16 corpus cells in this zone decode exactly against the post-fit mask. Bug lead on their side (their N=0-weighted verification would not reach it); untested on silicon by us |
| LUT mask polarity / order | XOR-linear TT, pair table `TT[7],TT[15]` share a pair | mask bits 2 per frame in k order (0,1 / 2,3 ... 14,15), no inversion | k-to-pair labelling differs (their README puts TT7 and TT15 in one pair; ours puts k14 and k15 in one frame). Same cell sets, so it may be an index convention on their side (their TT index is from minterm labels). Ours is exact on 292 / 292 cells; theirs unchecked on this point |
| Row 15 | ghost row: absent from fitter; formula validated on silicon at X10 Y15 | no corpus placement at Y15 (X1 Y12..16 are not LEs); VY is linear through Y15 | their Y15 cells equal ours on 176 / 352 sites, rest in the lane-join zone: consistent, not independently tested by us |
| Row 20 | "does not exist" | real LAB row: `ho2_x16_y20_n2`, `ho2_x26_y20_n4` place and decode exactly (4 cells) | **disagree** on existence; their statement is a fitter-whitelist fact (Quartus 21.1, F17 package). Ours: Quartus 25.1, E22 package. Their formula gives equal cell sets at Y20 on 352 / 352 sites |
| Rows beyond their grid | Y 2..21 only | Y1, Y22, Y23 exist; ours exact on those cells | we extend; their formula agrees at Y22/Y23 (352 / 352), not at Y1 (0 / 352, formula not meant to extrapolate there) |
| Compression | not covered | decoder, 70 / 70 pairs | ours only |
| Routing, FF, M9K | LI/R4/C4 signatures, M9K init codec, silicon | learnt tables, 80-92% on GX150, EP4CE6 routing paused | not compared here |

## Licence: what we may reuse

Read and cite facts with credit; run their scripts as an external oracle; do not copy their code (GPL-3.0-or-later) or reproduce their CRAM models, formulas or CRC specification in our tree without BY-SA 4.0 and credit, and do not redistribute their RBF or Quartus-generated files. The numbers quoted above are constants used for comparison and are credited here.

## Gaps

- Not reachable or not run: grep.app / searchcode full-text (one query each), rate-limited GitHub code queries, paywalled Ren et al. and PSE23 supplements, Bilibili / Zhihu / 4pda content (title-level only), Gitee and Gitea instances (not searched).
- No silicon on our side; every lane-join claim rests on the Quartus post-fit netlist oracle.
- 14sea's routing signatures (1,725 route cell-sets) not compared with our RCF-based tables.

## Recommended actions

- Keep our EP4CE6 LE model; no change needed from this sweep.
- Cite 14sea as independent confirmation of frame size, CRC, column geometry and row pitch in `cycloneiv-bitstream.md`.
- Ask the owner (public issue, after Dan's review) whether the lane-join zone and Y20 were tested on silicon; offer the affected site addresses (X10 Y3 N12 is one).
- Read Ren et al. if the compressed-format coverage (Cyclone III LS, GX) is ever in doubt; our decoder already matches the vendor on 70 / 70.
- Routing comparison (their LI/R4/C4 signatures vs our tables) is the next useful cross-check; needs a coordinate map first.
- Re-run the code searches after the rate limit resets for the 6 gap queries.
