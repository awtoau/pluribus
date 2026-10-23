"""cyclonev_unpack.normalise: keeps the preamble, realigns, dies on any failed check (#114)."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import cyclonev_unpack as cu  # noqa: E402

FIX = os.path.join(HERE, "fixtures")


def read(name):
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


def test_flash_padding_before_preamble_is_dropped_preamble_kept():
    u = read("cv_fixture.rbf")
    assert cu.normalise(b"\xff" * 4096 + u) == u


def test_compressed_input_is_expanded():
    assert cu.normalise(read("cv_fixture.compressed.rbf")) == read("cv_fixture.rbf")


def test_stripped_preamble_dies():
    u = read("cv_fixture.rbf")
    with pytest.raises(SystemExit):
        cu.normalise(u[cu.PREAMBLE:])
    with pytest.raises(SystemExit):
        cu.normalise(u[cu.PREAMBLE - 16:])


def test_nibble_shifted_form_is_realigned():
    u = read("cv_fixture.rbf")
    n = len(u) + 64  # flash-style 0xFF behind it
    v = (int.from_bytes(u, "little") << 4) | 0xF | (((1 << (8 * n - 4 - 8 * len(u))) - 1) << (8 * len(u) + 4))
    out = cu.normalise(v.to_bytes(n, "little"))
    assert out[:cu.PREAMBLE + 4] == u[:cu.PREAMBLE + 4]
    assert out[0x128:].rstrip(b"\xff") == u[0x128:].rstrip(b"\xff")


@pytest.mark.parametrize("off,what", [(0x84 + 10, "CRC16"), (-600, "CRC16")])
def test_corruption_dies(off, what, capsys):
    u = bytearray(read("cv_fixture.rbf"))
    u[off] ^= 0x10
    with pytest.raises(SystemExit):
        cu.normalise(bytes(u))


def test_no_sync_dies():
    with pytest.raises(SystemExit):
        cu.normalise(b"\xff" * 0x80 + b"\x6a\xf7" * 64)
