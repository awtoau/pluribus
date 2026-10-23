"""Cyclone III/IV compressed .rbf decoder on a synthetic stream built to the derived format
(docs/cycloneiv-bitstream.md).  Real pairs are vendor-.sof derived (third-party, not committed):
scripts/cycloneiv_decompress_check.py checks those, 70/70."""
import os
import random
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import cycloneiv_decompress as cd  # noqa: E402

F, PERIPH, CRAM = 210, 25, 40


def frame(rng, density):
    body = bytes(rng.randrange(256) if rng.random() < density else 0 for _ in range(F - 2))
    c = cd.crc16(body, cd.CRAM_INIT)
    return body + bytes([c & 0xFF, c >> 8])


def build(compressed_flag):
    rng = random.Random(7)
    hdr = bytearray([0x6A]) + bytearray(0xF0 | rng.randrange(8) for _ in range(cd.HDR)) + b"\0\0"
    d = bytearray(b"\xff" * cd.PREAMBLE) + hdr + b"\xff" * (F - len(hdr))
    d += bytes(rng.randrange(1, 256) for _ in range((PERIPH - 1) * F))
    for _ in range(CRAM):
        d += frame(rng, 0.1)
    d += b"\xff" * cd.POSTAMBLE
    s = cd.PREAMBLE
    cd.set_lane(d, s, 1, cd.lane(d, s, 1) & ~(1 << 35) | (0 if compressed_flag else 1 << 35))
    cd.set_length_field(d, s, 4 * (len(d) - 1))
    c = cd.crc16(d[s + 1:s + 1 + cd.HDR])
    d[s + 1 + cd.HDR], d[s + 2 + cd.HDR] = c & 0xFF, c >> 8
    return d


def encode(raw):
    """Zero-suppressing nibble coder (key = nonzero-nibble mask); odd tail = byte-0 nibbles only."""
    nib = []
    for i in range(0, len(raw), 2):
        pair = raw[i:i + 2]
        ns = [pair[0] & 15, pair[0] >> 4] + ([pair[1] & 15, pair[1] >> 4] if len(pair) == 2 else [])
        k = sum(1 << j for j, n in enumerate(ns) if n)
        if len(pair) == 1:
            k |= 12  # Quartus odd tail: key marks byte-1 nibbles the file never supplies
        nib += [k] + [n for n in ns if n]
    if len(nib) % 2:
        nib.append(15)  # a key with no nibbles after it: ignored at EOF
    return bytes(nib[i] | nib[i + 1] << 4 for i in range(0, len(nib), 2))


def compress(u):
    c = build(True)
    start = cd.PREAMBLE + PERIPH * F
    out = bytearray(c[:start]) + encode(u[start:])
    s = cd.PREAMBLE
    cd.set_length_field(out, s, 4 * len(out) - 5)
    cc = cd.crc16(out[s + 1:s + 1 + cd.HDR])
    out[s + 1 + cd.HDR], out[s + 2 + cd.HDR] = cc & 0xFF, cc >> 8
    return bytes(out)


def test_roundtrip_synthetic():
    u = bytes(build(False))
    info = {}
    assert cd.decompress(compress(u), info) == u
    assert (info["frame"], info["periphery_frames"], info["cram_frames"]) == (F, PERIPH, CRAM)


def test_uncompressed_passes_through():
    u = bytes(build(False))
    assert cd.decompress(u) == u


def test_container_ff_padding_trimmed():
    u = bytes(build(False))
    info = {}
    assert cd.decompress(compress(u) + b"\xff" * 4096, info) == u
    assert info["trimmed_ff_tail"] > 0


def test_bad_frame_crc_fails():
    u = bytearray(build(False))
    u[cd.PREAMBLE + (PERIPH + 3) * F + 5] ^= 1
    with pytest.raises(cd.FormatError):
        cd.decompress(bytes(u))
