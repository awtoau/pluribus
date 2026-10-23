"""Encryption-detection probe: a header+PRAM-valid image whose CRAM is random must be reported as
undecodable, and the CRC16-chain search must find the chain in a real stream but not in noise."""
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import cyclonev_decompress as cd  # noqa: E402
import cyclonev_encryption_probe as ep  # noqa: E402


def fixture():
    with open(os.path.join(HERE, "fixtures", "cv_fixture.compressed.rbf"), "rb") as f:
        return f.read()


def noisy_cram():
    c = fixture()
    h = cd.parse_header(c)
    rnd = np.random.default_rng(5).integers(0, 256, len(c) - h["cram_start"], dtype=np.uint8)
    return c[:h["cram_start"]] + bytes(rnd), h


def test_random_cram_is_reported_as_not_decodable():
    d, _ = noisy_cram()
    info = {}
    with pytest.raises(cd.FormatError, match="first CRAM frame marker"):
        cd.decompress(d + b"\xff" * 16, info)  # container padding, as in a flash image


def test_chain_search_finds_real_cram_not_noise():
    c = fixture()
    h = cd.parse_header(c)
    hits = ep.align_one(c, h["cram_start"], 0, 0, "coded", 1024)
    assert (0, 0, 0, 524) in hits
    d, h = noisy_cram()
    assert ep.align_one(d, h["cram_start"], 0, 0, "coded", 1024) == []
    assert ep.align_one(d, h["cram_start"], 0, -16, "raw", 1024) == []


def test_stats_separate_noise_from_zero_suppressed_data():
    rng = np.random.default_rng(9)
    noise = rng.integers(0, 256, 300_000, dtype=np.uint8)
    nib = rng.integers(1, 16, 600_000, dtype=np.uint8) * (rng.random(600_000) < 0.4)
    coded = np.frombuffer(ep.encode_zero_suppress(nib.astype(np.uint8)), dtype=np.uint8)
    assert abs(ep.stats_of(noise)["chi2_byte_z"]) < 5
    assert ep.stats_of(coded)["chi2_byte_z"] > 100
