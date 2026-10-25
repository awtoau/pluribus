# Cyclone V compressed `.rbf`

Decoder: `scripts/cyclonev_decompress.py` (`decompress(bytes) -> bytes`, CLI `--info`, `-o`).
Oracle: `quartus_cpf -c [-o bitstream_compression=on] build.sof out.rbf` (Quartus 25.1 Lite);
the only difference between the two runs is the compression option.

## Format

Offsets relative to the `jjjj` sync `S` (`S = 0x80` in every Quartus file).

| Region | Bytes | Coding |
|---|---|---|
| preamble | `0xFF` x 0x80 | raw |
| sync | `6a6a6a6a` at `S` | raw |
| option RAM | `S+4 .. S+0xa4`: 32 strips x 40 bits, bit-transposed (byte `S+4+(strip>>3)+4*bit`, mask `0x80>>(strip&7)`); `S+0xa4..a6` = 0 | raw |
| option CRC | `S+0xa6`: CRC16 (poly 0xA001 reflected, init 0xFFFF) of `S+4..S+0xa6`, little-endian | raw |
| fill | `0xFF` to `S+F-24` | raw |
| PRAM | frames of `F` bytes, CRC16 in the last 2; last frame starts `2a c5 01` | raw |
| CRAM | frames of `G` bytes, CRC16 last 2; first starts `84 3e 01`, last `42 9f 00` | coded |
| postamble | `ec 64` + zeros + CRC16; `ae fb` + 8 zeros + CRC16 | coded |
| tail | `0xFF` | coded |

- **Coding** (CRAM to EOF): nibble stream, low nibble of each byte first. Per 2 output bytes: one key nibble `k`, then the nibbles `k` marks, in order: bit0 = byte0 low, bit1 = byte0 high, bit2 = byte1 low, bit3 = byte1 high. Unmarked nibbles are 0.
  - Same scheme Project Mistral implements (`rbf_load` / `rbf_save`).
  - Quartus sometimes marks a zero nibble as present (`k=14` then `0`): its encoder is not pure zero-suppression, so a re-encoder will not reproduce Quartus byte-for-byte without that rule.
  - The `0xFF` tail is coded too (`f ffff` per 2 bytes); decoding to EOF gives the exact uncompressed length on every pair.
- **Option bits that change with compression** (everything else in the header and PRAM is byte-identical):
  - strip 6 bit 35 = `COMPRESSION_DIS` (1 = uncompressed).
  - length field = strip 4 bits 0..6 (high) : strip 5 bits 16..39 (low). Strip 4 bits 0..2 seen set (dies over 4 MB); bits 3..6 assumed.
    - uncompressed: `4*(file length - 305) + 1`, all 7 dies, 254/254 files.
    - compressed: `4*len - field` = 1428 (246 files) or 1427 (8 files, SFL only); what sets the low bit is not derived.
  - CRC16 at `S+0xa6` recomputed.
- **Die fingerprint without a device table**: strip 6 bits 19..26 = IDCODE byte (`0x02BXX0DD` -> `XX`), plus PRAM geometry (`F` x frame count) and CRAM frame count.
- Frame sizes are found from the CRC16 chain, so the decoder needs no per-die table.
- A stream shifted by whole bits (e.g. one extra leading `0xF` nibble from a container) is detected from the sync and realigned (`--realign-only` to do only that).
- Encrypted streams: header and PRAM parse, CRAM does not. The decoder reports the coded-CRAM byte entropy (encrypted ≈ 8.0; Quartus-compressed CRAM ≤ 2.5 here). Evidence and open questions: "Encrypted bitstreams" below.

## Per-die geometry (Quartus SFL `.sof` per die, `quartus_cpf` only)

| IDCODE | IDCODE byte | PRAM | CRAM start | uncompressed bytes |
|---|---|---|---|---|
| 02B010DD | 01 | 85 x 460 | 39,664 | 1,813,864 |
| 02B020DD, 02B120DD, 02B220DD | 02 / 12 / 22 | 56 x 700 | 40,004 | 4,244,820 |
| 02D010DD, 02D110DD | 01 / 11 | 56 x 700 | 40,004 | 4,244,820 |
| 02B030DD, 02B130DD | 03 / 13 | 58 x 916 | 54,148 | 7,020,944 |
| 02D020DD, 02D120DD | 02 / 12 | 43 x 916 | 40,408 | 7,007,204 |
| 02B040DD, 02B140DD | 04 / 14 | 38 x 1276 | 49,868 | 12,858,972 |
| 02B050DD, 02B150DD | 05 / 15 | 64 x 524 | 34,164 | 2,632,660 |
| 02D030DD, 02D130DD | 03 / 13 | 36 x 1516 | 56,196 | 23,237,960 |

- 02B050DD row = the corpus part 5CEBA4U19C8: 4,958 CRAM frames x 524 B; 2,632,660 B = 21,061,280 bits (datasheet E-A4 size).
- IDCODE byte alone is ambiguous across 02B/02D (both use 01..03); PRAM geometry separates them.

## Evidence

Measured 2026-10-24 on base commit `b7d1ce7f0`, Quartus 25.1std.0 Lite (`scripts/cyclonev_decompress_check.py`, log `tmp/logs/cyclonev_decompress_check.log`).

| Set | Pairs | `decompress(c) == u` | Uncompressed passes through |
|---|---|---|---|
| corpus/cyclonev, 5CEBA4U19C8, `.sof` re-made by `quartus_asm` from the stored fit DB (no map/fit) | 236 | 236 / 236 | 236 / 236 |
| Quartus SFL `.sof`, 18 files, 7 dies | 18 | 18 / 18 | 18 / 18 |

- Pairs: `scripts/cyclonev_compressed_pairs.py` (corpus; `--sfl` for the per-die set). The re-assembled uncompressed `.rbf` must equal the stored corpus `bitstream.rbf` before a pair is kept.
- Unit test: `tests/test_cyclonev_decompress.py` on a 36 KB cut of one corpus pair (`scripts/cyclonev_compressed_fixture.py`).

- Every decoded file also passes the structural checks: all PRAM and CRAM frame CRC16s, `843e01` / `429f00` frame markers, both postamble CRC16s.
- Corpus compression ratio 29.0-29.2% (764-770 KB of 2,632,660 B): small designs, mostly zero CRAM.

## Gaps

- Compressed-side length field low bit (1427 vs 1428 above) not derived; the decoder never needs it.
- Compressor not written; Quartus' explicit-zero-nibble choices not modelled.
- Encrypted (AES) streams: no oracle — Quartus 25.1 Lite refuses `--key` (`Error 213052: Design security feature is not enabled`). Which option bits mean "encrypted" is unconfirmed: see "Encrypted bitstreams".
- Container `0xFF` padding beyond 1024 bytes is treated as padding and trimmed to a 32-bit boundary; the length field then follows the trimmed length, not the original Quartus file.
- `scripts/cyclonev_unpack.py` keeps the 0xFF preamble + sync, validates with this decoder and dies on a failed check (#114). Check: `scripts/cyclonev_unpack_check.py` -> 236/236 `.bt` identical to the stored `decomp.bt`.

## Encrypted bitstreams

Question: is an image whose CRAM fails to decode encrypted, or mis-decoded? Detection only: no key handling, no key recovery, no licence workaround.
Tool: `scripts/cyclonev_encryption_probe.py` (sections `opt align stats pair`), log `tmp/logs/cyclonev_encryption_probe.log`, tests `tests/test_cyclonev_encryption_probe.py`.
Measured 2026-10-24 on base commit `8caf88fd5`; inputs are 4 third-party flash images (die byte 0x05 x2, 0x13 x2; never committed) against 254 Quartus 25.1 Lite streams (236 corpus + 18 per-die SFL, compressed and uncompressed) and 5 third-party Quartus-built streams from older toolchains (v0.11-v0.16, `.rbf` published by the vendor, in `tmp/thirdparty/`, gitignored).

### Verdict: ENCRYPTED (strong circumstantial; no oracle)

- Not a mis-decode: every alignment fails the CRC16 chain, header/PRAM are a valid compressed Cyclone V stream.
- Not plain Cyclone V coding: CRAM is statistically indistinguishable from uniform random at 2-4.7 MB.
- Not settled: no encrypted reference exists, so the option-bit meaning and the stream layout are inference.

| Test | Result | Strength |
|---|---|---|
| 4-bit shift (extra leading `0xF` nibble) | only shift 4 gives sync + option-RAM CRC16; PRAM 64 frames x 524 B CRC-valid after realign | structural |
| Shift persists into CRAM? | 8 bit offsets x 33 byte deltas x {nibble-coded, raw}, 272 trials per image, frame size 64..2048, 3 chained CRC16 frames: 0 hits. Same search on a Quartus stream hits at (0,0); on random bytes 0 hits | structural; detector validated |
| Byte entropy / chi-square | H = 7.9999-8.0; z (byte, nibble, byte-pair) all within +-1.8 over 2.0-4.7 MB; lag 1..16 autocorrelation <= 0.002; ones fraction 0.4998-0.5002 | statistical, strong |
| Same stats, Quartus CRAM | H 1.8-2.4; z 2.5e6..8.8e7 | control |
| Same stats, maximum-entropy zero-suppressed synthetic data (nibble density 0.05..1.0) | H <= 7.971 (density 0.4); byte z >= 2264, pair z >= 491 | control: no plain coding of any density looks uniform |
| Repeated 16-byte blocks | 0 duplicate aligned (123,595 blocks), 0 duplicate at any offset (first 2M windows); Quartus CRAM: 74-91% of aligned blocks repeat; Quartus PRAM 71-73% | not ECB |
| Two builds of one module, equal offsets | 0.3901% identical bytes (random 0.3906%); 0 identical 16-byte blocks at equal or any offset; XOR of the two CRAMs H = 7.9999 | no shared keystream/IV visible |
| PRAM | cleartext: valid CRC16, 97.4% of bytes equal a Quartus same-die PRAM, same statistics as Quartus PRAM | only CRAM is opaque |
| Header length field | `(field + 1428) / 4` equals the non-`0xFF` extent from file start within 0.5 B in all 4 images: the declared length covers the whole opaque stream, there is no `0xFF` tail and no extra block | structural |
| Granularity | stream length is not a multiple of 16 B from CRAM start (rem 6 B); one image ends on an odd nibble | weak; against ECB/CBC-with-padding, fits a keystream-style mode |

### Option RAM, image vs Quartus (die-independent bits)

Strip.bit as in "Format". Quartus = every one of 254 streams (+5 older-toolchain refs); the length field (strip 4 bits 0..6, strip 5 bits 16..39) and `jtag_id` (strip 7, 135 distinct values in Quartus) excluded. `compression_dis` (6.35) = 0 in the images, as in every Quartus compressed stream.

| Bits | Mistral name | Quartus (all 254 + 5 refs) | Images (4/4) |
|---|---|---|---|
| 6.36, 6.37 | - | 1, 1 | 0, 0 |
| 6.10 | - | 1 | 0 |
| 3.1, 3.3, 3.5, 3.7, 3.8 | - | 1 | 0 |
| 3.9..3.39 (31 bits) | `opt_b` | all 1 | 14-17 of 31 are 0; differs between images in 6-14 bits (the two builds of one module: 9) |
| 4.7..4.39 (33 bits) | `opt_b` | `1 0` then 31 x 1 | identical in all 4 images (two products, two dies): `01010101 10100111` then 17 x 0 |

- Strips 3 and 4 are bit-identical across Quartus 25.1 and the older third-party toolchains and across compressed/uncompressed: not a toolchain-version effect.
- 6.36/6.37 sit next to `compression_dis` (6.35, a `_dis` bit: 1 = feature off). If they are also `_dis` bits, 0 = on: fits two security features enabled. Hypothesis only.
- Strip 3's 31 varying bits are neither constant nor independent (pairwise 6-14 of 31 differ; random would give ~15): not a 128-bit IV. No bit pattern in the option RAM or the `0xFF` fill between option CRC and PRAM is large enough for an IV.
- Other strips that differ in the other-die images (0, 1, 13, 14, 15) track the die, not the flag.

### Public documentation position

- Cyclone V handbook vol. 1 (Configuration, Design Security) and AN 556: AES-256, hardware decryptor; Cyclone V uses one user 256-bit key (the other 256 bits are fixed in silicon); the key is never stored in the file.
- Order is compress, then encrypt; the device decrypts, then decompresses. FPP needs DCLK up to 4x the data rate with AES.
- Volatile/non-volatile key modes accept unencrypted files (board test) unless the tamper bit is set; no-key devices reject encrypted files. Key state is readable over JTAG with `KEY_VERIFY` (9-bit register for 28 nm: no key `000000000`, volatile `100011001`, non-volatile `011101000`).
- NOT documented anywhere found (handbook, AN 556, Mistral, `quartus_cpf --help`, public code search): position or polarity of any encryption/security option bit, IV or header block, cipher mode, encrypted frame layout. Mistral models `opt_a` / `opt_b` as opaque; its only encryption-named bit is the unrelated `cvp_data_encrypted`.
- A hobby script that wraps `quartus_cpf --key` claims "AES-256 CBC": unsourced.
- Copy of AN 556: `sources/altera/AN556_design_security.pdf` (manifest in `sources/README.md`).

### What would settle it (no bypass needed)

- One encrypted `.rbf` of any design built by a Quartus edition entitled to design security, compared bit-for-bit in the option RAM and CRAM start. Gives the flag bits, the layout, the granularity.
- `KEY_VERIFY` read from a board configured with the image: "key present" in the 9-bit register is device-side proof that the loaded image is the encrypted kind.
- Evidence in the host firmware of key programming (a key-load JTAG sequence) next to the image.
- Do not read the verdict as "AES by Quartus": a keyed scramble by the image's producer fits the same data.

### Lift realism (detection only)

- Tool: `scripts/lift_realism.py` (`lift`, `report`); control builder `scripts/cyclonev_random_control.py`; `scripts/cyclonev_unpack.py --allow-invalid` (statistics only, logs loudly, bypasses sync/CRC checks).
- Measured 2026-10-26: 256 Quartus corpus designs (re-lifted, current lifter) vs 3 random-CRAM controls vs 2 third-party opaque images, e50f die.
  - Separating metrics (corpus range -> control -> images): FF clock set 1.0 -> 0.37-0.41 -> 0.42; FF D driven 1.0 -> 0.49-0.76 -> 0.74-0.75; FF clock nets 1-2 -> 1277-1807 -> 1815-1824; sink nets with no driver 0 -> 0.29-0.31 -> 0.29-0.30; output pads driven 1.0 -> 0.15-0.29 -> 0.25-0.26; constant LUT masks <= 0.077 -> 0.58-0.69 -> 0.69-0.70.
  - Images lift to 8013-8227 LUTs / 9526-9720 FFs; nibble-coded random controls 8273-8382 / 9696-9745; largest corpus design 825 / 1040.
  - 8-9 of 9 discriminating metrics fall in the control range, 0 in the corpus range. Log: `tmp/logs/lift_realism.log`.
