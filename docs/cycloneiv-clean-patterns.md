# Cyclone IV GX clean pipeline: structural pattern detectors (#165)

Code: `lifters/cycloneiv_clean/patterns.py` (`detect(nl)`, `summary(res)`), specimens `scripts/cycloneiv_pattern_specimens.py`, scoring `scripts/cycloneiv_pattern_score.py`, tests `tests/cycloneiv_clean/test_patterns.py`.
Input is the emit `Netlist` (read-only). Generic: no image data in tracked files. Structure only: no statistics, no learned patterns. Unknown stays unknown.

## Method
- Each combinational signal gets an affine form over GF(2) (leaf mask + constant) when every LUT on its cone is affine in its inputs. Leaves: FF outputs, pads, block outputs, undecoded sources, carry-mode LUT outputs.
- Gating: a LUT of the form `G(pins) ? const : affine(x)` (1-3 gate pins, each read by >= 3 pins) or `gate ? affine(x) : hold` is read as the affine part plus a recorded gate (sync clear / set / load / enable in logic). The gate is not part of the register-group key; gate counts are reported.
- Register groups: SCC of the FF dependency graph (same clock + enable), `3 <= n <= 512`, at least one XOR. Per group: GF(2) matrix `A`, rank, characteristic polynomial (Krylov over a growing invariant subspace), shift structure (Fibonacci: all but one FF straight shifts; Galois: shifts + taps from one tail FF), primitivity (n <= 64), controls (enable, async clear, sclr/sload, gate, seed constants).
- Polynomial match: `charpoly(A)` vs `charpoly(M^w)`, `M` = companion of each known polynomial of equal degree, `w` = 1..64, both orientations. `w` and `2w` give the same polynomial (Frobenius), so the data width is read from the external-input count, not from `w`.
- Known tables (each with a `source:` line): PRBS 7/9/11/15/20/23/31, 802.16 / DVB x^15+x^14+1, 802.11 x^7+x^4+1, CCSDS, 10GBASE-R, PCIe, DVB-S2 PL; CRC-8 (802.16 HCS), CRC-5, CRC-16 (CCITT, ANSI), CRC-32, CRC-32C, CRC-24, CRC-8 DVB-S2 / J1850; GF(2^8) 0x11D / 0x11B / 0x187; convolutional K=3/5/7/9 and rate 1/3.
- Confidence: high = matched a known polynomial (n >= 7) or autonomous primitive Fibonacci/Galois (n >= 7); medium = structure only; low = rank-deficient or unmatched linear group.

## Detectors
| key | construct | evidence reported |
|---|---|---|
| `lfsr` | autonomous / serial feedback shift register | n, form, taps, rank, charpoly, known match, primitive, controls, whitening consumers (outside cones mixing group bits with other leaves) |
| `parallel` | word-parallel LFSR / CRC (external inputs on several FFs) | as `lfsr`, `w` = external input count |
| `conv` | straight chain + >= 2 XOR tap outputs | K, generators (octal), known-encoder match (either bit order) |
| `fir` | chain + feed-forward XOR of >= 3 positions (self-synchronising descrambler) | taps, span, known-polynomial match |
| `gfmul` | 8 outputs over 8 leaves, invertible GF(2) matrix | multiplication-by-constant match up to row/column relabelling (canonical form under permutations), candidates list |
| `shift` | straight FF chains >= 3, mux-loadable chains | length, clock, whether inside an LFSR |
| `syncword` | AND-of-literals cone (single satisfying assignment, sub-cones folded) over >= 8 FFs | literals, source (shift chain / counter / other), contiguity |
| `counters` | carry-chain registers with self feedback + LUT-built binary counters | width, counter / accumulator |
| `m9k_addr` / `m9k_buses` | modelled M9K address cone vs counters; M9Ks grouped by identical address bus | identity / bit permutation / rotation / function; sharing counts |
| `mac_rom` | MAC operand bits fed by M9K outputs | per-MAC M9K counts |
| `cdc` | 2-FF synchronisers (chain head fanout 1, source in another domain or a pad), cross-domain register edges, gray-coded counter registers, counter-vs-bus comparator chains | counts per domain pair |

Limits (not covered, therefore unknown):
- Non-modelled M9Ks (dual-port / 32-36 bit / undecoded widths) have no decoded address pins: no interleaver / FIFO / ROM test on them.
- GF(2^8) multiplier-accumulate (feedback `d ^ p` form, RS encoder) and non-polynomial bases are not matched; only pure 8-in 8-out multipliers.
- LFSR / CRC groups whose next state is non-affine (enable or reset muxed in a form other than gate / hold) are not seen.
- Counters: LUT-built counters need nested supports (<= 12 bits, <= 3 enable leaves); carry-chain counters need the sum LUT to read its own register.
- Hard-IP content (PLL, transceivers) is outside the netlist.

## Validation on built specimens (Quartus, `tmp/pattern_tests/`, local)
Specimens: LFSR set (Fibonacci x^15+x^14+1 with additive whitening, PRBS9, Galois x^7+x^6+1), CRC set (CRC-32 w=8, CRC-16-CCITT w=16, CRC-8 802.16 HCS w=8), K=7 171/133 encoder, x^7+x^4+1 descrambler, 3 GF(2^8) constant multipliers (2 polynomials), misc (13-bit counter + 8192x1 M9K with rotated address, 24-bit constant comparator on a shift chain, 2-FF and bus crossing), FIFO-ish (counter, gray register, 2-FF bus, pointer comparator), twiddle-ROM + MAC (M9K not modelled: no positive control for `mac_rom`).
Scores (matched / missing / extra / wrong), run `cycloneiv_pattern_score.py --specimens`:
- lfsr 3/0/0/0, lfsr whitening 1/0/0/0, crc 3/0/0/0, conv 1/0/0/0, fir 1/0/0/0, gfmul 3/0/0/0 (each candidate list contains the built constant; single candidate), sync word 1/0/0/0, shift 1/0/0/0, interleaver (bit permutation, rotation) 1/0/0/0, counters 4/0/0/0, 2-FF sync 1/0/0/0, gray 1/0/0/0, pointer compare 1/0/0/0.
- Bring-up findings: sync reset / set arrives as LUT logic (gate), not as SCLR / SLOAD; the gate can be a function of up to 3 control pins (e.g. `set = a & b & c` merged into the data LUT); enable arrives on ENA for some bits and inside LUTs for others; short counters are LUT-built; `rtl.py` carry-chain analysis rejects chains whose last LE reads its register through DATAD (counters in rtl.py: 1, here: 269 on the image).

## Controls
Negative controls: 362 corpus-keep designs without `hl_*` (random-LUT specimens, decoder tests; `scripts/cycloneiv_pattern_score.py --negatives`, 2026-10-30, 362 designs):
- lfsr 0, parallel 0, ring 0, conv 0, fir 0, gfmul 0, sync word 0, gray 0, pointer compare 0 detections (false positives: 0 / 362 designs). Straight chains >= 3: 2 chains in 2 designs.

Generator ground truth: 153 `hl_*` designs with `src/hl_truth.json` (`--hl`, 2026-10-30; truth rows: 491 LFSRs, 25 CRCs, 96+ counters, 16 equalities). Registers the fitter removed (truth `reg_bits` minus fitted `registers`) are tallied as `*_pruned`, not as misses:
- lfsr (width + feedback polynomial, either orientation) 480 matched / 1 missing / 0 extra / 0 wrong = 99.8%; 10 more absent from the fitted netlist (pruned).
- crc (width + generator + data width) 25 / 0 / 0 / 0 = 100%.
- counters (width) 57 matched / 10 missing / 42 extra / 0 wrong = 52.3%; 29 pruned. Misses: enable / load / clear / down variants outside the two counter shapes; extras: counters the generator did not list (adder / pipeline internals). Not used for claims below.
- constant compares >= 8 bits 2 / 6 / 14 / 0 = 9.1% (rule needs every literal on an FF; not used for claims).
- not in truth: 1 conv candidate (shift-register observers, no known-generator match), 1 unmatched linear group.
- Cost: whole-netlist pass on the image (89 k LUT, 37 k FF) 3 s after the netlist is built; the build itself is the existing emit step.


## Third-party image (EP4CGX150, counts only; details local in `tmp/dji_patterns/patterns.json`)
Design: 89,282 LUTs, 36,993 FFs, 6 clock domains (FF share 63.3 %, 35.3 %, then 218 / 142 / 119 / 52 FFs; below "domain 0" = largest, "domain 1" = second), 26,847 FFs (72.6 %) with an affine next state (gates allowed).

| detector | count | classes |
|---|---|---|
| LFSR (autonomous, Fibonacci form) | 7 | 11 stages x 4, 15 stages x 3; all 7 match a documented PRBS-table polynomial (either orientation) and are primitive; all in domain 0 |
| LFSR with outside XOR consumers (whitening-shaped) | 2 | the 15-stage and 11-stage members with a consumer FF mixing 1-2 state bits with one other FF |
| serial CRC-class group | 1 | 16 stages, 1 data input, matches the CRC-16-CCITT table polynomial; its data input is an 8:1-shaped select over one M9K output byte |
| other linear group | 1 | 5 stages, 4 external inputs, charpoly x^5+1 (not primitive), no table match (low) |
| word-parallel CRC / scrambler (w >= 8) | 0 | |
| convolutional encoder | 0 | |
| feed-forward XOR over a chain (self-sync descrambler shape) | 1 | 3 taps, span 16, no table match (low) |
| GF(2^8) constant multiplier (pure 8x8) | 0 | multiplier-accumulate form not covered |
| constant comparator on a straight chain | 1 | 10 literals, 1 of them set (not a framing-word shape) |
| constant comparators from counters / other | 88 / 173 | >= 8 FF literals |
| straight FF chains >= 3 / >= 8 | 317 / 32 | 29 of the 32 in domain 0 |
| mux-loadable chains >= 3 | 15 | lengths <= 4 |
| counters / accumulators | 222 / 47 | 236 in domain 0, 21 in domain 1 |
| modelled M9K / all | 349 / 542 | 24 distinct address buses; largest shared by 96, 64, 24 x 4 M9Ks (268 are 1-bit x 8192 words) |
| M9K address class (modelled) | identity 2, counter plus other 347 | no counter bit-permutation (interleaver shape) among modelled M9Ks; no write-enable-constant ROM |
| MACs with an M9K operand / on both operands | 33 / 13 of 87 | none counter-addressed ROM (not decidable on unmodelled M9Ks) |
| 2-FF synchronisers | 8 FF-sourced, 9 pad-sourced | FF-sourced: 7 domain 0 -> domain 1, 1 domain 0 -> domain 5; pad-sourced all into domain 0 |
| cross-domain affine register edges | 19 | 0 -> 1: 10, 1 -> 0: 8, 0 -> 5: 1 |
| gray-coded counter registers | 5 | |
| counter-vs-bus comparator chains | 61 | 55 same domain |

Evidence reading (hypotheses are labelled):
- Fact: of the 9 linear groups, none reaches a pad downstream within 10 register stages; upstream only the CRC-16 group does (its data select depends on 1 pad, plus 5 M9Ks); the 5-stage group is fed by 21 M9K output bits; 4 of the 7 LFSRs have no pad or M9K upstream, 3 read 2 M9K outputs. No CRC-32, no CRC-8 (802.16 HCS), no RS multiplier, no convolutional encoder was found. The three 15-stage LFSRs match the 802.16 / DVB randomiser polynomial class, which is also the PRBS15 test-pattern polynomial: the match alone does not separate whitening from test-pattern use.
- Hypothesis H1: the 7 autonomous PRBS-class LFSRs are on-chip test-pattern / noise sources or LFSR timers inside the main processing domain (all state bits are read by non-linear logic, 11-18 readers each; 5 reach M9K inputs, 2 reach MACs within 10 stages), not link whitening.
- Hypothesis H2: the CRC-16 group checks a byte stream read from M9K (integrity of stored data / packets), not an over-the-air header check.
- Hypothesis H3: the second domain (13,046 FFs, 21 counters, 0 linear groups) is a datapath, consistent with the wide 1-bit M9K banks and the MAC fabric rather than FEC.
- Not decidable from this netlist: anything in unmodelled M9Ks (193), hard IP, multiplier-accumulate GF(2^8) forms, non-affine LFSR variants (enable or reset muxed outside gate / hold).
- Pin / bank context (local pin drafts read only): the only detections touching IO are the 9 pad-fed 2/3-FF chains and the CRC-16 data select (1 pad).

