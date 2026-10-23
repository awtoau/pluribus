"""Cyclone V compressed .rbf decoder on a small pair cut from a Quartus-built corpus design
(scripts/cyclonev_compressed_fixture.py; design c_ram_sv_16, 5CEBA4U19C8, Quartus 25.1 cpf)."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import cyclonev_decompress as cd  # noqa: E402

FIX = os.path.join(HERE, "fixtures")


def read(name):
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


def test_decompress_matches_quartus_bytes():
    info = {}
    assert cd.decompress(read("cv_fixture.compressed.rbf"), info) == read("cv_fixture.rbf")
    assert (info["pram_frames"], info["pram_frame"], info["cram_frame"]) == (64, 524, 524)
    assert info["idcode_byte"] == "05"


def test_uncompressed_passes_through():
    u = read("cv_fixture.rbf")
    info = {}
    assert cd.decompress(u, info) == u
    assert not info["compressed"]


def test_bit_shifted_stream_is_realigned():
    c = read("cv_fixture.compressed.rbf")
    # One extra 0xF nibble in front (LSB-first) moves the whole stream 4 bits; flash-style 0xFF
    # padding behind it.  The 0xFF tail is then container padding, trimmed to a 32-bit boundary.
    n = len(c) + 64
    v = (int.from_bytes(c, "little") << 4) | 0xF | (((1 << (8 * n - 4 - 8 * len(c))) - 1) << (8 * len(c) + 4))
    info = {}
    out = cd.decompress(v.to_bytes(n, "little"), info)
    assert info["shift_bits"] == 4
    # Strip-5 length field follows the trimmed length, so compare after the option RAM.
    assert out[0x128:].rstrip(b"\xff") == read("cv_fixture.rbf")[0x128:].rstrip(b"\xff")
    assert len(out) % 4 == 0 and cd.crc_ok(out, 0x84, 0xA4)


def test_corrupt_frame_is_rejected():
    c = bytearray(read("cv_fixture.compressed.rbf"))
    c[-600] ^= 0x10
    with pytest.raises(cd.FormatError):
        cd.decompress(bytes(c))


def test_not_cyclone_v():
    with pytest.raises(cd.FormatError, match="sync"):
        cd.decompress(b"\xff" * 32 + bytes.fromhex("6af7f7f7f7f7f7f3") + b"\x00" * 64)
