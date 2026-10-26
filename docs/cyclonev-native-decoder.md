# Cyclone V native decoder (Bluebird, Python)

Measured 2026-10-24, Quartus 25.1std.0 Lite, die e50f (`5CEBA4U19C8`), corpus = 236 designs in `corpus/cyclonev/` (+ their `bitstream.compressed.rbf`), commits on branch `worktree-agent-aa200cd2ba009c3cc`.

## What it is

- `.rbf` bytes in, `.bt` (m/o/r/s/i lines) out; the lifter reads it unchanged. No `mistral-cv`.
- `scripts/cyclonev_decode.py`: container (ORAM/PRAM/nibble-compressed CRAM fold), feature readers, `.bt` writer, `encode_rbf` (inverse).
- `scripts/cyclonev_native_tables.py`: bit-position / routing / geometry tables, cached in `tmp/cyclonev_native/<model>.pkl`.
  - Source = Mistral `data/` text + `libmistral/cv-rpats.cc` + `cvd-<die>.cc` (bootstrap, per `docs/bluebird.md`). Mistral binary not used.
  - No table was derived from Quartus fuzzing; every table field is verified against the oracle below.
- `scripts/cyclonev_native_overrides.py`: oracle-backed corrections (data, applied at decode time).
- `scripts/cyclonev_unpack.py --decoder native|mistral` (default native), `--crosscheck` runs Mistral and logs the diff.
- Native refuses non-`.rbf` containers (`ContainerError`; `--force` overrides). Dies with an HPS (sx50f, sx120f) are not supported.
- e50f exercised on the full corpus; second die gt150f (5CEBA7, die byte 0x13) on 18 designs, see docs/cyclonev-status.md. `--device auto` selects by die byte.

## Verification (three strengths kept apart)

Stages: `scripts/cyclonev_native_verify.py {diff,account,routes,logic,lutmap,roundtrip,probes,lift}`, `cyclonev_native_classify.py`. Logs `tmp/logs/`, results `tmp/cyclonev_native/results/*.json` (regenerable).

### 1. Decoded (structurally valid)

- 1,170,088 CRAM frames: CRC-16 1,170,088 valid; EDCRC 1,169,864 valid (4 MLAB-RAM designs, 224 frames, below).
- PRAM page CRC-16 15,104/15,104; option-frame checksum 236/236; frame sync bytes 236/236; postamble length 236/236.
- Frame header bits beyond sync: 0 set. Frame gap bytes: 0 set. Rows 24-31 frame slots (never loaded by libmistral): 0 set across 236 designs.
- Compressed vs uncompressed Quartus images of the same design (236 pairs): CRAM and PRAM planes identical; ORAM identical except COMPRESSION_DIS, usercode (JTAG_ID) and ~10 compression-linked bits in strip 5 (set varies per design, unclaimed).
- Nibble codec: re-encoding the decoded CRAM reproduces Quartus's compressed stream byte-for-byte (232/236; 4 = MLAB-RAM EDCRC case). Compressed image trailer after the stream is not regenerated (design-dependent field).

### 2. Identical to oracle (independent of Mistral)

Oracle = Quartus post-fit `.vo` atoms/conns and RCF routes (`corpus.db`, read-only). Headline = matched / (matched + missing + extra + wrong).

| field | matched | missing | extra | wrong | headline | held-out B |
|---|---|---|---|---|---|---|
| routing pips (RCF tree edges with a 1:1 native node) | 39,550 | 0 | 0 | 0 | 100% | 30,248/30,248 |
| routing nets (all mapped pips matched) | 8,019/8,019 | | | | 100% | 5,891/5,891 |
| LUT masks (logic) | 2,941 | 0 | 46 | 0 | 98.5% | 97.98% |
| LUT masks (arith) | 347 | 0 | 0 | 0 | 100% | 100% |
| ARITH_SEL per ALM | 185 | 0 | 0 | 0 | 100% | 100% |
| FF present (routed output + DFF=REG) | 2,752 | 42 | 0 | 0 | 98.5% | 98.3% |
| FF clock select non-OFF | 2,752 | 0 | 0 | 0 | 100% | 100% |
| FF clock inversion, clk0 / clk1 / clk2 (with overrides) | 1,591 / 642 / 519 | 0 | 0 | 0 | 100% | 100% |
| pin used + direction | 4,446 | 110 | 0 | 0 | 97.6% | 97.35% |
| IO bus_hold / open_drain vs GPIO bits | 4,556 / 1,556 | 0 | 0 | 0 | 100% | 100% |
| DSP present / mode (2 atoms) | 2 / 2 | 0 | 0 | 0 | 100% | |
| M10K present (18 atoms) | 18 | 0 | 0 | 0 | 100% | |

- Split: family-level (all width/dialect variants of a construct on one side), crc32 of family name; A = 117 designs, B = 119. Rules fit on A only and frozen:
  - RCF element type to native node type map (`learn_type_map`): 17 types learned on A; B scored with the A map.
  - ALM LUT address function per (half, mode, MLAB): re-learned from A by exhaustive search (`cyclonev_native_lutmap.py`); unique winner for D_E/D_F/C_E/C_F, E_x/F_x winners equal up to unused-input ambiguity; all remain consistent on B.
  - FF control rule (below): hypothesis picked on A, same pick scores 100% on B.
- Routing coverage: 39,573 RCF edges (50%) have an endpoint with no 1:1 native node (IO_* path elements 62k element mentions, clock-tree buffers, LAB_INPUT, GLOBAL_LOCAL_SEL, ROWCLKSEL, M20K_BUFFER, LEIMSEL, DSP_BUFFER). They are unscored, not matched.
- LUT extras (46): MLAB tiles used as RAM (`cyclonev_mlab_cell`): LUT_MASK lines carry RAM contents, there is no lcell.
- Rules found from the oracle (not in Mistral):
  - F_0/F_1 modes use the E_0/E_1 address function (drops the "unmodelled" LUT cases, 136 lcells).
  - FF slot 1 takes the opposite half's CLK_SEL / CLK*_INV (slot 0 the same half): 2,752/2,752, same-half only 1,769, other-half only 1,974.
  - LAB CLK0/1/2 select vs invert roles swapped (all three clocks, 1,591 / 642 / 519 FFs; as named: 69.7% / 40.7% / 37.8%).

### Differential vs fresh `mistral-cv decomp` (236 designs)

- Compat mode (`--no-overrides --mistral-compat`): m/o/r/s/i identical, 0 differences (m 236, o 708, r 41,851, s 46,388, i 10,198 lines).
- Default mode differences, all classified with the oracle:

| class | count | what | evidence |
|---|---|---|---|
| Mistral wrong | 107 r | GCLK to SCLK links omitted | RCF `GLOBAL_CLOCK -> SPINE_CLOCK` edge present |
| Mistral wrong | 15 r | LAB clock from fabric (CLKA/CLKB_SEL=DIN) has no link | RCF `BLOCK_INPUT_MUX -> GLOBAL_LOCAL_SEL` edge present |
| Mistral wrong | 726 s lines each side | CLK0/1/2 SEL and INV roles swapped | postfit clk inversion, 100% vs 40-70% as named; 12/12 fuzz probes (bit 10.44 = edge, 6.45 = fabric source) |
| neither provable | 1 r | RCLK to SCLK link (default mode only) | not in RCF |
| native wrong | 0 | | |

- The omissions are a libmistral type slip: `rmux_is_default(dnode)` passes an `rnode_coords` where an `rnode_index` is expected (converts via `bool` to index 1), so the SCLK / DCMUX skip tests one fixed node, not the mux in question. On e50f it is always true: no SCLK-destination link is ever printed.
- `s` differences are only the three clock pairs; option-name corrections are in the probes (below) but print no extra `o` line in the corpus (bits keep default).

### Opt corrections re-derived on fresh Quartus knob builds (`probes`, 32 builds, `scripts/cyclonev_native_probes.py`)

- RELEASE_CLEARS_BEFORE_TRI_STATES On flips only oram 6.2 (was named cvp_conf_done_en).
- ENABLE_DEVICE_WIDE_RESET On flips only 6.4 (name polarity `*_dis`); ENABLE_DEVICE_WIDE_OE On flips only 6.5; start_up_clock claimed 6.3/6.4/6.5 wrongly.
- ENABLE_CVP_CONFDONE On flips oram 0.5 (CvP bit located; not yet a named field).
- Edge/source probes: bit 10.44 equals the clock edge and bit 6.45 equals "clock from fabric DATAIN" in 12/12 builds.
- Usercode (oram strip 7, 8-38) changes with every config.

### 3. Lifted-consistent

- Lifter on native `.bt` vs on Mistral `.bt`: compat 236/236 identical; default native: LUT, FF, net, pad counts identical in 236/236, 0 unparsed lines, arcs +123 (the classified links above). The lifter's own FF D/CLK gaps are unchanged (not a decoder property).

## Whole-bitstream accounting (236 designs)

| space | set bits | claimed | unclaimed |
|---|---|---|---|
| CRAM (rows >= 32) | 37,575,812 | 37,575,804 | 8 |
| PRAM | 890,583 | 890,583 | 0 |
| ORAM | 238,723 | 21,839 | 216,884 (all equal to the die default; none differ) |

- CRAM by tile type (set / unclaimed): LAB 26,440,214 / 0; MLAB 9,295,301 / 8; M10K 1,723,277 / 0; DSP 36,841 / 0; empty columns 80,179 / 0.
- Claim classes: routing muxes, block muxes, inverters, forced-1 bits (`<die>-1.txt`, 12 bits per design, set in every design).
- Unclaimed 8: MLAB tile-relative (43,45), 2 per design in the 4 `c_ram_vnd_mlab_*` designs. Those 4 designs also have 224 frames whose EDCRC does not verify: the stored value equals the CRC with two extra bits (rows 89, 94 of MLAB column frames 774-837) that are not in the frame.
- 8 set bits are claimed by two features (double claim; same 4 designs, not resolved).
- Static: 11.2M of 19.3M loaded CRAM positions are read by some feature; the rest are never set in this corpus.
- Frame overhead (verified, not features): sync, EDCRC, CRC-16, option checksum, PRAM page CRC.

## Re-encode (claim 4)

- `encode_rbf(decode(x)) == x`: 232/236 uncompressed Quartus images byte-identical (the 4 MLAB-RAM designs differ only in the EDCRC words above).
- One-feature edit on every design: flip 1 LUT_MASK bit, encode, decode: exactly one `s` line changes (192 replaced, 44 created from default); all frame CRC-16/EDCRC valid after the edit; Mistral decode of the edited file shows the identical single-line change (236/236).
- Not checkable here: acceptance by a device (no hardware), Quartus has no `.rbf` reader.
- Not done: Quartus rebuild of a one-LUT-bit Verilog change compared to the edited bitstream.

## Known gaps

- FF presence, sclr and sload are 2794/2794 against the post-fit oracle. `sload` as a signal is not claimed (no corpus register has a non-constant `sload`).
- 110 pins missing: dedicated clock inputs (K17 x105, L17, N9, G11) reaching the fabric via clock muxes.
- 15 + 107 route links are classified above; the RCLK to SCLK link (1) is unconfirmed. ACLR source (DATAIN.3 default) has no explicit link.
- Unscored RCF edges: IO paths, clock tree buffers (50% of RCF edges).
- M10K width / mode fields, DSP beyond MODE, MLAB RAM bits (43,45), PLL, HMC, I/O standards: no oracle values in this corpus (I/O drive/slew/standard identical in all builds).
- opt: 6.3 name unverified (`bit_6_3_unverified`); CvP bit 0.5 unnamed.
- Single die, single Quartus version. HPS dies not supported. The tables remain Mistral-derived: fields without an oracle check inherit its errors.
