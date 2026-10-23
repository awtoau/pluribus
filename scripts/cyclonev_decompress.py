#!/usr/bin/env python3
"""Cyclone V compressed .rbf -> uncompressed .rbf, byte-identical to quartus_cpf's own output.

Format (docs/cyclonev-compressed-rbf.md), offsets relative to the 'jjjj' sync S:
- S-0x80..S   0xFF preamble.  S+4..S+0xa4 option RAM (32 strips x 40 bits, bit-transposed),
              S+0xa6 CRC16 of S+4..S+0xa6, then 0xFF fill.  Raw in both modes.
- PRAM frames (F bytes, CRC16 last 2) start at S+F-24; the last starts 2a c5 01.  Raw.
- Everything after: nibble-coded (low nibble first).  Key nibble k, then the nibbles k marks:
  bit0/1 = byte0 lo/hi, bit2/3 = byte1 lo/hi; unmarked nibbles are 0.  Runs to EOF, FF tail too.
- Option bits that differ: strip 6 bit 35 (1 = uncompressed); length field (strip 4 bits 0..6
  : strip 5 bits 16..39) = 4*(file length - 305) + 1 in an uncompressed file.  CRC16 recomputed.
Die-independent: frame sizes come from the CRC16 chain, not a device table.

Usage: python3.15t scripts/cyclonev_decompress.py in.rbf [-o out.rbf] [--info]
"""
import argparse
import collections
import math
import sys

SYNC = b"jjjj"
LAST_PRAM = bytes.fromhex("2ac501")
FIRST_CRAM = bytes.fromhex("843e01")
LAST_CRAM = bytes.fromhex("429f00")
# Nibble-key value count: popcount(k).
NV = [bin(k).count("1") for k in range(16)]
# Longest 0xFF tail quartus_cpf writes after the postamble (276..452 over 7 dies); more = padding.
MAX_FF_TAIL = 1024
# Encryption tell: coded CRAM entropy over the first 64 KiB (Quartus compressed: <= 2.5).
ENTROPY_PROBE = 1 << 16
ENCRYPTED_ENTROPY = 7.9


def _crc_table():
    t = []
    for i in range(256):
        a = i
        for _ in range(8):
            a = (a >> 1) ^ (0xA001 if a & 1 else 0)
        t.append(a)
    return t


CRC_T = _crc_table()


def crc16(b):
    """CRC-16/0xA001 reflected, init 0xFFFF, no xorout (Mistral cv-files.cc crc16)."""
    a = 0xFFFF
    for x in b:
        a = (a >> 8) ^ CRC_T[(a ^ x) & 0xFF]
    return a


def crc_ok(d, s, n):
    return s + n <= len(d) and crc16(d[s:s + n - 2]) == d[s + n - 2] | d[s + n - 1] << 8


class FormatError(ValueError):
    pass


def find_sync(d):
    """(sync offset, bit shift).  Shift != 0 = stream misaligned by that many bits (LSB-first)."""
    n = 0
    while n < len(d) and d[n] == 0xFF:
        n += 1
    if d[n:n + 4] == SYNC:
        return n, 0
    window = int.from_bytes(d[n:n + 8], "little")
    for sh in range(1, 8):
        if ((window >> sh) & 0xFFFFFFFF).to_bytes(4, "little") == SYNC:
            return n, sh
    raise FormatError(f"no 'jjjj' sync after {n} bytes of 0xFF preamble (first bytes "
                      f"{d[n:n + 8].hex()}): not a Cyclone V .rbf in this format")


def realign(d, shift):
    """Drop `shift` leading bits (LSB-first) and pad the end with 1s."""
    v = int.from_bytes(d, "little") >> shift
    v |= ((1 << shift) - 1) << (8 * len(d) - shift)
    return v.to_bytes(len(d), "little")


def oram_strip(d, s, strip):
    v = 0
    for bit in range(40):
        if d[s + 4 + (strip >> 3) + (bit << 2)] & (0x80 >> (strip & 7)):
            v |= 1 << bit
    return v


def oram_set(d, s, strip, value):
    for bit in range(40):
        o = s + 4 + (strip >> 3) + (bit << 2)
        m = 0x80 >> (strip & 7)
        d[o] = (d[o] | m) if (value >> bit) & 1 else (d[o] & ~m)


def length_field(d, s):
    """31-bit length field: strip 4 bits 0..6 (high) : strip 5 bits 16..39 (low)."""
    return (oram_strip(d, s, 4) & 0x7F) << 24 | oram_strip(d, s, 5) >> 16


def set_length_field(d, s, v):
    oram_set(d, s, 4, oram_strip(d, s, 4) & ~0x7F | (v >> 24) & 0x7F)
    oram_set(d, s, 5, oram_strip(d, s, 5) & 0xFFFF | (v & 0xFFFFFF) << 16)


def fix_header(d, s, length):
    """Header of the uncompressed file of `length` bytes: flag, length field, CRC16."""
    oram_set(d, s, 6, oram_strip(d, s, 6) | 1 << 35)
    set_length_field(d, s, 4 * (length - 305) + 1)
    c = crc16(d[s + 4:s + 0xA6])
    d[s + 0xA6], d[s + 0xA7] = c & 0xFF, c >> 8


def parse_header(d):
    """Return dict: sync, pram_frame, pram_frames, cram_start, compressed."""
    s, sh = find_sync(d)
    if sh:
        raise FormatError(f"stream is shifted by {sh} bits; realign() first")
    if not crc_ok(d, s + 4, 0xA4):
        raise FormatError(f"option-RAM CRC16 mismatch at {s + 0xa6:#x}")
    compressed = not (oram_strip(d, s, 6) >> 35) & 1
    # PRAM frame size F: the frame at S+F-24 must carry a valid CRC16, preceded by 0xFF fill.
    fill = s + 0xA8
    for f in range(0xC0, 0x4000, 4):
        p = s + f - 24
        if p + 2 * f > len(d) or d[fill:p].strip(b"\xff"):
            break
        if crc_ok(d, p, f) and crc_ok(d, p + f, f):
            break
    else:
        raise FormatError("no PRAM frame size gives a valid CRC16 chain")
    if p + 2 * f > len(d) or d[fill:p].strip(b"\xff"):
        raise FormatError("PRAM frame size not found")
    n = 0
    while True:
        q = p + n * f
        if not crc_ok(d, q, f):
            raise FormatError(f"PRAM frame {n} at {q:#x}: CRC16 mismatch")
        n += 1
        if d[q:q + 3] == LAST_PRAM:
            break
    return {"sync": s, "pram_frame": f, "pram_frames": n, "cram_start": p + n * f,
            "compressed": compressed}


def nibble_decode(src):
    """Decode the key/nibble stream to EOF.  Returns (bytes, leftover nibbles)."""
    nib = bytearray(2 * len(src))
    nib[0::2] = bytes(b & 15 for b in src)
    nib[1::2] = bytes(b >> 4 for b in src)
    out = bytearray()
    i, n = 0, len(nib)
    while i < n:
        k = nib[i]
        if k == 0:
            # zero keys dominate: emit the whole run at once
            j = i
            while j < n and nib[j] == 0:
                j += 1
            out += bytes(2 * (j - i))
            i = j
            continue
        if i + 1 + NV[k] > n:
            break
        i += 1
        v0 = v1 = 0
        if k & 1:
            v0 = nib[i]; i += 1
        if k & 2:
            v0 |= nib[i] << 4; i += 1
        if k & 4:
            v1 = nib[i]; i += 1
        if k & 8:
            v1 |= nib[i] << 4; i += 1
        out.append(v0)
        out.append(v1)
    return bytes(out), n - i


def entropy(b):
    n = len(b)
    return -sum(c / n * math.log2(c / n) for c in collections.Counter(b).values() if c)


def cram_check(u, start, raw=None):
    """Walk the uncompressed CRAM frames by CRC16.  Returns (frame bytes, frame count).
    `raw` = the coded CRAM bytes, used only to explain a failure."""
    if u[start:start + 3] != FIRST_CRAM:
        msg = f"first CRAM frame marker {u[start:start + 3].hex()} != 843e01"
        if raw:
            e = entropy(raw[:ENTROPY_PROBE])
            msg += f"; coded CRAM byte entropy {e:.3f} bits/byte"
            if e > ENCRYPTED_ENTROPY:
                msg += " (Quartus-compressed CRAM <= 2.5): looks encrypted"
        raise FormatError(msg)
    for g in range(64, 0x10000, 4):
        if crc_ok(u, start, g) and crc_ok(u, start + g, g):
            break
    else:
        raise FormatError("no CRAM frame size gives a valid CRC16 chain")
    n = 0
    while True:
        q = start + n * g
        if not crc_ok(u, q, g):
            raise FormatError(f"CRAM frame {n} at {q:#x}: CRC16 mismatch")
        n += 1
        if u[q:q + 3] == LAST_CRAM:
            return g, n


def decompress(data, info=None):
    """Compressed Cyclone V .rbf -> uncompressed .rbf.  Uncompressed input is returned as-is.
    `info` (dict) receives what was found: offsets, frame sizes and counts, shift."""
    info = {} if info is None else info
    s, sh = find_sync(data)
    info["shift_bits"] = sh
    if sh:
        data = realign(data, sh)
    h = parse_header(data)
    info.update(h)
    info["idcode_byte"] = f"{(oram_strip(data, h['sync'], 6) >> 19) & 0xFF:02x}"
    if not h["compressed"]:
        info["note"] = "already uncompressed (option strip 6 bit 35 set)"
        cram_info(data, h, info)
        return bytes(data)
    body, left = nibble_decode(data[h["cram_start"]:])
    if left and data[-1] != 0xFF:
        raise FormatError(f"{left} nibbles left over at EOF (truncated key group)")
    out = bytearray(data[:h["cram_start"]]) + body
    ff = len(out) - len(out.rstrip(b"\xff"))
    if left or ff > MAX_FF_TAIL:
        # Container padding (flash image), not Quartus output: keep the stream through the
        # postamble, then 0xFF to the next 32-bit boundary.
        del out[len(out) - ff:]
        out += b"\xff" * (-len(out) % 4)
        info["trimmed_ff_tail"] = ff
    s = h["sync"]
    info["compressed_length_field"] = length_field(data, s)
    fix_header(out, s, len(out))
    cram_info(out, h, info, data[h["cram_start"]:])
    return bytes(out)


def cram_info(u, h, info, raw=None):
    g, n = cram_check(u, h["cram_start"], raw)
    end = h["cram_start"] + g * n
    info.update(cram_frame=g, cram_frames=n, cram_end=end, length=len(u))
    tail = u[end:].rstrip(b"\xff")
    if tail[:2] != b"\xec\x64":
        raise FormatError(f"postamble marker {tail[:2].hex()} != ec64 at {end:#x}")
    a = tail.find(b"\xae\xfb", 2)
    if a < 0 or not crc_ok(tail, 0, a) or not crc_ok(tail, a, len(tail) - a):
        raise FormatError("postamble CRC16 mismatch")
    info["postamble"] = (a, len(tail) - a)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rbf")
    ap.add_argument("-o", "--out")
    ap.add_argument("--info", action="store_true", help="print the structure found")
    ap.add_argument("--realign-only", action="store_true",
                    help="only undo a bit shift of the whole stream (e.g. an encrypted image)")
    a = ap.parse_args()
    data = open(a.rbf, "rb").read()
    if a.realign_only:
        s, sh = find_sync(data)
        print(f"sync {s}, shift {sh} bits")
        if a.out:
            open(a.out, "wb").write(realign(data, sh) if sh else data)
        return 0
    info = {}
    try:
        out = decompress(data, info)
    except FormatError as e:
        print(f"{a.rbf}: {e}", file=sys.stderr)
        return 2
    if a.info or not a.out:
        for k, v in info.items():
            print(f"{k}: {v}")
    if a.out:
        open(a.out, "wb").write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
