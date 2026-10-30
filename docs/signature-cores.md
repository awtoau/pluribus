# Known-design signature cores (Cyclone IV GX EP4CGX150, #165)

Goal: structural signatures of comms blocks (scrambler, RS, conv/Viterbi, interleaver, FFT, CRC, framing) recognised in OUR decode of a bitstream.
Specimens: `tmp/sig/<name>/` (gitignored; third-party source never committed). Scripts: `scripts/cycloneiv_clean_sig_setup.py` (assemble), `scripts/cycloneiv_clean_sig_build.py` (Quartus map/fit/asm/cpf), `scripts/cycloneiv_clean_sig_extract.py` (signatures). Signature table: `reference/signatures.tsv`.
Measured 2026-10-30, Quartus Prime 25.1 SC Lite, EP4CGX150DF31C7.

## 1. Licence test (Quartus Lite IP)
- Generation: `quartus/sopc_builder/bin/ip-generate --component-name=<ip> ... --file-set=QUARTUS_SYNTH --report-file=qip:...` (qsys-generate shim notice suppressed with `--remove-qsys-generate-warning`). Output is plain, unencrypted VHDL / SystemVerilog.
- `altera_fft_ii` (Variable Streaming, fixed point, 64-pt, 16-bit, radix-2^2 SDF): generates, `quartus_map` / `quartus_fit` succeed (4,918 LE, 4,025 FF, 10 M9K, 24 mult9, 105 pins).
- `quartus_asm` (info 115017): "Design contains a time-limited core -- only a single, time-limited programming file can be generated"; writes `build_time_limited.sof` (4.9 MB) and NO `build.sof`; warning 210042 "Can't convert time-limited SOF into POF, HEX File, TTF, or RBF"; `quartus_cpf` on the time-limited `.sof` fails. Result: **no .rbf; only an OpenCore Plus time-limited .sof** (the SOF payload layout differs from the .rbf plane, not decodable by our reader).
- Same result for every licensed DSP core that generated: `altera_nco_ii`, `altera_cic_ii`, `altera_rs_ii`, `altera_bch`, `altera_vit_ii` (Viterbi II; generated via `--component-file=.../top_hw/altera_viterbi_ii_hw.tcl`) -> fit OK, time-limited .sof only.
- Not licence-gated: `altera_mult_add` (hard multiplier wrapper): full `.sof` and `.rbf`.
- Generation failures (not licence): `altera_fir_compiler_ii` (dspba backend binary needs `libnsl.so.1`, missing on this host), `altera_CORDIC` (HDL generation error with default parameters).
- `quartus/common/misc/outdated_ip/*.odip` for reed_solomon, viterbi, fft are upgrade placeholders only; the current cores are `rs_ii`, `altera_vit_ii`, `altera_fft_ii`.
- Catalogue `ip/altera/dsp/`: altera_bch, altera_cic_ii, altera_CORDIC, altera_fft_ii, altera_fir_compiler_ii, altera_fp_acc_custom, altera_fp_functions, altera_fp_matrix_inv, altera_fp_matrix_mult, altera_fpdsp_block, altera_fxp_functions, altera_nco_ii, altera_vit_ii; plus `ip/altera/rs_ii`, `altera_mult_add`. Other `ip/altera/*` are interface / system IP (PLL, LVDS, UART, PCIe, XCVR, memory controllers); not exercised. fp_* / fpdsp need Arria 10 / Stratix 10 hard-FP blocks (not tried).
- `quartus_eda` (post-fit .vo) on any licensed core: refused, error 204012 "Can't generate netlist output files ... OpenCore Plus time-limited file" (checked on altera_nco_ii, altera_cic_ii). Not worked around. No netlist-level (state-map / polynomial) signature exists for these cores.
- Consequence: Altera DSP IP is usable as a Quartus-side oracle only, at map/fit report level (section 4); it cannot be a decode specimen for our .rbf pipeline.

## 2. Open-source candidates
Reuse rules: read and cite; build and run as external oracle is fine; no GPL/restricted code copied into our tree. Licences read from the repo (GitHub) or the OpenCores overview page (OpenCores entries not verified against a LICENSE file).
`B` = built here (tmp/sig, untracked), `-` = not downloaded.

| id | block | URL | licence | lang | ~lines | synth | B |
|---|---|---|---|---|---|---|---|
| fec_rs | RS enc+dec, parametric (255,239 via n=255 check=16) | github.com/dshekhalev/FEC rtl/rs | MIT | SV | 3200 | yes | B (rs255_enc, rs255_dec) |
| fec_viterbi | Viterbi K=7 171/133 + encoder | github.com/dshekhalev/FEC rtl/viterbi/vit_1byN | MIT | SV | 3100 | yes | B (viterbi_k7) |
| fec_convenc | conv encoder K=7 171/133 | same repo | MIT | SV | 380 | yes | B (conv_k7) |
| wimax_prbs | 802.16 PRBS x^15+x^14+1 | github.com/OmarElayat/Channel-Coding-QPSK-For-WiMAX-system | MIT | VHDL | 33 | yes | B |
| wimax_interleaver | 192-bit block interleaver (sipo/perm/piso) | same repo | MIT | VHDL | 190 | yes | B (interleaver_wimax) |
| scr_80211b | 802.11 scrambler x^7+x^4+1 | github.com/travisgoodspeed/80211scrambler | none stated | Verilog | 200 | yes | B (reference only) |
| scr_xband | 20-bit scrambler + K=7 conv enc (CCSDS style) | github.com/moamenibrahim/X-band-Transmitter-Baseband-DSP-Module | MIT | VHDL | 200 | yes | B |
| fft_r22sdf | 64-pt R2^2 SDF FFT | github.com/nanamake/r22sdf | MIT | Verilog | 770 | yes | B (fft64_r22sdf) |
| fft_dit | radix-2 DIT FFT | github.com/benreynwar/fft-dit-fpga | MIT | Verilog | 760 | needs generated twiddle module (py2 + jinja) | not built |
| crc_lfsr | generic LFSR / CRC / PRBS (any poly, width) | github.com/alexforencich/verilog-ethernet rtl/lfsr.v | MIT | Verilog | 450 | yes | B (prbs15, crc32, crc8 wrappers) |
| uart_af | UART tx/rx | github.com/alexforencich/verilog-uart | MIT | Verilog | 370 | yes | B (uart) |
| rs_vhdl_cc0 | RS(255,239) enc/dec (Berlekamp, Chien, Forney) | github.com/f-crivellaro/rs_code | CC0-1.0 | VHDL | 3500 | yes | - (multi-library mapping) |
| rs_vhdl_htm | RS(1023,1019)->RS(520,512) hybrid | github.com/htminuslab/RS_CODEC | MIT | VHDL | 1060 | yes | - |
| crc32_uw | CRC32 (stub core) | github.com/UW-ASIC/Ethernet-CRC32 | Apache-2.0 | Verilog | 49 | `CRC_core` is an empty module | - |
| cordic_zip | pipelined CORDIC | github.com/ZipCPU/cordic | LGPL-3.0 (headers only) | Verilog | 870 | yes | - |
| intlv_icvdelt | generic block interleaver | github.com/icvdelt/block_interleaver | GPL-3.0 | VHDL | 2470 | yes | - (reference only) |
| zipcpu_dblclockfft | FFT generator | github.com/ZipCPU/dblclockfft | LGPL (headers) | Verilog | 5000+ | yes | - |
| hukenovs_intfftk | FFT | github.com/hukenovs/intfftk | GPL-3.0 | VHDL | - | yes | - |
| lcrypto_fec | RS (older Verilog of dshekhalev code) | github.com/Lcrypto/FEC-Archive-Verilog | none stated | Verilog | 3000 | yes | - |
| freecores_rs_dec | RS decoder | github.com/freecores/reed_solomon_decoder | none stated | Verilog | 2000 | yes | - |
| redflag_rs | RS enc+dec | github.com/RedFlag2017/rs-codec | none stated | Verilog | big | yes | - |
| mmdems_rs | RS(255,239) dec | github.com/mmdems/rs_255_239 | none stated | VHDL | 600 | yes | - |
| jfoshea_viterbi | Viterbi variants | github.com/jfoshea/Viterbi-Decoder-in-Verilog | none stated | Verilog | 3000 | yes | - |
| freecores_viterb | Viterbi enc+dec | github.com/freecores/viterb_encoder_and_decoder | none stated | Verilog | 600 | yes | - |
| madellimac_viterbi | Viterbi | github.com/madellimac/viterbi | MIT | VHDL | - | yes | - |
| asultan_wimax_cc | WiMAX encoder / interleaver / prbs | github.com/asultan123/WiMax_Channel_Coding | none stated | VHDL | - | yes | - |
| bishoy8599_wimax_phy | WiMAX PHY (near-duplicate of OmarElayat) | github.com/bishoy8599/WiMax_PHY | MIT | VHDL | - | yes | - |
| codyps_wimax_ofdm | 802.16 OFDM partial | github.com/codyps/wimax_ofdm | none stated | Verilog | small | no (unfinished) | - |
| jhshi_openofdm | 802.11 OFDM RX (Viterbi, FFT, deinterleaver) | github.com/jhshi/openofdm | none checked | Verilog | - | yes | - |
| smariel_dvbt | DVB-T | github.com/smariel/CodageDVBT | none stated | VHDL | - | unknown | - |
| chemeris_wimax_scanner | WiMAX preamble scanner | github.com/chemeris/wimax-scanner | none stated | VHDL | - | unknown | - |
| pconst_basic_verilog | CRC / LFSR / UART / FIFO collection | github.com/pConst/basic_verilog | none stated | SV | - | yes | - |
| jakubcabal_uart | UART | github.com/jakubcabal/uart-for-fpga | MIT | VHDL | - | yes | - |
| oc_vhcg | Viterbi generator (K=7 133/171 example) | opencores.org/projects/vhcg (mirror sourceforge.net/projects/viterbi-gen) | GPL generator; generated Verilog unrestricted per page | Perl/C -> Verilog | - | yes | - |
| oc_rs_gen | RS codec generator (3-11 bit symbols) | opencores.org/projects/reed_solomon_codec_generator | LGPL / GPL (page conflicts) | Verilog | - | yes | - |
| oc_rs_dec_enc | RS 8-bit, t=2 only | opencores.org/projects/rs_dec_enc | LGPL | VHDL | - | yes | - |
| oc_bluespec_rs | RS n=255 t=16 | opencores.org/projects/bluespec-reedsolomon | LGPL | Bluespec | - | via bsc | - |
| oc_fft64 | 64-pt radix-8 FFT | opencores.org/projects/pipelined_fft_64 | LGPL | Verilog | - | yes | - |
| oc_dblclockfft | FFT generator | opencores.org/projects/dblclockfft | GPL | Verilog | - | yes | - |
| oc_cordic | CORDIC | opencores.org/projects/cordic ; verilog_cordic_core | GPL ; none stated | VHDL ; Verilog | - | yes | - |
| oc_parallelcrcgen | CRC generator (any poly, up to 1024 bit) | opencores.org/projects/parallelcrcgen | LGPL | C -> Verilog / VHDL | - | yes | - |
| oc_bluespec_80211a | 802.11a TX baseband (scrambler, conv enc, interleaver, IFFT) | opencores.org/projects/bluespec-80211atransmitter | LGPL | Bluespec | - | via bsc | - |
| oc_ofdm | OFDM modem | opencores.org/projects/ofdm | none stated | VHDL | - | probably, author notes a bug | - |
| oc_viterbi_k7 | K=7 133/171 R=1/2 | opencores.org/projects/viterbi_decoder_k_7_r_1_2 | none stated | - | no code checked in | no | - |

Coverage and gaps
- Hosts searched: GitHub (gh), OpenCores, GitLab (API), Codeberg (API), sr.ht, SourceForge; Bitbucket needs login; grep.app and `gh search code` were not usable (rate limit / no results).
- GitLab / Codeberg / sr.ht returned no usable HDL for these blocks.
- No open DVB-T or 802.11a OFDM PHY with permissive licence found; WiMAX material is channel-coding class projects (MIT) and an unfinished stub.
- No licensed PN / preamble correlator core found; no standalone permissive 802.16 interleaver beyond `wimax_interleaver`.

## 3. Built specimens and recovered signatures
Per-specimen build + extraction results: see `reference/signatures.tsv` (columns: name, block type, source, structural features, resources, recovered, notes). Recognisers (`scripts/cycloneiv_clean_sig_extract.py`):
- Linear state machine: SCC of the FF graph, D cones evaluated exactly as truth tables, external inputs searched (coordinate ascent) for the assignment that makes every cone GF(2)-affine; state map A over GF(2); minimal polynomial of A (basis-independent) vs catalogue: LFSR / CRC polynomials from the public standards (either orientation; k and 2^j*k bits/clock share a minimal polynomial so bits/clock is not determined by it) and the RS generator-polynomial LFSR expanded to GF(2) from first principles (GF(2^8) poly 0x11D, 16 roots a^0..a^15).
- Convolutional encoder: shift chain (FF D = single other FF under a gating assignment) plus affine tap cones over the chain; tap sets vs the K=7 171/133 delay sets (live-input delay 0 is gated separately in registered designs and is excluded from the comparison).
- ROM content: M9K content decoded with `m9k.read_words`, non-zero window tested against sampled cos/sin (full / half / quarter wave).
- Counts: LUT / carry LUT / FF / M9K / MAC / pads, plus the rtl lift counts (adders, comparators, FSMs, XOR cones, shift registers).

### Results (2026-10-30; 15 decodable specimens, 6 Altera IP not decodable)
- Recovered (signature matched from our decode): PRBS15 802.16 (2 builds), PRBS7 802.11 scrambler, PRBS20 scrambler, CRC32, CRC8, RS(255,239) encoder (128-FF GF(2) state map, minimal polynomial equal to the generator LFSR), RS(255,239) decoder (minimal polynomials of a^0..a^15 present among 8-FF linear SCCs; necessary condition, Chien/Forney registers also match), K=7 171/133 convolutional encoder (two tap sets on a 6-FF chain), cosine ROM table in M9K (peak 32000, 256 words), hard multiplier.
- Partial (structure present, no polynomial/ordering test): Viterbi K=7 (14 SCCs of 64 FFs = 2^(K-1) states, non-linear ACS, 9 x 8-bit adders), 192-bit interleaver (192-FF shift chain + 192 mux2), 64-pt FFT (8 MAC = 16 mult9, 4 M9K delay lines; twiddles are LUT logic), UART (FSM, 17-bit baud adder).
- Not recovered / limits: bits per clock of an LFSR is determined only up to 2^j (shared minimal polynomial); the Viterbi 171/133 polynomials are not tested (branch-metric XOR structure not analysed); M9K width/mode is not modelled for TDP/32-bit blocks (content still decodes through `m9k.read_words`).
- `fft_dit` not built (needs generated twiddle module); `rs_vhdl_cc0` not built.

## 4. Licensed Altera DSP cores: report-level signatures (2026-10-30)
Source: `quartus_map` + `quartus_fit` only (`scripts/cycloneiv_clean_sig_ipgen.py` generates, `..._sig_netlist.py` builds, `..._sig_reports.py` parses `map.rpt` hierarchy + RAM summary, rows into `reference/signatures.tsv` via `..._sig_tsv.py`). Generated HDL, reports and netlists stay in `tmp/sig/` (gitignored). No bitstream, no netlist, no licence handling.
- Every time-limited design carries a fixed OpenCore Plus overhead (Signal Tap hub + obfuscated timer wrapper): 242 LE(comb) + 148 FF in the fit totals. Counts below are net of it; M9K / mult9 unaffected.
- Not obtainable: polynomial / state-map recovery (needs a netlist). Generator polynomials in RS / BCH / Viterbi are generation parameters here, not recovered.
- Table: LE = combinational functions, FF = dedicated registers, M9K = blocks (fit), mult9 = 9-bit embedded multiplier elements (1 mult18 = 2).

| config | parameters | LE | FF | M9K | mem bits | mult9 |
|---|---|---|---|---|---|---|
| fft_vs256_12 | 256-pt, 12-bit, variable streaming | 5079 | 4510 | 14 | 10152 | 32 |
| fft_vs256_16 | 256-pt, 16-bit, variable streaming | 6023 | 5665 | 16 | 13024 | 40 |
| altera_fft64 | 64-pt, 16-bit, variable streaming | 4208 | 3919 | 10 | 4012 | 24 |
| fft_st64_16 | 64-pt, 16-bit, streaming (block FP) | 3412 | 3487 | 24 | 10186 | 24 |
| fft_bb64_16 | 64-pt, 16-bit, buffered burst (block FP) | 3124 | 3369 | 20 | 8138 | 24 |
| fft_b64_16 | 64-pt, 16-bit, burst (block FP) | 3111 | 3309 | 12 | 4042 | 24 |
| ip_nco | large ROM, 32-bit acc, 16-bit ROM addr, 18-bit out, dither | 345 | 178 | 288 | 2359296 | 0 |
| nco_large_nodither | large ROM, 24-bit acc, 12-bit addr, 12-bit out, no dither | 91 | 88 | 12 | 98304 | 0 |
| nco_small_rom | small ROM, 24-bit acc, 12-bit addr, 12-bit out | 308 | 237 | 2 | 11264 | 0 |
| nco_cordic | CORDIC, 24-bit acc, 12-bit out | 1282 | 1249 | 0 | 0 | 0 |
| ip_cic | interpolator, 12 stages, in 8 | 1185 | 1463 | 3 | 1376 | 0 |
| cic_dec_s3_r8 | decimator, 3 stages, R=8, in 16 | 341 | 311 | 3 | 1028 | 0 |
| cic_dec_s5_r16 | decimator, 5 stages, R=16, in 16 | 574 | 630 | 3 | 1424 | 0 |
| cic_int_s4_r8 | interpolator, 4 stages, R=8, in 12 | 354 | 301 | 2 | 768 | 0 |
| rs_enc_204_188 (= ip_rs_ii) | RS encoder, check 16 (N=204 and N=255 give identical counts) | 212 | 156 | 0 | 0 | 0 |
| rs_dec_255_239 | RS decoder, check 16 | 2245 | 970 | 1 | 5120 | 0 |
| rs_dec_204_188 | RS decoder, N=204, check 16 | 2285 | 970 | 1 | 5120 | 0 |
| bch_enc_255_239 | BCH encoder m=8 t=2 | 283 | 215 | 2 | 1536 | 0 |
| bch_enc_255_191 | BCH encoder m=8 t=8 | 359 | 303 | 2 | 1536 | 0 |
| bch_dec_255_191 | BCH decoder m=8 t=8 | 2913 | 2136 | 13 | 6144 | 0 |
| ip_bch | BCH encoder m=14 t=40 (N=8784) | 2029 | 1354 | 6 | 32828 | 0 |
| vit_k7_hard | Viterbi K=7 171/133, 1 soft bit (hard), parallel | 3374 | 1472 | 7 | 34816 | 0 |
| vit_k7_soft3 | Viterbi K=7 171/133, 3 soft bits, parallel | 4112 | 1752 | 7 | 34816 | 0 |
| vit_k7_hybrid | Viterbi K=7 171/133, 3 soft bits, hybrid, 4 ACS units | 1270 | 833 | 6 | 5056 | 0 |
| ip_vit | Viterbi K=3, n=4, parallel (defaults) | 911 | 535 | 5 | 3072 | 0 |

Structure visible in the report hierarchy (counts):
- FFT, variable streaming: 24-32 registered adders (widths 13-50 bit), mult9 = 8 mult megafunctions (2 mult9 each) + 2-4 mult-add (4 mult9 each) at 64-pt, 16 mult + 2 mult-add at 256-pt 16-bit; ROM 17/5 words (64-pt) or 17/5/65 words (256-pt) x data width = twiddle ROMs (2 each); 6-10 simple-dual-port delay RAMs.
- FFT, streaming / burst / buffered burst (64-pt): 16 registered adders (10 x 19-bit, 6 x 33-bit), 6 mult-add (24 mult9), 4 shift-taps, 6 ROMs 16 x 16; delay RAM 16 x 32 repeated 16x (streaming), 12x (buffered burst), 4x (burst) is the only M9K-count differentiator (24 / 20 / 12 blocks).
- NCO: one registered adder = phase accumulator width (32 / 24), 1 counter (3-5 FF), 2 ROMs (sin, cos) each 2^addr x out width (65536x18, 4096x12, 512x11 small-ROM); CORDIC variant: 34 adders (20 x 12-bit, 10 x 16-bit), no ROM, no multiplier.
- CIC: no adder megafunctions visible (integrators / combs are plain logic); 2-3 delay RAMs (32 x ~2*width, 8 x ~width) are the M9K use; FF count tracks stages x width.
- RS II encoder: pure logic, 0 RAM, 212 LE / 156 FF, independent of N. Decoder: one 512 x 10 RAM, 970 FF, ~2250 LE.
- BCH: encoder 2 RAMs (128 x 10, 32 x 10); decoder adds a 256 x 8 ROM (inverse table), 3 shift-taps, 5 more RAMs.
- Viterbi K=7: 5 RAMs (2 x 256x1, 256x6, 2 x 256x64 = path / decision memory), no multipliers; hard vs 3-bit soft changes LE (+738) and FF (+280), not RAM; hybrid with 4 ACS units uses 8 small 8x8 RAMs and 3x fewer LE.

### Match shapes against the decoded DJI image (counts only)
Image (`scripts/cycloneiv_clean_sig_image_shapes.py` on the local decode): 36,993 FF, 542 M9K, 87 MAC, 20,260 carry LUTs. Per clock domain (rank by FF): domain 1 = 23,416 FF / 349 M9K / 81 MAC / 5,771 registered carry LUTs; domain 2 = 13,046 FF, no M9K / MAC; domains 3-6 (52-218 FF) none. 193 M9K and 6 MAC have no decoded clock.
- DSP shape: all 81 clocked MACs sit in domain 1. One 64-pt FFT is 12 mult18 + 10-24 M9K; one 256-pt FFT 16-20 mult18 + 14-16 M9K. FFT-II sized engines are possible there (about 4-7 copies by MAC count) but the M9K (349) and FF (23,416) counts are far above that; MAC shape alone does not identify an FFT.
- No other core family in section 4 uses a MAC or mult9: NCO, CIC, RS, BCH, Viterbi are shape-compatible with any domain on MAC count.
- NCO large-ROM (2 ROMs, 12-288 M9K) fits inside domain 1's 349 M9K only as the 288-block default; unmodelled M9Ks (193) prevent a ROM-content test.
- Viterbi K=7 shape (5-7 M9K, 1,470-1,750 FF, 3,400-4,100 LE) and RS decoder (970 FF, 1 M9K): the image has no matched GF multiplier (`gfmul` 0); the pattern detector does not test non-affine ACS SCCs, so Viterbi is untested. No match is claimed for any core.
