# Cyclone III / IV `.rbf` (E, GX, III LS)

Decoder: `scripts/cycloneiv_decompress.py` (`decompress(bytes) -> bytes`, CLI `--info`, `-o`).
Oracle: `quartus_cpf -c -o bitstream_compression=on|off X.sof out.rbf` (Quartus 25.1 Lite) on the vendor
SFL / SFL-enhanced / PFL `.sof` files shipped in `quartus/common/devinfo/programmer/`.

## Status (2026-10-24)

| Layer | Status | Evidence level |
|---|---|---|
| Container, header, frame CRC, compression | derived; decoder written | identical to oracle, 70 / 70 pairs |
| Fabric (LE LUT/FF bits, routing, IO) | **not started**: Quartus cannot fit Cyclone IV here | none |
| Lifter / schema | not written (gated on fabric decode) | — |

## Feasibility

- Installed Quartus 25.1 Lite has **Cyclone V device support only** (`quartus_sh --tcl_eval get_family_list` -> `{Cyclone V}`).
  - Cyclone IV needs `cyclone-25.1std.0.1129.qdz` (466 MB; manifest in `sources/README.md`). Lite licenses Cyclone IV E and GX. The download needs an Altera SSO sign-in.
  - Until it is installed: no `quartus_map/fit/asm` for any EP4C part, so no post-fit `.vo` oracle and no fuzzing.
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

## Gaps

- No fabric decode: Cyclone IV device support is not installed (see Feasibility). Once it is, the next step is a fuzz corpus: constants, LUT masks over one fixed LE, FF controls, IO standards. It would be built on the smallest die (EP4CE6, F=210) with the post-fit `.vo` as oracle (`scripts/cyclonev_vo_parse.py` pattern).
- Periphery frames 1..r-1: no CRC found in-frame; how they are protected is unknown.
- Compressed length-field low bits; header lanes 0 and 3, lane 1 bits 0..23 and 36..37.
- Compressor not written.
- Encrypted Cyclone III LS / IV streams: no oracle.
