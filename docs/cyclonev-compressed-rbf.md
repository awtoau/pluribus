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
- Encrypted streams: header and PRAM parse, CRAM does not. The decoder reports the coded-CRAM byte entropy (encrypted ≈ 8.0; Quartus-compressed CRAM ≤ 2.5 here). Evidence and open questions: [fpga-encryption.md](fpga-encryption.md).

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
- Encrypted (AES) streams: no oracle — Quartus 25.1 Lite refuses `--key` (`Error 213052: Design security feature is not enabled`). Which option bits mean "encrypted" is unconfirmed: see [fpga-encryption.md](fpga-encryption.md).
- Container `0xFF` padding beyond 1024 bytes is treated as padding and trimmed to a 32-bit boundary; the length field then follows the trimmed length, not the original Quartus file.
- `scripts/cyclonev_unpack.py` keeps the 0xFF preamble + sync, validates with this decoder and dies on a failed check (#114). Check: `scripts/cyclonev_unpack_check.py` -> 236/236 `.bt` identical to the stored `decomp.bt`.

## Encrypted bitstreams

Moved to [fpga-encryption.md](fpga-encryption.md) (all families, detection evidence, open questions).
