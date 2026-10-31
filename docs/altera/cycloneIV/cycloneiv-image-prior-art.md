# Prior art for the third-party EP4CGX150 image (#165)

Question: are its M9K tables and control structure copies of, or derived from, open-source designs, Altera/Intel IP or examples, or third-party WiMAX/OFDM modem designs?
Date 2026-10-31. Structure and counts only; no table values. Comparison code: `scripts/cycloneiv_prior_art_compare.py` (local dumps in `tmp/m9k_dump`, results `tmp/prior_art/compare.json`).
Tags: V = matched numerically or textually; I = suggestive; U = no evidence either way; N = structure does not fit (does not exclude).
Sequencer-agent ISA findings (`tmp/dji_microcode/`) had not landed; soft-CPU rows are geometry and field-spread only.

## Bottom line
- No copy of any open-source or Altera design is demonstrated. Zero V for copying.
- One V, not copy evidence: the PRBS15 seed equals the published DVB-T / IEEE 802.16 initialisation vector, so the scrambler follows the standard text.
- Strongest provenance lead (I): the PHY is DJI's own/Artosyn-linked design; the Artosyn AR8001 ASIC reimplements the FPGA bitstream (source 1-3). Prior art then is a closed vendor design, not a public one.
- Altera WiMAX material is built on the FFT MegaCore + block floating point; the image has no cos/sin twiddle table and no FFT-shaped M9K set (I, negative).
- Soft CPU: nothing identified. Candidates are geometry-compatible only; no processor datapath found by the detectors (U).

## Our fingerprints (inputs)
- 3 PRBS15 x^15+x^14+1 (seed below), 4 PRBS11 x^11+x^9+1, 1 serial CRC-16-CCITT init 0; no conv encoder, RS, HCS, interleaver permutation, FFT twiddle, preamble table.
- 226 counters, 21 FSMs, 1,377 adders, 87 MACs; 8 populated M9Ks of 542.
- Populated tables (extent x width): 512x18 monotone phase ramp (7_57); 512x18 4-level staircase (7_58); 423x18 opcode+operand-like (7_85); 266x18 ten constants (7_86); 512x18 two 100-word linear ramps (36_64); 511x18 decaying curves (36_82); 680x9 + 680x9(3 bits used) companion pair, microcode-like (94_57/94_58).
- SPI slave register file 0x00..0xCF; SPI master 24-bit frame engine; AD9363 CMOS DDR TX from two RAM lanes (9+3 bit).

## Local tests run
- PRBS15 seed (stage 1 = feedback input): observed 100101010000000 = published vector (V). Published in `jwise/dvbt` `prbs.c` (DVB-T energy dispersal; no licence file reported by `gh api`), and `moerjie/DVB-S` readme; the 802.16 OFDM randomiser uses the same vector (IEEE 802.16-2004 clause 8.3.3.1, cited by IEEE C802.16maint-04/66; vector itself from memory of the standard, not re-read).
  - Meaning: standard-conformant, shared by DVB and 802.16; says nothing about which implementation.
- PRBS11 x^11+x^9+1: period 2047; seeds 10110101110 and 00000101111 are 1622 and 1501 steps from the all-ones state (gap 121 steps, matches the seed-trace note). 802.16 OFDMA pilot PRBS is x^11+x^9+1 (Keysight/IEEE contribution listings), so the polynomial is the 802.16 class (I); seed use not matched to a standard value (U). The pilot-sign recovery from air captures (#165 comment 6522533900) did not find the PRBS11 on pilots (V, negative), so the PRBS11 role is unconfirmed.
- Geometry vs program stores: every 512x18 table fits KCPSM3 (18 x 1024), KCPSM6 (18 x 4096), Mico8 (18 x 1024) on width/depth; this is weak (any 512x18 RAM fits). 94_57 (9 bit, 680) + 94_58 (3 bit) = 12-bit word fits PIC12-class width only; no other fit.
- Field spread, 7_85 (18-bit view): bits [11:8] take 11 distinct values with 82.5% zero; bits [17:12] 23 distinct, most common 24.8%. A KCPSM3/Mico8 register-select field in a real program is not 82% zero (N for those ISAs, I-grade; depends on the 18-bit alignment and on 7_85 being code at all).
- Altera IP ROM depth match: none of the 8 tables has depth (17, 5, 65, 16, 256, 512 x 11, 4096, 65536) and width of an Altera FFT-II twiddle, NCO, BCH-inverse ROM in `reference/signatures.tsv` (the 512-deep tables are 18 bit, NCO small ROM is 512 x 11 sine) (N).

## Candidates

### 1. DJI / Artosyn in-house PHY (Lightbridge)
- What: the Lightbridge PHY; FPGA on early boards, later Artosyn AR8001 (baseband) + AR8003 (RF).
- Sources (all read this session):
  1. o-gs wiki, P3X OFDM Receiver board: "based on WiMAX, but uses custom processing"; Artosyn chip "has a design which exactly matches the previously used FPGA bitstream". https://github.com/o-gs/dji-firmware-tools/wiki/P3X-OFDM-Receiver-board (wiki; no licence stated). Same page: air FPGA is a Cyclone V; the AR8001 "implements digital processing previously handled by FPGA Bitstream". Ground FPGA firmware m2001 page is an empty stub ("TODO").
  2. fpvwiki.co.uk (Mads Tech Wiki): AR8001/AR8003 "appear to be ASICS of the design DJI was originally delivering in FPGA"; DJI worked closely with Artosyn early.
  3. EE-China interview with Artosyn co-founder/CTO (2023): Artosyn founded 2011, launched the first mass-production wireless video solution for DJI in 2013; gen 1 = AR8001 + AR8003 (2014); gen 2 = AR8020 + AR8003S. https://www.eet-china.com/mp/a220381.html
- Signature: ASIC mirrors the bitstream; Artosyn modulations BPSK/QPSK/16QAM/64QAM adaptive (wiki chip description); no numerology published.
- Comparison: the FPGA design is the prior art for the ASIC, not the reverse; a design house (Artosyn) may have written it (I). DJI-alone is not supported or refuted (U).
- Settling test: AR8001/AR8003 documentation or firmware register map vs the FPGA register file (SPI slave regs 0x00..0xCF, command 0x0E); an Artosyn SDK/driver for AR8001-era parts (public repos found are AR8020/AR8030-era only: `fpv-wtf/buildroot-libre-artosyn`, `gehee/ar_libre`).

### 2. Altera/Intel WiMAX OFDMA reference designs and DSP IP
- What: AN-412 "A Scalable OFDMA Engine for WiMAX" (May 2007): subchannelization + OFDM kernel (FFT/IFFT MegaCore, block floating point to fixed point), FFT 128/512/1K/2K, Avalon-ST glue; companion notes AN-450/451/452 (FFT kernel), AN-421 DUC/DDC, AN-430 ranging, AN-434 channel estimation, AN-439 mapper/demapper; RS and Viterbi MegaCore for FEC. Clear-text VHDL supplied on request via sales; not public. Also a marketing white paper (D. Boppana, 2005). Read: https://datasheet.datasheetarchive.com/originals/library/Datasheet-082/DASF0043968.pdf (18 pp), http://application-notes.digchip.com/038/38-21382.pdf (7 pp). Target devices there are Cyclone II/III, Stratix II/III (no Cyclone IV GX).
- Licence: Altera proprietary reference design; MegaCores need OpenCore Plus / licence.
- Signature (from AN-412 and `signatures.tsv`): FFT MegaCore = twiddle ROMs (e.g. 17/5/65-word ROMs at width 12-16), delay RAMs, 24-32 registered adders in variable-streaming 64/256-pt, 16-24 mult9... ; RS decoder = 970 FF + one 512 x 10 RAM; Viterbi K=7 = five RAMs + 64-state ACS.
- Comparison: image has 87 MACs, but no twiddle ROM content, no GF multiplier, no 64-FF ACS array, no RS/conv (N for the standard WiMAX chain: scrambler + RS + conv + interleaver). OFDMA subchannelization permutation tables (PUSC) also not in M9K (no permutation table, comment 6524020172). Altera FFT with twiddles in logic cannot be excluded: licensed cores yield no .rbf here, so no netlist-level test exists (U for FFT).
- Settling test: identify the FFT in the image (delay-RAM geometry, MAC count 12-20 per FFT, BFP exponent logic); compare to the report-level table in `docs/signature-cores.md` section 4.

### 3. Open WiMAX / OFDM FPGA designs
- Already built and compared as specimens (`docs/signature-cores.md` section 2): OmarElayat WiMAX channel coding (MIT: PRBS, K=7 conv, 192-bit interleaver), bishoy8599/WiMax_PHY (MIT), asultan123/WiMax_Channel_Coding, codyps/wimax_ofdm (stub), chemeris/wimax-scanner, jhshi/openofdm (802.11).
- New: phthinh/OFDM_802_16 (Verilog TX/RX/SYS, Xilinx ISE IP cores, preamble coefficient `.txt` files, correlation-based synchroniser). https://github.com/phthinh/OFDM_802_16 ; licence not stated on the page read.
- Signature: standard 802.16 OFDM preamble tables in text files, FFT as Xilinx core, correlator sync.
- Comparison: PRBS15 class matches (I only; a 1-bit LFSR is generic). Image lacks conv encoder, 192-bit (or any) interleaver, preamble table (N). Channel-coding class projects are not the image's structure.
- Not re-fetched this session (from memory, prior sessions' table): WARP OFDM reference and Airblue target Xilinx and 802.11; gr-ieee802-16 is a GNU Radio software reference. Not comparable at netlist level (U).
- Settling test: none distinguishes; the shared piece is the standard randomiser. A copy would need identical module structure (e.g. 15-FF LFSR with additive-whitening tap shape) in a design with the same other blocks; none present.

### 4. Open soft CPUs as the control structure
- Candidates and program-store geometry: PicoBlaze KCPSM3/6 and Altera ports (18 x up to 1024/4096, 10/12-bit PC, 16 x 8 register file, 31-deep stack), Mico8 (18 x 1024), J1 (16-bit, 8k), ZPU (8-bit), PIC12-class (12-bit), Nios II/e (32-bit), OpenRISC mor1kx, 8051/6502/AVR cores (separate program memory or RAM-shared), PicoRV32 (32-bit). Licences range BSD/MIT (J1, PicoRV32, mor1kx LGPL-style) to Xilinx-restricted (PicoBlaze source); not individually re-verified this session.
- Comparison: only 18-bit/512 (7_85 and the other 18-bit tables) and the 12-bit pair (94_57/94_58) are code-shaped; 7_85 fails a KCPSM3/Mico8 register-field test (above, N, I-grade). Operand patterns ("repeated count-down operands") read like a schedule, not a program. No detector in `patterns.py` looks for a processor datapath (PC counter + stack + register file + ALU flag FFs), and the SPI engine trace found the engine MCU-driven with no M9K script (comment 6523400968): the M9K microcode may be a data-path sequencer, not a CPU (U).
- Settling test: (a) feed the sequencer agent's word streams to a KCPSM3 / Mico8 / PIC12 opcode-table decoder and score the valid-opcode share against random words of the same width; (b) search the netlist for a 10-bit PC with load/increment, a 31-entry stack RAM and a 16x8 register file adjacent to the ROM output.

### 5. Altera DSP IP as table sources (NCO, CIC, FIR compiler)
- Signature: NCO large-ROM = two ROMs 2^k x W (sin, cos); small-ROM 512 x 11; CIC = delay RAMs only; FIR Compiler II = coefficient ROM (dspba backend not generable here).
- Comparison: the populated tables do not look like NCO sin/cos (a 512x18 monotone phase-like ramp, 2.82 wraps of 2^18, is not a sine) (N). 36_64's two 100-word linear ramps and 36_82's decaying curves have no counterpart in Altera IP generation outputs (U). FIR coefficients: no symmetric-coefficient table test has been run (U; test = symmetry and sinc/raised-cosine shape on the 18-bit tables).

### 6. Other vendors' modems (Leadcore, Beceem/Sequans-class WiMAX SoCs)
- Leadcore LC1860 (LTE, CEVA DSP) is the OcuSync lineage, not Lightbridge (fpvwiki). Published WiMAX SoC references describe the standard chain (scrambler, RS, conv, interleaver) that the image does not contain (N). No public PRBS11-pilot + PRBS15-randomiser reference design found beyond the standard text.
- Chinese academic: Xidian University master's thesis 2019 "wireless image transmission MIMO-OFDM modulator and Turbo decoder FPGA implementation" (title and table of contents only; TS framing, rate adaptation, Turbo FEC). Not tied to DJI; no content read. It raises the point that this class of video-link PHY may use Turbo/LDPC, which no detector here tests (U).

### 7. DJI / Artosyn patents, job postings, FCC photos
- Searched: Justia DJI assignee list (results page only, not opened), Google Patents hits CN115276938A / CN101610234B / CN102638435B / CN104125184B (titles only, pilot-transmission methods by other assignees; not read, not linked to DJI). No PHY patent with PRBS/preamble numerology confirmed. FCC ID SS3-WM3231503 exhibits are images; not read. Job postings: not searched. Gap, not a negative.

## Disagreements and limits
- o-gs wiki says the air FPGA is a Cyclone V; our image is a Cyclone IV GX ground-side bitstream (m2001). "Exactly matches" is the wiki's claim and is not independently supported.
- Chinese-language sources (EE-China, Sohu) are secondary company statements; the 2013 date is the company's.
- Blocked or empty: docs.altera.com pages render empty (JS); IEEE contribution S80216d-04_37r1 returned nothing via fetch (not retried via pdf); Basak thesis 403 (earlier); search-engine results are DuckDuckGo only.
- Hosts: this session `gh search repos|code` and DuckDuckGo via playwrong; GitLab, Codeberg, sr.ht, SourceForge, OpenCores, grep.app were covered earlier (`docs/signature-cores.md`, `docs/altera/cycloneIV/cycloneiv-prior-art.md`) and not re-run.
- Local third-party PDFs fetched for reading are under `tmp/prior_art/` (gitignored); nothing else saved to the repo.

## Ranked, with the test that settles each
1. DJI/Artosyn in-house PHY (I): AR8001 register map or ROM/bitstream-mirror evidence vs FPGA registers.
2. IEEE 802.16 / DVB standard conformance of the scrambler (V, not copying): nothing further needed.
3. Altera FFT MegaCore based OFDMA engine (I, negative): FFT identification in the image; twiddle in logic.
4. Unknown soft CPU (U): opcode-table decode of sequencer words + datapath search (PC, stack, register file).
5. Open WiMAX channel-coding projects (N): no matching blocks.
6. Altera NCO/CIC/FIR IP tables (N/U): FIR symmetry test on the 18-bit tables.
7. Turbo/LDPC FEC in a third-party video-link style (U): add an RSC/Turbo shape detector to `patterns.py`.
