# Cyclone III / IV `.rbf` (E, GX, III LS)

Decoder: `scripts/cycloneiv_decompress.py` (`decompress(bytes) -> bytes`, CLI `--info`, `-o`).
Oracle: `quartus_cpf -c -o bitstream_compression=on|off X.sof out.rbf` (Quartus 25.1 Lite) on the vendor
SFL / SFL-enhanced / PFL `.sof` files shipped in `quartus/common/devinfo/programmer/`.

## Status (2026-10-24)

| Layer | Status | Evidence level |
|---|---|---|
| Container, header, frame CRC, compression | decoder written | identical to oracle, 70 / 70 pairs |
| LE LUT mask (EP4CE6) | address model for every LAB LE site measured | simulated vs post-fit netlist: fresh held-out 32 / 32 designs, 0 bad outputs |
| FF, LAB controls, routing, IO | not decoded (diff counts only) | none |
| Lifter / schema | not written (gated on a verified LE model incl. FF and routing) | none |

## Feasibility

- Cyclone IV device support installed on 2026-10-24 (`sources/README.md`, `scripts/quartus_device_install.py`).
  - `quartus_sh --tcl_eval get_family_list` -> `{Cyclone IV E} {Cyclone V} {Cyclone IV GX}`.
  - EP4CE6E22C8 builds end to end: map, fit, asm, eda (`.vo`), cpf.
  - Before that, Lite had Cyclone V only and nothing EP4C could be fitted.
- `quartus_cpf` needs no device package: it converts every Cyclone III/IV vendor `.sof` (70 `.sof`, 13 dies).
- Install-side Cyclone IV data: only `programmer/ep4c*_pcf.ddb` and `ep3c*_pcf.ddb` (about 1 KB each).
  - Each holds a zlib-packed type schema (`PGMIO_PCF_ENTRY`, `PGMIO_JTAG_CONSTANTS`, `PGMIO_ERAM_LOCATIONS`, ...) and a payload that does not inflate.
  - They are programmer constants. They carry no fabric or routing data, unlike the Cyclone V device DB.

## Prior art

Searched on 2026-10-24: gh code/repos, grep.app, DuckDuckGo, GitLab / Codeberg / sr.ht, papers, forums.

- **No public description of the Cyclone III/IV compressed format was found.**
- `14sea/Cyclone_CRAM_Mapper` (GitHub, GPL-3.0):
  - EP4CE6/EP4CE10, uncompressed only.
  - 210-byte frames, CRC-16 0xA001 init 0xFE54, header frames 0..24, LUT/FF/routing on one die.
  - Agrees with the frame layer below. That repo builds with `bitstream_compression=off`.
- Cyclone IV Handbook vol 1, ch. 8:
  - Compression is "35 to 55%" smaller; no algorithm given.
  - Per-frame 16-bit CRC plus a 32-bit CRC for error detection.
  - Table 8-2 gives the uncompressed sizes, which match the table below.
- Swierczynski MSc thesis (RUB 2012): Stratix II/III encrypted-header layout, CRC-16/MODBUS over the header. No compression, no Cyclone.
- Project Mistral: Cyclone V only. Its nibble scheme turns out to be the same one Cyclone III/IV uses.
- Forums (Altera Community #102341, comp.arch.fpga 2007): people asked for a Cyclone II/III decompressor; no answer.

## Format

Offsets relative to the `0x6a` sync byte `S` (`S = 32` in every Quartus file).

| Region | Bytes | Coding |
|---|---|---|
| preamble | `0xFF` x 32 | raw |
| frame 0 (header) | `6a`, 40 option bytes, CRC-16/MODBUS of the 40 bytes (LE), `0xFF` fill to `S+F` | raw |
| frames 1..r-1 (periphery) | `F` bytes each, **no per-frame CRC found** | raw |
| frames r.. (CRAM) | `F` bytes; last 2 = CRC-16 (poly 0xA001 reflected, **init 0xFE54**) of the other `F-2` | coded |
| postamble | `0xFF` x 59 | coded |

- **Header**: 8 bit-lanes x 40 bits; byte `i` = bit `i` of every lane. Lanes 5..7 are all 1s in all 140 files. Lane 4 is all 1s in 92 files, has bit 9 clear in 32, and has low byte 0x05..0xd9 in 16 (8 pairs; meaning not derived).
  - lane 1 bit 35 = uncompressed flag (1 = uncompressed).
  - Length field = lane 2 bits 16..39 (low) : lane 3 bits 0..6 (high).
    - Uncompressed: `4*(file length - 1)`. Holds for 70/70 files.
    - Compressed: `4*len - field` = 4..7. A `6` coincides with one unused nibble at EOF. The rule for the low bits is not derived; the decoder does not need it.
  - lane 1 bits 24..31: `0x07` on every Cyclone III / IV E file; `0x00` on IV GX and III LS (`0x01` on EP4CGX30 F484).
  - lane 1 bits 0..23 vary by part, including parts that share a die (EP4CGX110 vs EP4CGX150 differ in bit 23).
  - lane 0: all 1s on GX/III; on IV E it varies per design (a usercode or checksum; not derived).
  - lane 3 bits 16..39: not all 1s only on III LS (a design-security part). Varies per design and is the same in a compressed/uncompressed pair. Meaning not derived.
- **F** = header-frame length = the offset of the first non-`0xFF` byte after the header, minus `S`.
- **r** comes from the CRC chain: the first frame `k >= 2` where frames `k` and `k+1` pass.
- **Coding** (frame `r` to EOF): the Cyclone V nibble scheme (`docs/cyclonev-compressed-rbf.md`).
  - Low nibble first.
  - Per 2 output bytes: key `k`, then the nibbles `k` marks (bit0/1 = byte0 lo/hi, bit2/3 = byte1 lo/hi). Unmarked nibbles are 0.
  - Odd tail: the last byte is `f` + 2 nibbles, and the byte-1 nibbles are never supplied. So the 59-byte `0xFF` postamble codes to exactly 74 `0xFF` bytes.
  - Header, periphery and frame 0 are byte-identical between modes. Only the length field, the flag and the header CRC change.
- `0xFE54` is the CRC-16/MODBUS state after the bytes `cc e8` from `0xFFFF`. No meaning found for it; it is stated as an init value.
- 32-bit whole-stream CRC (handbook error detection): not located.

## Per-die geometry (vendor `.sof`, `quartus_cpf` only)

| uncompressed bytes | F | periphery frames | CRAM frames | CRAM bits | parts |
|---|---|---|---|---|---|
| 368,011 | 210 | 25 | 1727 | 2,873,728 | EP3C5, EP3C10, EP4CE6, EP4CE10 |
| 475,696 | 271 | 49 | 1706 | 3,671,312 | EP4CGX15 |
| 510,856 | 255 | 37 | 1966 | 3,979,184 | EP3C16, EP4CE15 |
| 718,569 | 298 | 25 | 2386 | 5,650,048 | EP3C25, EP4CE22 |
| 950,005 | 359 | 37 | 2609 | 7,451,304 | EP4CGX22, EP4CGX30 |
| 1,191,788 | 377 | 37 | 3124 | 9,372,000 | EP3C40, EP4CE30, EP4CE40 |
| 1,861,195 | 464 | 21 | 3990 | 14,747,040 | EP3C55, EP4CE55 |
| 2,495,719 | 543 | 21 | 4575 | 19,800,600 | EP3C80, EP4CE75 |
| 2,751,361 | 586 | 49 | 4646 | 21,706,112 | EP4CGX30 (F484), EP4CGX50, EP4CGX75 |
| 3,345,845 | 613 | 17 | 5441 | 26,595,608 | EP3CLS70, EP3CLS100 |
| 3,571,462 | 639 | 21 | 5568 | 28,374,528 | EP3C120, EP4CE115 |
| 4,928,127 | 796 | 37 | 6154 | 39,090,208 | EP4CGX110, EP4CGX150 |
| 6,326,341 | 875 | 13 | 7217 | 50,403,528 | EP3CLS150, EP3CLS200 |

- `uncompressed bytes x 8` equals Handbook Table 8-2 for every Cyclone IV entry (e.g. EP4CGX150 39,425,016 bits).
- Each Cyclone III die has the same geometry as its Cyclone IV E twin. Same die, different part bits.
- Bits per frame = `8*(F-2)`. The frame-to-LAB-column map is not derived, so nothing is claimed yet about which LE columns scale.

## Evidence

Measured 2026-10-24 on base `a219aa755`, Quartus 25.1std.0 Lite.

- `scripts/cycloneiv_pairs.py` -> `tmp/cycloneiv/pairs/`: 70 `.sof`, each converted plain + compressed, 0 failures.
- `scripts/cycloneiv_decompress_check.py` (log `tmp/logs/cycloneiv_decompress_check.log`):

| Set | Pairs | `decompress(c) == u` | Uncompressed passes through |
|---|---|---|---|
| Cyclone III / IV E / IV GX / III LS vendor `.sof` (sfl, sfl_enhanced, pfl), 13 dies | 70 | 70 / 70 | 70 / 70 |

- Every output passes all checks: header CRC, every CRAM frame CRC, 59-byte postamble.
- Unit test `tests/test_cycloneiv_decompress.py` uses a synthetic stream built to this format. The vendor-derived pairs are third-party and are not committed.

## Fabric decode, EP4CE6 (2026-10-24)

Every Cyclone IV rule here comes from Cyclone IV oracle runs. No Cyclone V bit position or rule is used.

### Corpus and tools
- `scripts/cycloneiv_fuzz.py`: generates `corpus/cycloneiv/<name>/` (src + design.toml tracked, outputs gitignored) and builds with Quartus, one process at a time under `heavy_guard`.
  - Designs instantiate WYSIWYG `cycloneive_lcell_comb` / `dffeas` at fixed `LCCOMB_X*_Y*_N*` / `FF_X*_Y*_N*` sites, with fixed pins.
  - Device EP4CE6E22C8.
  - Step times, worst over 302 builds: map 9.3 s, fit 10.1 s, asm 3.3 s, eda 1.6 s, cpf 0.4 s.
- `scripts/cycloneiv_fuzz_analyze.py`: CRAM bit sets plus the `.vo` oracle. Produces per-site LUT bit maps (trained on one-hot masks), the site sweep and FF diffs. Output `tmp/cycloneiv/fuzz_analysis.json`.
- `scripts/cycloneiv_le_model.py`: the LE address model, built from the sweeps.
- `scripts/cycloneiv_sim_check.py` is the **acceptance test**.
  - Decoded Verilog is simulated with iverilog against the post-fit `.vo` on all 16 vectors plus 64 random ones. Bad outputs are counted per design.
  - DUT-A uses the vendor `cycloneive_*` cell models, cut from `eda/sim_lib/cycloneive_atoms.v` (the whole file does not compile in iverilog).
  - `--negative-control` flips one decoded mask bit; every design must then fail.
  - Limits: the LUT mask is decoded from CRAM. Which pad feeds each LUT input, and the output-buffer inversion, are still taken from the `.vo` (routing and IO are not decoded). So this tests the mask decode end to end (positions, polarity, input order), not a lift.
- Reused from Cyclone V, as method only:
  - `cyclonev_vo_parse.Vo`, imported, with Cyclone IV cell types added; `top_module_only` drops the SDF line and the `hard_block` module.
  - The `cyclonev_corpus_build.py` builder pattern (stall and overall limits, one Quartus at a time).
  - The `cyclonev_lifted_sim_check.py` testbench pattern.
  - The `cyclonev_lift_scorecard.py` fields: matched / missing / extra / wrong, with a held-out split.

### LUT mask results

| set | designs | sim: designs with bad outputs | output compares ok / bad / x |
|---|---|---|---|
| per-site maps, 3 sites (16 one-hot train + 24/16/16 held-out masks) | 104 | 0 | 8,320 / 0 / 0 |
| address model, the same 104 | 104 | 0 | 8,320 / 0 / 0 |
| address model, `ho_*` 16 random sites x 2 masks (became training, see below) | 32 | 4 before fix, 0 after | 2,560 / 0 / 0 after |
| address model, `ho2_*` fresh held-out, 15 sites x 2 random masks | 32 | **0** | 2,560 / 0 / 0 |
| negative control (one mask bit flipped), lut_* / ho2_* | 104 / 32 | 104 / 32 (all fail, as required) | |

- Structural sub-check: per-site maps on held-out masks gave matched 384 / 256 / 256, with missing 0, extra 0 and wrong 0 per site. The model predicted all 16 bit positions at the held-out site X10_Y10_N16.
- Model fixes, both found by held-out failures, and found only that way:
  - The bit order mirrors for odd LEs of a pair. The first model mispredicted 8/16 bits at X1_Y18_N2.
  - Lane 7 holds 206 bytes, not 207. 4 `ho_*` designs at rows whose LAB crosses into lane 7 failed in simulation; after the fix, 0.

### LE address model (EP4CE6)
- Frame bit index `b = byte*8 + lane` (byte in frame data, lane = bit within byte, LSB first).
- Vertical position `v`: lane 7 bytes 0..205, then lanes 6..0, 207 bytes each.
- Mask bit `k` of LE (X, Y, N):
  - `frame = FX[X] - (k >> 1)`: 8 consecutive frames, descending.
  - `v = VY[Y] + DN[N] + s*dv(k)`, with `dv` = 0, -1, -1, 0 repeating. `s` = -1 when N/2 is odd (mirror).
  - No inverted bits: a stored 1 is a mask 1.
- `FX` (frame of mask bit 0): X1..X14 = 81 + 35*(X-1). X16 864, X17 899, X18 938, X19 973. X21..X26 = 1033 + 35*(X-21). X28..X33 = 1536 + 35*(X-28).
  - Columns 35 frames apart. X17 to X18 is 39.
  - Non-LAB columns X15, X20 and X27 do not fit an LE. The gaps are 328, 60 and 328 frames.
- `VY`: rows 70 v apart (lane 7 first). Y1 = 91 ... Y11 = 791, Y17..Y23 = 1211 + 70*(Y-17). X1 rows Y12..Y16 do not fit an LE.
- `DN` (v offset of LE N/2 = 0..15): 0, -3, -8, -11, -16, -19, -24, -27, -38, -41, -46, -49, -54, -57, -62, -65.
  - LE pairs sit 3 v apart and pairs 5 v apart, with an extra 6 v gap between LE 7 and LE 8.
  - That gap is presumably LAB-wide control bits (not decoded).
- A LAB spans 66 v of a 1655-v frame column (206 + 7 x 207) x 35 frames. 23 rows x 70 v = 1610.

### FF results (no decode yet)
- `power_up=high` is not a FF bit. Quartus implements it by push-back: an inverting LUT feeds `asdata`, `sload=1`, and the output buffer `.i` is inverted.
  - It rejects power-up high with CLRN (error 14053) and with SCLR (no fit).
  - So no FF field is scored. The `ff_high_*` control variants were dropped.
- Each control changes many bits relative to `ff_low_base`, mixing routing with LAB config:
  - clrn: +35 / -21 bits
  - ena: +30 / -13
  - sclr: +31 / -37
  - sload: +80 / -52
  - all: +135 / -105
- Not attributable without routing decode. Fault table for FF fields: not scored (0 decoded).

### Layout vs Cyclone V (structure only, no values)
- Cyclone V reference: the Mistral `lab-mux.txt` LUT_MASK position list.
- Both families:
  - store LUT bits 2 per frame, in vertically adjacent positions, over consecutive frames;
  - use alternating (boustrophedon) order: k0/k1 swap orientation each frame step.
- Differences:
  - IV pairs are frame-aligned (k0, k1 in one frame; 16 bits in 8 frames, descending).
  - V pairs straddle frames: frame 2 holds one bit; 16 bits over 10 tile frames, frames 2..6 ascending then 11..7 descending.
  - IV LEs mirror orientation within an LE pair. IV packs one LAB per 35-frame column x 66 v, with 8 bit-lanes interleaved per frame.
- The structure lines up at the 2-bits-per-frame snake. The tile geometry does not.

## The m2001 sample (third-party image, read-only, not in repo)

`scripts/cycloneiv_die_match.py IMAGE` (log `tmp/logs/cycloneiv_die_match.log`).

- **Decoded and structurally valid**:
  - header CRC OK, compressed flag set;
  - F = 796, 37 periphery frames, **6154 / 6154 CRAM frame CRCs valid**;
  - decompresses to 4,928,127 bytes, the EP4CGX110/150 size.
- **Die: EP4CGX110/150** (the geometry, the CRC chain and the length all fit only this die).
  - Part bits: lane 1 bit 23 matches the EP4CGX150 SFL files, not EP4CGX110. That is one bit with one reference file per part: moderate.
- **Not encrypted**: the CRAM frame CRCs are over cleartext. 4634 / 6154 CRAM frames are non-zero, 2,211,198 set bits; the vendor SFL loader has 1447 frames and 294,160 bits.
- Container: the image is 32 FF + stream + flash `0xFF` padding.
  - The length field says the stream ends 74 bytes after the last non-`0xFF` byte, which is exactly the coded 59-byte postamble.
  - A copy cut at the last non-`0xFF` byte lacks that postamble, and the decoder rejects it (`postamble 0 x 0xFF < 59`).
- Header differs from the vendor files beyond flag/length/CRC: lane 1 bits 36..37, lane 3 bits 8..11, lane 0. These are option bits; meaning not derived.
- Earlier work in this repo treated the same payload as a Cyclone V e50f stream. That reading is contradicted: the payload has no `jjjj` sync, and it passes the Cyclone IV CRC chain on all 6154 frames.

## Routing decode, EP4CE6 (paused 2026-10-26; work moved to EP4CGX150)

- Security: Cyclone IV E/GX have no design-security (AES) feature (handbook vol 1 has compression, no security chapter; only Cyclone III LS has AES), so every Cyclone IV stream is decodable in principle.
- Routing oracle: `quartus_cdb --back_annotate=routing` works for Cyclone IV (EP4CE6, GX parts listed by Quartus 25.1). Exported per design as `corpus/cycloneiv/<d>/routing.rcf` (`cycloneiv_fuzz.py` step `quartus_cdb`; it rewrites `build.qsf` even with `--write_settings_files=off`, so the `.qsf` is restored).
- RCF element types seen: LE_BUFFER, LOCAL_LINE, LOCAL_INTERCONNECT, R4, C4, R24, C16, LAB_CONTROL_MUX, BLOCK_INPUT_MUX, IO_DATAIN, LAB_CLK, BLK_CLK_BUF, BLK_CLK_LIM, SCLK_TO_ROWCLK_BUF, GLOBAL_CLK_H/V, CLK_BUFFER, CLKBUF_IN/OUT, GEN_CORE_BUF.
  - `dest = (atom, PORT), route_port = P`: P is the physical LUT pin (matches the `.vo`).
  - LE_BUFFER index = 2 x LE + {0, 1}.
- Corpus: `rnd_*` (`scripts/cycloneiv_rnd_designs.py`): random 4-LUT networks + registers with random enable / sync clear / async clear / sync load, adders, XOR-group outputs, fitter SEED per design. Tiers s 40 (20-120 nodes), m 40 (300-700), l 40 (900-1500).
  - First attempt (up to 2600 nodes, global random wiring) did not route in 10 min; sources now 85% from the last 60 nodes. Worst fit after that 65 s (4 jobs).
- Tools: `cycloneiv_corpus.py` (RCF parser, CRAM as a (frame, v) plane), `cycloneiv_geom.py` (device-driven tile anchors, `lifters/data/cycloneiv_<die>_geom.json`), `cycloneiv_route_learn.py` (tile-relative mux tables), `cycloneiv_route_score.py` (scored vs RCF).
- Findings:
  - LOCAL_INTERCONNECT mux = 2 levels in 2 v rows: level A = 2 bits in one frame (or none), level B = one-hot over 6 bits in the next 3 frames; 18 inputs. Patterns with only a B bit exist (A = none).
  - Mux input order differs per LAB column (not X parity); tables are keyed per column.
  - R4 / LE_BUFFER sources: same pattern for every row of a column.
  - C4 sources: naming depends on Y. Per (column, LI, pattern), source is a function of Y mod 4 in 20,295 / 21,191 cases (Y mod 1: 6,692 / 9,214). Not yet modelled.
- Held-out score (train `rnd_l*` crc32-even 20 designs, score the odd 20), 2026-10-26:

| dst type | matched | missing | wrong | extra | headline |
|---|---|---|---|---|---|
| LE_BUFFER (LE comb/FF -> buffer) | 37,847 | 1,179 | 10 | not scored | 97.0% |
| LOCAL_INTERCONNECT | 65,851 | 40,871 | 1,596 | not scored | 60.8% |
| R4 | 35 | 129,794 | 3,215 | not scored | 0.0% |
| all RCF edges | 103,733 | 488,931 | 4,821 | not scored | 17.4% |

  - LI missing = 38,006 ambiguous patterns (C4 Y-naming) + unknown/untabled. R4: mux bits not found by the tile-relative rule (R4 mux probably sits at the driving end, outside the window or keyed wrong). C4, C16, R24, LE inputs, LAB controls, clocks, IO: not learnt yet (`no table`).
  - `extra` not implemented in the scorer yet; not a pass.
- Resume: `cycloneiv_fuzz.py --build --match 'rnd_*' --jobs 4` (needs `--generate` first), `--rcf-only` for older designs, then `cycloneiv_route_learn.py --train 'rnd_l*' --split even` and `cycloneiv_route_score.py --tables tmp/cycloneiv/route_learn_even.json --designs 'rnd_l*' --split odd`.
- Left for EP4CE6: C4 Y-rule, R4/C4/C16/R24 mux location, LE input and FF control sinks, LAB-wide controls and inversion, carry (`sum_lutc_input`, cin), clocks, IO, lifter + emitter, sim gate.

## EP4CGX150 (2026-10-26, current target)

- Quartus 25.1 builds EP4CGX150DF31C7 / EP4CGX110DF31C7 (smoke: map 4 s, fit 9 s). One CRAM geometry for both: F = 796, 37 periphery + 6154 CRAM frames. GX has no AES (see EP4CE6 section).
- Die of the third-party compressed image under study: EP4CGX150. Header lane 1 bits 0..23 = 0x200dff on our GX150 builds and on the image; 0xa00dff (bit 23) on GX110. Also matches the vendor-SFL comparison.
- Legal LABs by fitter probe (`cycloneiv_device_grid.py`, `lifters/data/cycloneiv_ep4cgx150_labs.json`): 9,360 LABs = 104 columns x 90 rows (149,760 LEs / 16).
- Corpus: `gx150_sp_000..299` (random RTL, 400-900 nodes, one anchor register per LAB in a random 7x7 window, `FITTER_EFFORT "FAST FIT"`). Worst step over 300 builds: map 12.1 s, fit 31.6 s. Unconstrained designs of 4.5k nodes: fit > 11 min; Lite has no place regions.
- Geometry (`lifters/data/cycloneiv_ep4cgx150_geom.json`, from `cycloneiv_le_locate.py` + `cycloneiv_geom.py`, no per-site sweeps):
  - the EP4CE6 per-LAB LUT-mask rule holds unchanged;
  - 3,921 LAB tiles located, 2,915 confirmed in 2 designs, 0 conflicts;
  - 8 lanes x 793 bytes, row pitch 70 v, LAB column pitch 35 frames; 104 LAB columns + 12 special (M9K-like gap 328, multiplier-like gap 60) + 2 IO.
- LUT-mask decode from CRAM vs post-fit `.vo` (`cycloneiv_lut_check.py`), 301 designs: 334,656 cells (13,419 arithmetic), 5,354,496 mask bits, matched 100%, missing 0, wrong 0.
- Routing (held-out, 30 training designs `gx150_sp_00..06` crc32-even, scored on 21 other designs; matched / (matched + missing + extra + wrong), extra not scored): all pips 236,659 / 293,757 = 80.56%.

| dst type | matched | missing | wrong | % |
|---|---|---|---|---|
| LOCAL_INTERCONNECT | 51,568 | 3,380 | 87 | 93.7 |
| C4 | 44,579 | 6,578 | 102 | 87.0 |
| R4 | 50,307 | 9,504 | 126 | 83.9 |
| LE inputs | 55,054 | 21,731 | 363 | 71.4 |
| LE_BUFFER | 20,193 | 637 | 0 | 96.9 |
| C16 / R24 | 1,833 / 1,756 | 1,207 / 889 | 96 / 34 | 58.5 / 65.6 |
| LAB_CONTROL_MUX | 200 | 1,217 | 33 | 13.8 |

- More training data is the main lever (same learner reached 84.7% overall with 150 training designs); memory is the limit: a plane is 38 MiB per GX150 design.
- Method findings (hold on both dies): mux bits sit at the wire's driving end (R4 dx, C4 dx 0..1 / dy, per-group search); R4 / C4 indices rotate with Y mod 4; LI input order repeats per X mod 8; FF CLK / ENA / CLRN pins pick a LAB line with a per-LE select bit (EP4CE6 held-out 1117 / 1117 and 277 / 277 LABs).
- Not done on GX150: connection-level trace score, FF / LAB-control / IO / carry decode, lifter + emitter, sim gate, M9K / multipliers / PLL.
- EP4CE6 LUT decode: 996 wrong bits of 1,780,540 + 996 in `rnd_*` (all LEs crossing the bit-lane boundary at v 1241 and 206); the GX150 lane model has no such case. EP4CE6 lane fix pending.

## Quartus device-info (.ddb) decode, Cyclone IV GX (2026-10-26)

Files: `quartus/common/devinfo/cycloneivgx/ddb_stingray{1..4}_*.ddb`; E family in `cycloneive/`. Reader: `scripts/quartus_ddb.py`, dump: `scripts/quartus_ddb_dump.py`.

- Container: 0x73-byte header (u32 0x14, ..., "Version 25.1std.0 ...") then payload.
  - zlib kinds (icname, routing, asm, place, pad, timing, gid_database): a chain of zlib streams, NOT terminated; each ends with a sync-flush marker `00 00 ff ff` and the next starts with `78 01` (the "invalid stored block lengths" of a single inflate is that boundary). Split on `00 00 ff ff 78 01`, inflate each: 100% of the bytes decode.
  - xz kinds (hdr, part_info, pcf): one `fd 37 7a 58 5a 00` stream at 0x73 (Python `lzma`).
  - asmdb / asmdb_dirt: other layout, not decoded.
- Which stingray is which (`device.db`, SQLite, names base64): STINGRAY1 = EP4CGX15, STINGRAY2 = GX30 (V1 = GX22), STINGRAY3 = GX75 (V1 GX50, V2 GX30A), STINGRAY4 = EP4CGX150 (149,760 LEs), STINGRAY4_V1 = EP4CGX110 (109,424 LEs). Same ddb files (`ddb_stingray4_*`) serve both.
- Header bit meaning (settled): the option lanes of `quartus_cpf` .rbf output for 6 of our builds (`cycloneiv_header_probe.py`):
  - lane 1 = `f8 00 20 0d ff` on every EP4CGX150 build (DF31C7, CF23C8, DF27I7) and `f8 00 a0 0d ff` on every EP4CGX110 build (DF31C7, CF23C7, DF27C8). Lane 1 bit 23 = die variant (STINGRAY4 vs STINGRAY4_V1: full die vs fused-down 109,424-LE variant). It does not follow package, speed grade or temperature grade.
  - lane 0 = `00 73|74 xx yy ff`: byte 2..3 change per build (usercode / checksum); byte 1 = 0x74 on the F484 (CF23) builds and 0x73 on the F672 / F896 builds, so it follows package.
  - lanes 2..3 identical across all six builds.
  - A third-party compressed image has lane 1 = `c0 00 20 0d ff` (first byte differs: option bits; bytes 1..3 = `00 20 0d` as on GX150, GX110 has `00 a0 0d`), so it is the EP4CGX150 variant (full die), not GX110.
- stingray4 hdr.ddb payload (107 KB): chip description database (device name "EP4CGX150", family, node-type names such as LE_BUFFER, LAB_LINE, C16, GLOBAL_CLK_H; file names `stingray4.ww19.asm.rba`, `stingray4_dirt.xml`). It carries no .rbf header fields.
- asm / icname decoded (2026-10-26, [cycloneiv-ddb-format.md](cycloneiv-ddb-format.md)): record = one routing wire (icname gives its vendor name), group = one input of a destination mux, entry = (CRAM bit, role): select bit, or one of the two shared second-level bits programmed iff `b1 == -1`. asm (frame, v) -> plane (FX + 17 - (frame - FX), 6344 - v). Parse ends at EOF; the earlier `u32 c` / `(delta, mask)` reading was the same stream misframed by 4 bytes.
  - Decoder `scripts/cycloneiv_asm_decode.py` (prepare / learn / score) + `scripts/cycloneiv_asm_tables.py`; tables `lifters/data/cycloneiv_ep4cgx150_asm_names.json` (block -> RCF destination per tile class, RCF source aliases, LE_BUFFER record bases).
  - The RCF names a wire by its driver column / row, so one asm record has several RCF names; scoring uses the learnt alias sets (see the format doc). routing.ddb (fan-in map) still undecoded.
  - Held-out score (asm tables alone, 20 odd designs, tables learnt on 60 even; `cycloneiv_asm_decode.py score`), matched / missing / extra / wrong: LOCAL_INTERCONNECT 30,196 / 14,284 / 557 / 12,277 (52.7 %), C4 9,179 / 40,432 / 0 / 519 (18.3 %), R4 10,076 / 45,871 / 15 / 543 (17.8 %), every other class 0 (LCCOMB, LE_BUFFER, LOCAL_LINE, FF, C16, R24, LAB controls, clocks: no block named yet); all LAB pips 49,455 / 229,368 / 1,024 / 13,366 = 16.9 %. The learner on the same 20 designs: 282,978 / 21,978 / 1,597 / 201 = 92.25 %, nets 59.2 % (`cycloneiv_learner_baseline.py`). The asm decode does NOT replace the learner yet: 85 % of learner source patterns map to an asm input of the right wire type, 15 % to a different type and 20 % to no exact group (`(FC, VC) = (17, 6344)` is the best of the nine neighbouring mirror constants), so either the bit rule has a fourth case or the learner's pooled patterns are incomplete; and the block -> destination map covers 1,913 mux keys (832 by learner position, the rest by co-occurrence).

## EP4CGX150 routing tables from the corpus (2026-10-26, replaces the 80.6% figure)

- Learner now streams per source (AND / OR of windows) instead of stacking windows (1.5 GB for the large LE-input groups), so all 150 crc32-even designs fit in a 2.5 GB cgroup; planes are sparse (`SparsePlane`, ~1 MB per design, was 38 MiB).
- Held-out (20 designs of the odd half), pooled tables (X mod 8, Y mod 4): pips matched 272,070 / (matched 272,070 + missing 21,492 + extra 1,644 + wrong 195) = 92.10%; nets with every pip matched 13,210 / 22,407 = 58.95%.
  - extra counted on touched tiles + 60 random untouched LABs per design; an unused mux whose bits read as one known source.
  - per type, matched / missing / wrong: LE inputs 74,574 / 2,571 / 3 (96.7%), LOCAL_INTERCONNECT 52,137 / 2,858 / 40 (94.7%), C4 48,444 / 2,798 / 17 (94.5%), R4 53,888 / 5,986 / 63 (89.9%), LE_BUFFER 20,823 / 7 / 0 (99.97%), FF pins 5,580 / 515 / 25 (91.2%), LAB_CONTROL_MUX 1,234 / 209 / 7 (85.1%), C16 1,877 / 1,238 / 21 (59.9%), R24 1,681 / 989 / 9 (62.8%).
  - not covered (zero / no table): clock tree (BLK_CLK_BUF 1 / 2,440, LAB_CLK 93 / 445, SCLK_TO_ROWCLK_BUF 7 / 478, GLOBAL_CLK_*), IO (IO_DATAIN 195 / 327, IOOBUF 5 / 379, BLOCK_INPUT_MUX 307 / 80). Most of the remaining misses are 'ambiguous pattern' (two sources share a pooled pattern): per-column tables resolve those.
- IO sites (`cycloneiv_io_bits.py`, no geometry needed): each used IOOBUF site has a 36-bit configuration signature (set in >= 95% of designs using the site, in <= 3% of the others), in clusters of 4 consecutive v. Top-row (Y91) and bottom-row (Y0) IO config sits in the periphery frames (e.g. X26/X30/X32/X34 -> frames 26..29), v falls by 136 per IO step of 7 in N (N2, N9, N16, N23). The LAB-column anchor model does not apply to IO rows, so IO-row routing tables (IO_DATAIN, BLOCK_INPUT_MUX, IOOBUF.I) need their own anchors.
- IO input sites: every used IOIBUF site has a 4-bit signature (4 consecutive v in one periphery frame), set in all designs using the site and in <= 3% of the others (249 sites with >= 12 uses; e.g. X26 Y91 N1 frame 26 v 380..383, N8 244..247, N15 108..111: v falls by 136 per N step of 7; left/right IO columns X117 carry the same pattern with frames 20..34). Some sites also show a bit beyond the lane model (v 6344+, the lane-tail columns).
- Memory: a per-column learner (104 columns instead of 8 classes) needs a larger cgroup than 2.5 GB.

## Gaps

- Fabric not decoded:
  - FF fields: d / clk / clrn / ena / sclr / sload / asdata.
  - LAB-wide controls; routing (needed before LUT inputs can come from the bitstream instead of the `.vo`); IO buffers and standards; M9K; multipliers; PLL.
- Address model covers EP4CE6 LAB LEs only. Rows Y12..Y16 at X1 and the non-LAB columns are unmapped. Other dies untested.
- Periphery frames 1..r-1: no CRC found in-frame; how they are protected is unknown.
- Compressed length-field low bits; header lanes 0 and 3, lane 1 bits 0..23 and 36..37.
- Compressor not written.
- Encrypted Cyclone III LS streams: no oracle. Cyclone IV E/GX cannot encrypt ([fpga-encryption.md](fpga-encryption.md)).
