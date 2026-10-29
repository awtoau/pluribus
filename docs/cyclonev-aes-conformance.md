# Cyclone V AES-256 conformance check

Question: do the Cyclone V images the repo calls encrypted (`docs/fpga-encryption.md`) have the structure of Altera's AES-256 design-security output?
Scope: structure only. No decryption, no key handling, no licence workaround. Tool: `scripts/cyclonev_aes_conformance.py`, log `tmp/logs/cyclonev_aes_conformance.log`. Images are named by label in a local untracked JSON config.

## What static analysis of Quartus 25.1 Lite gives (own words, format-level only)

- Public docs (Cyclone V handbook vol. 1, design security section): AES-256, 256-bit user key, volatile or non-volatile key, tamper bit; order is compress then encrypt, device decrypts then decompresses. No bit layout, no mode, no IV.
- Quartus programming-file library `libpgm_pgmio_aes` (source file name `pgmio_non_vol_encryption.cpp`) implements AES-128 and AES-256 with two modes: CBC and CTR (OpenSSL EVP). Key-programming/non-volatile path; whether the same code encrypts the configuration stream is not established.
  - 256-bit path: input padded with 1-bits to a multiple of 128 bits; output length = whole 128-bit blocks; every 16-byte block is encrypted with its own 128-bit counter derived from a 64-bit IV value (not a chained mode).
  - Consequence if the same rule applies to the configuration stream: the encrypted run is a multiple of 16 bytes and a repeated plaintext block still gives a different ciphertext block.
- `libpgm_pgmio`: `PGMIO_F2P::encrypt` takes the chain's bit-vector queue; destination is sized `ceil(bits/128) * 16 + 256` bytes (128-bit granularity); it asserts a distinction between compressed and encrypted sections (`enc_cmp_is_enabled`). Per-device accessors `is_bitstream_encrypt_enabled`, `is_volatile_encryption`, `get_security_opt_no_pr`, `get_security_opt_no_jtag_key` read flags from the chain-element object; the mapping to option-RAM bit positions was not recovered (the decompile does not reach it).
- Not looked at (by decision): key derivation, key schedule, any key-handling path.

## Results, 7 images (2 die 0x05 air, 5 die 0x13 ground), run 2026-10-29

Controls first: 2 MB uniform random passes every statistic; the Quartus-compressed CRAM cut fails `cipher.uniform`, `cipher.no_leak`, `cipher.tail`.

| Check | Result (all 7 unless stated) | Numbers |
|---|---|---|
| `hdr.cleartext` | PASS | sync, option-RAM CRC16, all PRAM frames CRC16 valid |
| `pram.cleartext` | PASS | PRAM byte entropy 0.87-0.99 |
| `opt.flags` | INCONCLUSIVE | 44-50 of 72 Quartus-constant option bits differ, incl. 6.10, 6.36, 6.37; meaning undocumented |
| `len.field` | PASS | `(field+1428)/4` within 0.75 B of the non-0xFF extent |
| `len.container_pad` | PASS | everything after the stream is 0xFF |
| `len.block16` | FAIL 6 of 7, PASS 1 | length mod 16 from cipher start: 6, 6, 0, 7, 11, 1, 15; the single PASS is 1-in-16 chance |
| `cipher.uniform` | PASS | H >= 7.9999; byte/nibble/pair chi-square z within +-1.8 |
| `cipher.no_repeat16` | PASS | 0 duplicate 16-byte blocks at all 16 alignments (123k-297k blocks each) |
| `cipher.no_leak` | PASS | frame-marker 3-byte hits 0-1 (random expectation 0.35-0.85); no 16-byte 00/FF run |
| `cipher.tail` | PASS | 156-162 distinct values in last 256 B |
| pairs (21) | PASS | equal bytes 0.384-0.396% (random 0.391%); XOR entropy 7.9999-8.0000; 0 shared 16-byte blocks; first-64-byte matches 0-1 of 64 |
| `hdr.common_flags` | INCONCLUSIVE | 35 option bits identical in all 7 images and different from every Quartus stream (6.36, 6.37, 6.10, strip 3 and 4 bits) |

Reading:
- Consistent with a strong cipher in a non-repeating mode (no ECB signature, no shared keystream between same-die images, no fixed prefix, no plaintext markers).
- `len.block16` is the one finding that does not fit the Quartus padding rule above: 6 of 7 encrypted runs are not a 128-bit multiple.
  - Alternatives: the encrypted unit excludes a cleartext or differently padded tail; the configuration stream uses a stream mode with no padding; the images were not made by the Quartus encryptor.
  - Not distinguishable without a Quartus-encrypted reference.
- Random-looking bytes alone cannot separate AES from any other good cipher or a PRNG stream.

## Cannot be verified without a key or a Quartus-produced encrypted reference

- Which option bits mean encrypted / volatile / non-volatile key.
- Where the encrypted run starts and ends (so whether the 16-byte rule applies to it).
- Cipher mode and IV carriage for the configuration stream.
- Whether an authentication or CRC value sits inside the encrypted region (postamble CRCs would be inside the ciphertext).
- Whether the cipher is AES at all.
- Reference that would settle all of these: one encrypted `.rbf` from a Quartus edition entitled to design security (Lite refuses `--key`: Error 213052; not worked around), or `KEY_VERIFY` read from a board configured with the image.
