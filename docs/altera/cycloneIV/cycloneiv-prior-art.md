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

Removed with the other-die work: full table in #173. Outcome: frame size, CRC, column step and row pitch agree with 14sea; they disagree on the lane-join zone and row 20 (our side exact against the post-fit netlist). Script `cycloneiv_prior_art_xcheck.py` removed.

## Licence: what we may reuse

Read and cite facts with credit; run their scripts as an external oracle; do not copy their code (GPL-3.0-or-later) or reproduce their CRAM models, formulas or CRC specification in our tree without BY-SA 4.0 and credit, and do not redistribute their RBF or Quartus-generated files. The numbers quoted above are constants used for comparison and are credited here.

## Gaps

- Not reachable or not run: grep.app / searchcode full-text (one query each), rate-limited GitHub code queries, paywalled Ren et al. and PSE23 supplements, Bilibili / Zhihu / 4pda content (title-level only), Gitee and Gitea instances (not searched).
- No silicon on our side; every lane-join claim rests on the Quartus post-fit netlist oracle.
- 14sea's routing signatures (1,725 route cell-sets) not compared with our RCF-based tables.

## Recommended actions

- Cite 14sea as independent confirmation of frame size, CRC, column geometry and row pitch in `cycloneiv-bitstream.md`.
- Ask the owner (public issue, after Dan's review) whether the lane-join zone and Y20 were tested on silicon; offer the affected site addresses (X10 Y3 N12 is one).
- Read Ren et al. if the compressed-format coverage (Cyclone III LS, GX) is ever in doubt; our decoder already matches the vendor on 70 / 70.
- Routing comparison (their LI/R4/C4 signatures vs our tables) is the next useful cross-check; needs a coordinate map first.
- Re-run the code searches after the rate limit resets for the 6 gap queries.
