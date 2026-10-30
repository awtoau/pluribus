# Lightbridge OFDM: reconciliation with the existing analysis (#165)

- Existing: `awto-dji/docs/lightbridge-phy-measured.md` (awto-dji#71), read-only.
- Ours: `scripts/lightbridge_ofdm_demod.py`, `lightbridge_numerology_fit.py`, `lightbridge_ofdm_population.py`, `lightbridge_ofdm_precoder_test.py`, `lightbridge_population_report.py`; data in `tmp/ofdm/`, `tmp/ofdm_pop/` (local; `report.txt`, `table.tsv`, `*.jsonl`).
- Tags: V measured, I inferred, U unknown. Counts and parameters only.
- Independence: the numerology fit (`num`) imports the existing awto-dji measurement functions, so its agreement is a reproduction on more files, not an independent method. The demod (`pop`) is independent code that assumes the numerology and checks it (CP correlation, carrier-edge error, pilot-class agreement).

## Sets

| set | files | bursts |
|---|---|---|
| Zenodo 2.4 GHz (M100, Inspire 2, M210, P4, P4P+, Mavic Pro, Mavic Mini) | 7 | numerology 36 fitted (6 files); demod 54 |
| Zenodo 5.8 GHz (Inspire 2, M210, P4P+; 1of2 + 2of2) | 6 | numerology 36 fitted; demod 12 (1of2 files) |
| GENESYS M100 (7 UAVs x 4 distances, 27 cells) | 27 | numerology 27; demod 27 |
| KU Leuven: inspire2Vid (10 files), matricevid, MavicVid1, MavicVid2 (numerology only), mini2vid (2 files) | 14 | numerology 8 files; demod 30 Inspire 2 + 5 others |

Column "behind ours": `num` = `num_*.jsonl` (6 wide bursts per file), `pop` = `pop_*.jsonl`, `zg`/`ku` = `tmp/ofdm/results_zg.json` (17 bursts) / `results_ku.json` (2), `prec` = `precoder_*.json`, `ramp` = `ramp.jsonl`.

## A. Reconciliation table

### Matrice 100, 2.4 GHz

| claim (tag) | existing | ours | verdict | behind ours |
|---|---|---|---|---|
| subcarrier spacing (V) | 10937.50 Hz, std 0.04, 20 bursts | 10937.48, std 0.03 | match (-0.02 Hz) | num: 1 file, 6 bursts; pop: 19 bursts lock to the 11.2 MS/s / 1024 grid (CP corr 1.00) |
| CP (V) | 1/8 Tu; fold plateau 1369-1372 | 0.12503 | match; plateau not separately tested | num: 6 |
| symbol time (V) | 102.859 us | 102.86 us | match | num: 6 |
| used carriers, DC null (V) | 864, k = -432..+432, DC -12 to -13 dB, 20 bursts | 864; DC -12.6 dB | match | num: 6; pop: 19 |
| guard bins (V) | 80 low, 79 high | carrier-edge error 0 bins in 115/115 gated bursts (grid 80..944 assumed) | match | pop: 115 |
| pilots 96/symbol, one per 9 (V) | residue 5,5,8,8,2,2, period 6, each held 2 symbols | same; class agreement 100% in 18/19 M100 bursts (1 at 98.9%) | match | pop: 19; zg: 17 |
| pilot power boost (V) | none (+0.5 dB) | not tested (pilots are two-level, see B) | not tested | - |
| pilot BPSK^2 coherence (V) | 0.87-0.92 vs 0.13-0.20 off-pilot | square-fit metric 0.99-1.00 per pilot parity set | different metric, consistent | prec: 3 bursts |
| first symbols, 1/3 per k mod 3, no 802.16e preamble (V) | ~1/3 each | sym 0 share 0.33/0.33/0.34 | match | zg: 17 |
| video burst (V) | 9.98 ms, ~97 symbols, +16.5 MHz | 9.98 ms; 95 OFDM symbols (18 bursts) or 88 (1), plus 5 lead windows; +16.49 MHz | match on ms and MHz; symbol count differs by 2 (we count OFDM symbols after the lead-in) | num: 6; pop: 19 |
| frame (V) | 14.000 ms start-to-start | 14.000 ms median | match | num: 20 wide bursts |
| lead-in CW 0.16 ms (V) | 0.16 ms | 5 lead windows incl. 0.4 ms pad = ~1 symbol (0.1 ms) non-OFDM | consistent, not separately measured | pop: 19 |
| second link (V) | 2.2 ms, ~1.4 MHz, new centre per frame, 2 MHz grid +-36, 1 ms CW first | 20 narrow bursts, median 2.18 ms, 1.41 MHz, 20 distinct centres | match on duration, width, hopping; grid step and CW lead not tested | num: 20 |
| second-link df / CP (V/U) | 10938-10944 Hz; CP 0.13-0.14, weak | narrowband pass not run | not tested | - |
| 864/768/96 split, 802.16e AMC layout (I) | layout match | 768 data + 96 pilots per symbol used throughout | consistent; no new test of AMC detail | pop |

### GENESYS M100 (2.4 GHz, 10 MS/s)

| claim | existing | ours | verdict | behind ours |
|---|---|---|---|---|
| df (V) | 10939.32 Hz, std 0.11, 14 bursts | median 10939.2 (10938.9-10939.5) | match (-0.1 Hz) | num: 27 files |
| CP (V) | 0.1253 | 0.1252 | match | num: 27 |
| Tsym (V) | 102.87 us | follows from df, CP | match | num: 27 |
| bandwidth 9.47 MHz (V) | spectrogram -20 dB | not measured (fixed window) | not tested | - |
| occupied bins 923 (U, edge artifact) | not a carrier count | 924 on the 1024 grid; the 864 grid fits with edge error 0 in 27/27 | match; edge-artifact reading supported | pop: 27 |
| burst length (V) | up to 9.78 ms | 92-94 OFDM symbols = 9.5-9.7 ms, 0 lead | consistent | pop: 27 |
| first symbols 1/3 per k mod 3 (V) | yes | yes | match | zg: 10 |
| constellation/pilot search unreliable (U) | ratio 6-12 | single-channel k4 1.11-1.73; 5/27 bursts fail the pilot-class gate (agreement 0.34-0.89) | differs: usable on 22/27 | pop: 27 |

### KU Leuven, 2.44 GHz fixed

| claim | existing | ours | verdict | behind ours |
|---|---|---|---|---|
| Inspire 2 df (V) | 10937.56 Hz, n=15 | 10937.6 | match | num: 2 files; pop: 30 bursts, 10 files |
| CP, Tsym, bins (V) | 0.1249; 102.85; 866 | 0.1249; 102.85; 866 | match | num: 2 files |
| video burst, frame (V) | 9.76-9.78 ms; 14.000 ms | 9.76 ms; 14.000 ms | match | num: 2 files |
| centre -33.5 MHz (I) | 2406.5 MHz | -33.50 MHz | match | pop: 30 |
| second link on Inspire 2 RC (V) | 7 bursts, 2.2 ms, 1.27-1.37 MHz | RC file not run; video files show 0 narrow bursts | not tested (consistent for video) | num: 2 |
| Matrice (V) | 15000.25 Hz, 0.0717, 71.44 us, 1024, 18.07 MHz | 15000.0 / 15000.6, 0.0715-0.0716, 71.43-71.44, 1024, 18.07 | match | num: 2 files |
| Mavic (V) | 15000.12 Hz, 0.0713, 71.42, 1024, 18.16 | 15000.0 / 15000.1, 0.0714, 71.42, 1024, 18.16 | match | num: 2 archives |
| Matrice/Mavic RC too short (U) | inconclusive | not run | not tested | - |
| Mini 2 hopping, no wide burst (V) | 43-84 narrow bursts, 0.1-1.1 ms | 0 wide; 40 narrow, median 0.5 ms, 27 centres | match | num: 2 files |
| Matrice variant = newer platform (I) | | numerology identical to Mavic | consistent | - |

### Fleet table (Zenodo)

| row | existing | ours | verdict | behind ours |
|---|---|---|---|---|
| Phantom 4 2G | 10937.44, 1/8, 866, no null, 9.78 ms, 14 ms | 10937.4, 0.125, 866, DC +2.0 dB, 9.78, 14.0 | match | num: 20 wide, 6 fitted |
| P4P+ 2G / 5.8G | 10937.41 / .52, 866 / 865, no null | 10937.5 / 10937.4, 866 / 865, DC -0.2..+3.1 dB | match | num: 3 files |
| Inspire 2 2G / 5.8G | 10937.53 / .45, 865, no null, 10.2 ms | 10937.5, 865, DC -6.3 dB (2G), -3.5..-3.8 (5G), 10.2 ms | match; the 2G DC dip is larger than other non-M100 files | num: 3 files |
| M210 2G / 5.8G | 10937.34 / .32, 866, no null | 10937.4 / 10937.3, 866, DC -1.5 / -3.8..-4.2 | match | num: 3 files |
| Mavic Pro 2G | 15000.0, 1/14, 71.43, ~18 MHz, ~5 ms bursts | 14999.7, 0.0716, 71.44, 18.16 MHz, 4.1 ms bursts, 6.0 ms period | numerology match; burst length 4.1 vs ~5 ms differs | num: 45 wide, 6 fitted |
| Mavic Mini 2G | 4.3 MHz, 0.2 ms bursts, not OFDM-measured | no wide or narrow burst passes our thresholds | not tested | num: 1 file |
| "only M100 has the 9-carrier pilot grid" (V) | other models: no | class pattern 5,5,8,8,2,2 agrees > 0.9 in all 115 gated bursts incl. P4 (8), P4P+ (12), Inspire 2 (42), M210 (12), GENESYS (22) | **differs**: every group-A device has it | pop: 115 |
| "only M100 has the DC null" (V) | yes | M100 -12.6 dB; all other group-A Zenodo/KU files -6.3 .. +3.1 dB | match | num: 13 files |
| "P3 expected to match M100 generation" (I) | | all 40 group-A files share carrier map and pilot pattern; DC null differs per model | consistent | - |

### Other claims

| claim | existing | ours | verdict |
|---|---|---|---|
| 1024 FFT, 11.2 MS/s, 802.16e 10 MHz numerology (V) | exact | 11.2 MS/s grid locks, CP corr 1.00 in 115 bursts | match |
| 14 ms frame, no preamble, CW lead-in (V) | | frame 14.0 ms, no 1-in-3 preamble, lead-in consistent | match |
| P3 AD9363 11.2 MS/s, ~10 MHz (I) | consistent | MCU register decode: 11.2 MS/s chain, 10 MHz RF filter downlink, both RX on both ends, 2 TX on air, ground TX2 in the last state, 1.25 MHz RF uplink filter | register values V; Fref 40 MHz stays I |
| P3 channel table 39 ch, 2 MHz step (I) | | decode: 39 channels, 2404-2480 MHz, 2 MHz | match |
| second-link width vs radio | ~1.4 MHz | ground TX filter 1.25 MHz RF vs measured 1.41 MHz | consistent |
| patent CN110046591B rejected (V) | no 9.3 kHz | df 10937.5 in 40 files | consistent |
| static pilot channel estimate dead end (U) | 4th-power coherence 0.007 vs 0.17 | cause found: data carry a residual -10 deg/carrier ramp relative to the pilot channel (C) | **differs**: dead end explained |
| data constellation not resolved; 2-TX STC pair fit (U) | | see C and "not beyond" | still unresolved; partly refined |

Totals over the 50 claim rows above: match or consistent 38, differs 5 (pilot grid on non-M100 models; static-estimate dead end now explained; burst symbol count +2; Mavic Pro burst length; GENESYS constellation usability), not tested 6, still unresolved 1 (data constellation).

## B. Population check

- 130 records; demod on 128 bursts; 115 pass the Lightbridge gate (CP corr > 0.8, pilot-class agreement > 0.9).
- Not passing: GENESYS 5 (agreement 0.34-0.89, CP corr 0.98-1.00, numerology still fits), KU Matrice 3 and Mavic 2, Zenodo Mavic Pro 3 (CP corr 0.00-0.02, agreement 0.30-0.54: numerology B, demod not applicable). Mini 2 and Mavic Mini: no wide burst.

### Groups by measured numerology (per file; label as attribute)

| group | numerology | files | devices |
|---|---|---|---|
| A | df 10937.3-10937.6 Hz (GENESYS 10939.2), CP 0.125, Tsym 102.85-102.87 us, 864-866 used, frame 14.0 ms, burst 9.76-10.2 ms, bw 9.6-9.8 MHz, second link 2.2 ms / 1.2-1.6 MHz | 40 | M100 (Zenodo 1, GENESYS 27), Inspire 2 (Zenodo 3, KU 2), M210 (3), P4 (1), P4P+ (3) |
| B | df 15000.0-15000.6 Hz, CP 0.0714-0.0716 (1/14), Tsym 71.42-71.44 us, 1024-grid full span, bw 18.07-18.16 MHz, bursts 3.6-5.1 ms, period 5.0-6.0 ms | 5 | Matrice (KU 2), Mavic (KU 2), Mavic Pro (Zenodo 1) |
| unfit | no wide OFDM burst; KU Mini 2: 40 narrow bursts 0.5 ms, 27 centres; Mavic Mini: none | 2 | Mini 2 (KU), Mavic Mini (Zenodo) |

- Match Lightbridge (1024 FFT, 10.9375 kHz, CP 1/8, 864 used, pilots every 9th): all of group A (40 files); the pilot pattern is verified by demod in 115 bursts over all A devices.
- Do not match: group B (15 kHz, CP 1/14, 18.1 MHz, full 1024 span, shorter bursts, no 9-grid class pattern). Mavic Pro also shows 56 narrow bursts (0.5 ms, 34 centres).
- Second narrowband link: present in 11/11 Zenodo group-A files (both bands), 2.18-2.6 ms, 1.17-1.56 MHz; not seen in the 2 KU Inspire 2 video files.

### Per-burst similarity (115 gated bursts, `table.tsv`)

- Identical in all 115: pilot even/odd amplitude ratio alternates (ratio at odd symbols x ratio at even symbols 0.99-1.04, roles swap each symbol); class phase steps +60/-30/-30 deg; 90 deg intra-pair step; symbol 0 coherent in the three pilot classes (median metric 0.80) with k4 median 2.28; symbols 1-2 low modulus spread (CV median 0.16, p5 0.03, p95 0.45).
- Varies: ratio 1.0-11.7; even-odd pilot phase near 0 or near 90 deg (bimodal; 3 bursts between); data k4 1.02-1.73; SNR 15-47 dB (median 40).
- Repeats within a session: std(log ratio) 0.001-0.003 in all 8 Zenodo groups (63 bursts) and KU Inspire 2 (30 bursts, 10 files).
- Differs across sessions of one model: Inspire 2 Zenodo ratio 4.28, phase 89 deg, k4 1.39; KU ratio 3.88, phase 2 deg, k4 1.46. Differs across bands of one unit: Inspire 2 4.28 (2.4) vs 2.08 (5.8); M210 11.67 vs 2.31; P4P+ 1.45 vs 2.64.
- GENESYS (22 gated, one burst per UAV x distance): eta^2 of log ratio by UAV 0.51, by distance 0.20 (n=1 per cell, indicative). uav2: 5.75 at 6 ft, 1.45 at 12 ft, 1.01 at 15 ft.
- Ward, 8 clusters: KU Inspire 2 (30) alone; M100 + Inspire 2 5.8G + 6 GENESYS (29); P4P+ 2.4G + M210 5.8G + 3 GENESYS (15); M210 2.4G alone (8); P4 + 5 GENESYS (15); Inspire 2 2.4G + P4P+ 5.8G + 1 GENESYS (13); GENESYS remainders (4, 1). Clusters follow dataset/unit/band, not protocol fields.
- Reading (I): ratio and phase track the radio path (antenna geometry, band, unit), not the protocol: constant within a session, different between sessions and bands, drifting with distance for one UAV. Protocol constants (class pattern, steps, alternation, symbol-0/1/2 structure) do not vary.

## C. Two new variants (bounded)

Variant 1: per-carrier channel from training symbols 1-2 (assumed constant modulus) vs the pilot model; 9 bursts (M100 x3, M210, KU Inspire 2 x2, GENESYS x3).
- V (negative): data k4 with pilot model 1.02-1.73; training magnitude from symbol 1 or 2 alone 2.1-224; mean power of both 1.07-5.9; never lower than the pilot model. Pilot-static gain = per-symbol pilot model (1.59 vs 1.59 on M100). Training phase does not change k4.
- Per-carrier 4th-power coherence over symbols: median 0.15-0.19 vs Gaussian null 0.20-0.22 (8 two-path bursts); 0.015 on M210.
- Training symbols are not a clean per-carrier gain reference.

Variant 2: pair combining z = y1 + sigma a(k) conj(y2), a(k) by blind 4th-power search, sign per pair refined iteratively.
- V: alignment (1,2): k4 1.62 (M100, 3 bursts), 1.61-1.62 (KU, 2); wrong alignment 1.69-1.79; control (m, m+3) 1.68-1.78; GENESYS 1.65-1.87 (alignment differs per burst).
- Positive control, identical pipeline: simulated 2-TX Alamouti 16QAM at 30 dB gives k4 1.51 and mean coherence 0.556; Gaussian null 2.07 and 0.565. The search cannot recover a 16QAM lattice from ~40 pairs per carrier, so the negative result is uninformative. Only the pair-vs-control difference (0.15-0.17 in k4 on M100) is evidence; it repeats the earlier power-anticorrelation finding.

Unplanned finding on constant-modulus bursts (V):
- M210 2.4G (ratio 11.7, 8 bursts): data k4 1.017, modulus CV 0.066. Adjacent-carrier products show a constant -10.0 deg step per carrier (mod 90 deg), step coherence over symbols 1.00, within-symbol 0.94, left in the data by the pilot-based equaliser. Removing it: four phase peaks at 0/90/180/270 deg, QPSK EVM 0.26-0.31 (Gaussian null 0.63), 4th-power coherence 0.50-0.63.
- Same -10.0 deg step: M210 5.8G 4/4, P4P+ 5.8G 4/4, GENESYS uav7 2/2, P4P+ 2.4G (-9.6..-11.0). Step coherence > 0.9 in 25/115 bursts; median step -10.2 deg over all 115. Equivalent to a 28.4-sample delay (mod 256) between data and pilot channel, or a cyclic-delay-type precoder; which one is U.
- It explains the earlier low 4th-power coherence (0.17, 0.007) and part of the "Gaussian-like" kurtosis (measured with the ramp uncorrected).
- Two-path bursts (M100, Inspire 2, P4): ramp not recoverable (coherence 0.18-0.58), k4 stays 1.39-1.59. corr(log ratio, k4) = -0.77 over 115 bursts: k4 falls to ~1.0 as one path dominates, as expected for a two-stream mixture. A QPSK two-stream mixture cannot exceed k4 1.5, so k4 1.59-1.73 needs a higher-order or more complex mix (U).

## Beyond the existing analysis

- Software demod: per-symbol pilot-class tracking, 100% class agreement in nearly all of 115 bursts.
- Pilot amplitudes two-level, swapping per symbol pair (115/115); class steps +60/-30/-30 and 90 deg intra-pair (115/115).
- Symbol 0 (all classes coherent, k4 ~2.3) and symbols 1-2 (low modulus spread) as preamble-like structure.
- Pair power anticorrelation (-0.35, M100); Alamouti scan and per-parity ZF combining; PRBS11 pilot tests (0 of ~1800 symbol tests above chance); PRBS15 descramble search (hits at chance).
- Population: session/device dependence of ratio and phase.
- Numerology on every DJI video file held (A 40, B 5, unfit 2), both bands.
- The -10 deg per-carrier ramp and QPSK-like peaks on constant-modulus bursts.

## Not beyond (still open)

- Data constellation unresolved for two-path bursts (most captures): k4 1.39-1.73, EVM at the Gaussian null for QPSK, 16QAM, 64QAM. Single-path bursts look QPSK-like only with EVM 0.26-0.31, not clean.
- Exact transmit scheme (Alamouti-like pairs vs cyclic delay on both antennas vs multiplexing): U; the AD9363 config does not decide it.
- FEC, interleaver, scrambler, framing bits: nothing found; no bit stream is valid while the constellation is unresolved.
- Pilot value sequence: negative, with the two-path sign caveat.
- Second-link carrier map and CP; Inspire 2 RC; Matrice/Mavic RC; Mavic Mini and Mini 2 numerology.
- Pilot power boost; fold-plateau CP; GENESYS bandwidth; the owned P3 itself.
