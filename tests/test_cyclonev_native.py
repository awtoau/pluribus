"""Native Cyclone V decoder: codec and container unit tests; corpus round trip when corpus outputs exist."""
import os
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_decode as cd  # noqa: E402

CORPUS = [p for p in (os.path.join(REPO, "corpus", "cyclonev", "adder12", "bitstream.rbf"),
                      "/mnt/2tb/git/pluribus/corpus/cyclonev/adder12/bitstream.rbf") if os.path.exists(p)]
MISTRAL = os.path.exists(os.environ.get("PLURIBUS_MISTRAL_ROOT", "/mnt/2tb/git/mistral") + "/data/e50f-r.txt.xz")


def test_nibble_roundtrip():
    rng = np.random.default_rng(1)
    raw = bytes(rng.integers(0, 256, 4096, dtype=np.uint8) * (rng.random(4096) < 0.2))
    comp = cd.nibble_compress(raw)
    out, used = cd.nibble_decompress(np.frombuffer(comp, np.uint8), len(raw))
    assert out == raw


def test_crc16_table_matches_bitwise():
    rows = np.frombuffer(bytes(range(64)) * 2, np.uint8).reshape(2, 64)
    assert int(cd.crc16_rows(rows)[0]) == cd.crc16(bytes(rows[0]))


def test_garbage_is_rejected():
    if not MISTRAL:
        pytest.skip("mistral data not present")
    with pytest.raises(cd.ContainerError):
        cd.decode(b"\x6a" + b"\xf7" * 2_700_000)


@pytest.mark.skipif(not (CORPUS and MISTRAL), reason="corpus outputs / mistral data absent")
def test_corpus_roundtrip_byte_identical():
    data = open(CORPUS[0], "rb").read()
    m = cd.decode(data)
    assert cd.encode_rbf(m.t, m.bits) == data
    lines = m.bt_lines()
    assert lines[0].startswith("m 5CEBA4U19C8")
