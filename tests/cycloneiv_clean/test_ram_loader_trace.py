"""Pure helpers of scripts/cycloneiv_clean_ram_loader_trace.py (#165): SHA-1 constants vs a scrambled two-tile word layout, LUT dependency.  No image."""
import os
import random
import sys

from conftest import REPO

sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_ram_loader_trace as R  # noqa: E402


def test_sha1_match_recovers_a_wire_permutation():
    tg = R.SHA1_IV + R.SHA1_K
    perm = list(range(36))
    random.Random(7).shuffle(perm)           # word bit j -> physical position perm[j] (tile A 0..17, tile B 18..35)
    wa, wb = [], []
    for t in tg:
        phys = [0] * 36
        for j in range(32):
            phys[perm[j]] = (t >> j) & 1
        wa.append(sum(b << k for k, b in enumerate(phys[:18])))
        wb.append(sum(b << k for k, b in enumerate(phys[18:])))
    u, a, m, mp = R.sha1_match(wa, wb)
    assert m == 0 and u + a == 32
    assert all(perm[j] in mp[j] for j in range(32))


def test_sha1_match_rejects_other_data():
    rnd = random.Random(1)
    wa = [rnd.getrandbits(18) for _ in range(9)]
    wb = [rnd.getrandbits(18) for _ in range(9)]
    u, a, m, _ = R.sha1_match(wa, wb)
    assert m > 8


def test_lut_deps():
    assert R.lut_deps(0x0022) == [0, 1, 3]
    assert R.lut_deps(0xAAAA) == [0]
    assert R.lut_deps(0xFFFF) == []
