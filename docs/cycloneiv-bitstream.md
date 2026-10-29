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
  - Each holds a zlib-packed type schema (`PGMIO_PCF_ENTRY`, `PGMIO_JTAG_CONSTANTS`, `PGMIO_ERAM_LOCATIONS`, ...) and a second zlib payload that does inflate (`ep4cgx150_pcf.ddb`: zlib at byte 117, up to the `00 00 ff ff` marker at 746; 3,160 bytes = 790 little-endian words, among them 2048, 262144, 6344 and 6506) [V 2026-10-29]. The words are not yet matched to fields.
  - They are programmer constants; whether they carry the lane/padding table for the image-to-`.rbf` map is open (#165). They carry no fabric or routing data, unlike the Cyclone V device DB.

## Prior art

Searched on 2026-10-24: gh code/repos, grep.app, DuckDuckGo, GitLab / Codeberg / sr.ht, papers, forums.
Full sweep and the 14sea cross-check (2026-10-29): [cycloneiv-prior-art.md](cycloneiv-prior-art.md). It found two paywalled papers on Intel bitstream decompression (Ren et al.) and LUT mapping (PSE23), so the claim below is "no public description found", not "none exists".

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
  - Held-out score (asm tables alone, 20 odd designs, tables learnt on 60 even; `cycloneiv_asm_decode.py score`), matched / missing / extra / wrong: LOCAL_INTERCONNECT 30,196 / 14,284 / 557 / 12,277 (52.7 %), C4 9,179 / 40,432 / 0 / 519 (18.3 %), R4 10,076 / 45,871 / 15 / 543 (17.8 %), every other class 0 (LCCOMB, LE_BUFFER, LOCAL_LINE, FF, C16, R24, LAB controls, clocks: no block named yet); all LAB pips 49,455 / 229,368 / 1,024 / 13,366 = 16.9 %. The learner on the same 20 designs: 282,978 / 21,978 / 1,597 / 201 = 92.25 %, nets 59.2 % (`cycloneiv_learner_baseline.py`); asm first + learner fallback (`--asm`): 274,940 / 30,004 / 1,769 / 213 = 89.58 %, nets 47.5 % (C4 95.4 vs 94.8 %, R4 90.7 vs 90.3 %, LI 79.8 vs 94.8 %). Second round (tables from all 150 even designs, select-entry rule fixed): asm alone 50,211 / 228,056 / 1,025 / 13,922 = 17.1 % (LI 30,425 / 13,572 / 555 / 12,760 = 53.1 %); combined 274,533 / 30,419 / 1,770 / 205 = 89.45 %, nets 47.1 %. Below the learner on the same designs, so the learner stays the default and the asm work stops here (stopping rule, 2026-10-26). The asm decode does NOT replace the learner (route_decode uses it only when an `AsmSource` is passed; issue #136): 85 % of learner source patterns map to an asm input of the right wire type, 15 % to a different type and 20 % to no exact group (`(FC, VC) = (17, 6344)` is the best of the nine neighbouring mirror constants), so either the bit rule has a fourth case or the learner's pooled patterns are incomplete; and the block -> destination map covers 1,913 mux keys (832 by learner position, the rest by co-occurrence).

## EP4CGX150 routing tables from the corpus (2026-10-26, replaces the 80.6% figure)

- Learner now streams per source (AND / OR of windows) instead of stacking windows (1.5 GB for the large LE-input groups), so all 150 crc32-even designs fit in a 2.5 GB cgroup; planes are sparse (`SparsePlane`, ~1 MB per design, was 38 MiB).
- Held-out (20 designs of the odd half), pooled tables (X mod 8, Y mod 4): pips matched 272,070 / (matched 272,070 + missing 21,492 + extra 1,644 + wrong 195) = 92.10%; nets with every pip matched 13,210 / 22,407 = 58.95%.
  - extra counted on touched tiles + 60 random untouched LABs per design; an unused mux whose bits read as one known source.
  - per type, matched / missing / wrong: LE inputs 74,574 / 2,571 / 3 (96.7%), LOCAL_INTERCONNECT 52,137 / 2,858 / 40 (94.7%), C4 48,444 / 2,798 / 17 (94.5%), R4 53,888 / 5,986 / 63 (89.9%), LE_BUFFER 20,823 / 7 / 0 (99.97%), FF pins 5,580 / 515 / 25 (91.2%), LAB_CONTROL_MUX 1,234 / 209 / 7 (85.1%), C16 1,877 / 1,238 / 21 (59.9%), R24 1,681 / 989 / 9 (62.8%).
  - not covered (zero / no table): clock tree (BLK_CLK_BUF 1 / 2,440, LAB_CLK 93 / 445, SCLK_TO_ROWCLK_BUF 7 / 478, GLOBAL_CLK_*), IO (IO_DATAIN 195 / 327, IOOBUF 5 / 379, BLOCK_INPUT_MUX 307 / 80). Most of the remaining misses are 'ambiguous pattern' (two sources share a pooled pattern): per-column tables resolve those.
- IO sites (`cycloneiv_io_bits.py`, no geometry needed): each used IOOBUF site has a 36-bit configuration signature (set in >= 95% of designs using the site, in <= 3% of the others), in clusters of 4 consecutive v. Top-row (Y91) and bottom-row (Y0) IO config sits in the periphery frames (e.g. X26/X30/X32/X34 -> frames 26..29), v falls by 136 per IO step of 7 in N (N2, N9, N16, N23). The LAB-column anchor model does not apply to IO rows, so IO-row routing tables (IO_DATAIN, BLOCK_INPUT_MUX, IOOBUF.I) need their own anchors.
- IO input sites: every used IOIBUF site has a 4-bit signature (4 consecutive v in one periphery frame), set in all designs using the site and in <= 3% of the others (249 sites with >= 12 uses; e.g. X26 Y91 N1 frame 26 v 380..383, N8 244..247, N15 108..111: v falls by 136 per N step of 7; left/right IO columns X117 carry the same pattern with frames 20..34). Some sites also show a bit beyond the lane model (v 6344+, the lane-tail columns).
- Memory: a per-column learner (104 columns instead of 8 classes) needs a larger cgroup than 2.5 GB.

## Lifter, emitter and functional gate (EP4CGX150, 2026-10-26)

- `lifters/cycloneiv_lift.py` (bitstream -> cells / nets), `lifters/cycloneiv_emit.py` (self-contained Verilog), `scripts/cycloneiv_lifted_sim_check.py` (gate), `scripts/cycloneiv_verify_all.py` (stages: LUT-mask decode 100% [blocking], routing score [reported], lifted-sim gate [blocking], NOT LIFTED list).
- Decoded from the bitstream (verified against the post-fit netlist):
  - LE used = LE bit (-8,-1) or a nonzero mask: 1004 of 1018 LEs on `gx150_sp_001` (14 pass-through LEs missed).
  - LUT mask 100% (5.35 M bits). Carry mode: the DATAC mux reads zero (CIN is a learnt source of that mux); 0 mode mismatches on `gx150_sp_001` (1004 LEs).
  - FF exists when an LE_BUFFER of the LE selects the register output and its mux reads nonzero (a zero mux is the idle code).
  - FF pins (CLK, CLRN, ENA, SCLR, SLOAD, ASDATA, D) are per-(LE, pin) mux groups; D reads the learnt pseudo source LUTOUT (own LUT) or a routed DATAD; constants are learnt pseudo sources CONST 0 / 1.
  - Clock inversion: LAB bit (-6,-30) from the tile anchor (Jaccard 0.85 over 5,442 clock lines, greedy); other control-pin inverters (60 CLRN, 1 ENA inverted in `gx150_sp_001`) are not decoded; `ffi` corpus built to find them.
- Register semantics follow the vendor primitive exactly (`PRIM_GDFF_LOW`): async clear is a level, a capture needs a clean 0 -> 1 edge (an X -> 1 edge is ignored), ena must be 1, state updates in the active region and q follows by a non-blocking assignment (`q_tmp` / `q_tmp_dly`). Using `posedge` and a plain non-blocking assignment gave a different power-up and race behaviour.
- Gate method: both netlists simulated with iverilog on the vendor cell models; stimulus: data first, clocks left X for 100 ps (an inverted clock goes X -> 1 and captures once with settled data), then one clock pulsed at a time (pulsing two clocks together races the register updates of one domain against the other); every LUT combout / cout and FF q of the post-fit netlist is compared by location. Boundary nets (pads, clock wires) are named from the RCF (naming only; no logic comes from the .vo).
- Race exclusion: a register whose asynchronous clear is driven by logic glitches at the clock edge in zero-delay simulation, differently in two correct models; `race_taint` excludes such registers and everything downstream and prints the count. The random generator now draws async clears from input pins only (`gx150_rb_*`, 150 designs, 0 excluded).
- Results with routing taken from the .vo (`--oracle`, isolates everything except routing decode): `gx150_rb_*` 8 / 8 designs PASS, points matched 7,773 / (7,773 + missing 0 + extra 0 + wrong 0) = 100%; `gx150_ffc_001` 74 / 74. These do not test the routing decode.
- Results with routing from the bitstream (pooled X mod 8 tables, 150 + 61 training designs): `gx150_rb_*` odd, 8 designs: 0 PASS, points matched 324 / (324 + missing 6,509 + extra 51 + wrong 940) = 4.1%. The cause is routing: 1,600-1,800 unresolved cell inputs per design, 'ambiguous driver' (a pooled pattern names more than one source; a few percent per hop compounds over 4-6 hops).

## Third-party image test pass (2026-10-26)

`scripts/cycloneiv_image_pass.py` (log `tmp/logs/cycloneiv_image_pass.log`): a third-party compressed GX150 image (read only, never copied) against 6 held-out Quartus corpus designs and a control (the image with its set bits shuffled inside every frame: same bits per frame, random v). Tables: pooled X mod 8 learner tables from 150 training designs. Image: 2,178,780 set bits of 39.4 M positions (5.5%).

| measure | image | control (shuffled) | corpus designs (6) |
|---|---|---|---|
| used LEs (mask != 0 or LE-used bit) of 149,760 | 89,283 (59.6%) | 131,771 (88%) | 804 .. 1,186 |
| active LABs of 9,360 | 7,077 | 9,359 | 109 .. 152 |
| constant masks (0000 / FFFF) | 0.000 | 0.016 | 0.000 |
| mask support 0 / 1 / 2 / 3 / 4 inputs | 0 / .093 / .089 / .317 / .501 | .016 / 0 / .002 / .093 / .890 | 0 / .03-.05 / .02-.05 / .11-.13 / .79-.82 |
| distinct masks | 3,077 | 7,153 | 539 .. 818 |
| most common masks | ff00 5,494, 9617 3,102, 698e 2,904, f0f0 2,370, f3c0 1,567 | 4000, 8000, 1000, 2000 (single-bit masks) | 6996, ff00, 9669, f0f0 |
| carry-form masks (top 8 of corpus arithmetic cells) | 11,337 (12.7% of used) | 0 | 5 .. 79 |
| routing: nonzero muxes in an active LAB | 54.2 | 47.2 | 50 .. 60 |
| routing: unknown share of nonzero muxes | 0.064 | 0.430 | 0.036 .. 0.042 |
| LE inputs the mask depends on that trace to one driver | 6,589 / 9,016 = 73.1% | 13 / 588 = 2.2% | 74% .. 82% |
| IO output sites with the full 36-bit signature | 16 | 0 | 11 .. 29 |
| IO input sites with the 4-bit signature | 21 | 0 | 17 .. 31 |
| set bits claimed by the decode | 90.1% (unclaimed 214,628) | 59.6% | 98.4% .. 98.7% |

- Verdict: logic, not noise. The control separates from the image on every measure (single-bit masks and 89% 4-input support; 43% of its nonzero routing muxes match no legal source; 2% of inputs trace to a driver); the image sits next to the corpus on the routing (6.4% unknown vs 3.6-4.2%) and tracing (73% vs 74-82%) measures and has real-logic mask structure (buffers `ff00` / `f0f0`, XOR3 / carry forms; 50% 4-input, rest small support).
- Used LEs 89,283 of 149,760 (59.6%); 7,077 of 9,360 LABs active. The 12.7% carry-form masks are a lower bound (the carry-mode bit itself is not decoded).
- Where the image differs from the corpus: more small-support functions (support <= 2: 18% vs 5-10%; support <= 3: 50% vs 18-21%), and 6.4% unknown routing patterns (constructs absent from the corpus: clock tree, M9K / multiplier neighbours, wide fan-in).
- Fan-out of sampled drivers (1..9+): image [2663, 385, 89, 43, 10, 14, 5, 1, 13]; corpus designs [235, 159, 109, 77, 59, 26, 9, 4, 2] (smaller, denser cones); the image shows a few high-fan-out nets (13 drivers with 9+ sinks).
- Combinational back-edges in the sampled cones are not a usable measure: the loop-free corpus designs give 0 .. 5,322 (wrong decoded edges), the image 8.
- IO edges (sites with a known signature): image outputs top 5, bottom 1, right 10; inputs top 7, bottom 2, right 12; none on the left edge (transceiver side). Only sites used >= 12 times in the corpus have a signature (176 output, 249 input of 456 pins).
- Claims: LUT-mask + used-bit positions cover 718,530 of the image's set bits (33%); routing-mux positions of every LAB 1,174,333 (54%); static bits 225,516; IO 1,940. The 9.9% unclaimed bits are blocks and nets outside the fabric tables (clock tree, IO routing, M9K, multipliers, PLL, transceivers).
- Not claimed: nothing here shows the logic is correct, only that its statistics match built designs; the lifter and gate are still open.

## Lift of a third-party GX150 image and pin-inverter status (2026-10-26)

`scripts/cycloneiv_lift_image.py` (log `tmp/logs/cycloneiv_lift_image.log`; 18 s, tables `rl_gx_m8f.json`, no asm tables). Counts below are what the lifter emits, not a correctness claim.

- Used LEs 89,283 of 149,760 (59.6%); LUTs 89,283; FFs 25,835.
- LUT inputs the mask depends on that do not trace to a driver: 246,878. Reasons: ambiguous driver 119,822; FF-pin `zero pattern` 69,960; FF-pin `unknown pattern` 25,348; R4 unknown 4,683 / zero 3,093; LCCOMB unknown 4,528; no LE_BUFFER table 3,631; C4 unknown 3,120.
- NOT LIFTED: 24,815 FF traces reached with no LE_BUFFER selecting the register; 80 comb-loop edges cut; carry chains entering at LE 0; M9K, multipliers, PLL, transceivers, clock tree, IO routing.
- Claimed-bit fraction 90.1% (unchanged, see above).
- Blocker: routing decode quality. Per-pip held-out learner score is 92% (missing 21,978 / extra 1,597 / wrong 201 of 306,754 on 20 designs) but a trace compounds 4-6 hops; on race-free corpus designs the bitstream-routed gate gives matched 333 / (333 + missing 6,489 + extra 88 + wrong 951) = 4.2%. With oracle (RCF) routing the same gate passes 100% (7,773 points; 74/74 FF-control designs). Per-column tables did not improve it (4.24%) and inflate FF false positives (394 vs 211).
- Pin inverters (clrn / ena / sclr / sload): not decodable from the LE window. Greedy 4-bit decision tables on 240 FF-control designs score 0..0.3% matched for the inverted labels (held-out missing 230..331 each). The inverters are not LE-local bits (LAB-wide control path, to be searched at LAB scope); `CycloneIVLift.pin_inverted` stays False. Clock inversion (LAB bit (-6,-30)) is decoded.
- The asm.ddb tables (previous section) do not replace the learner yet (issue #136).

Net-level routing experiments (one race-free held-out design, LE-input traces vs RCF truth: match / unresolved / wrong; learner `rl_gx_m8f`):
- baseline 1,091 / 841 / 37 (ambiguous driver 592, unknown R4 95, unknown C4 84).
- + driver-cell-must-be-used filter in the Tracer: 1,098 / 839 / 32 (ambiguous 570). Kept (`Tracer.valid`).
- + vendor asm tables first (`Decoder(asm=AsmSource())`): 555 / 1,380 / 34. Worse: an asm record has several RCF alias names, each walked as a separate branch; physical tracing needs routing.ddb fan-in (undecoded).
- + `--template` (row-phase-0 mux bits from other phases): no change in the phase-0 mux; the missing second bit row there is not a det/anyone bit. 1,021 / 924 / 24 with the retrained set (375 designs). Option kept, off by default.
- Ambiguous traces (570): the true driver is among the candidates in 374; candidate sets of 2: 156, of 10+: 219. Nearest-driver prior picks it 143 times and a wrong one 145 (86 ties): no usable prior.
- Cause of the ambiguity: sink groups in row phase 0 learn 5 mux bits where phases 1..3 learn 10, so 9 of 24 LE-input sources share one pattern.
- FF control pins read as unreadable (`zero pattern` / `unknown pattern`) are set to their idle constant in `lift_ff` (`des.assumed_idle`): gate 3.94% vs 4.02% without, no gain.
- Gate with decoded routing, 8 odd race-free designs: matched 307 / (307 + missing 6,593 + extra 21 + wrong 873) = 3.94%.

## Gaps

- Fabric not decoded:
  - FF fields: d / clk / clrn / ena / sclr / sload / asdata.
  - LAB-wide controls; routing (needed before LUT inputs can come from the bitstream instead of the `.vo`); IO buffers and standards; M9K; multipliers; PLL.
- Address model covers EP4CE6 LAB LEs only. Rows Y12..Y16 at X1 and the non-LAB columns are unmapped. Other dies untested.
- Periphery frames 1..r-1: no CRC found in-frame; how they are protected is unknown.
- Compressed length-field low bits; header lanes 0 and 3, lane 1 bits 0..23 and 36..37.
- Compressor not written.
- Encrypted Cyclone III LS streams: no oracle. Cyclone IV E/GX cannot encrypt ([fpga-encryption.md](fpga-encryption.md)).
