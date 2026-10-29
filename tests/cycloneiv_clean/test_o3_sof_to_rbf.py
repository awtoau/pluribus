"""O3: plane.py's sof -> rbf closed form (incl. mask) vs quartus_cpf, bit-exact over all 39,040,976 CRAM cells.
Inputs: the vendor sfl sofs of the die and one seeded random-plane sof.  Skips without Quartus or the local mask table."""
import os

import numpy as np
import pytest

from conftest import REPO, report
from lifters.cycloneiv_clean import plane as P
from lifters.cycloneiv_clean import sofio as S

WORK = os.path.join(REPO, "tmp", "cycloneiv_clean")
CHUNK = 4_000_000


def compare(bits, got):
    bad = 0
    for a in range(0, P.N_BITS, CHUNK):
        i = np.arange(a, min(a + CHUNK, P.N_BITS), dtype=np.int64)
        r, j, k = P.sof_to_rbf(i)
        bad += int((got[r, j - 1, k] != bits[i]).sum())
    return bad


@pytest.fixture(scope="module")
def sofs(tables):
    try:
        S.quartus_bin()
    except S.VendorMissing as e:
        pytest.skip(str(e))
    os.makedirs(WORK, exist_ok=True)
    out = {}
    for name in ("sfl_ep4cgx150.sof", "sfl_enhanced_ep4cgx150.sof"):
        try:
            out[name] = S.programmer_sof(name)
        except S.VendorMissing as e:
            pytest.skip(str(e))
    rnd = os.path.join(WORK, "random_plane.sof")
    bits = np.random.default_rng(165).integers(0, 2, P.N_BITS, dtype=np.uint8)
    S.make_sof(out["sfl_ep4cgx150.sof"], rnd, bits)
    out["random_plane.sof"] = rnd
    return out


@pytest.mark.parametrize("name", ["sfl_ep4cgx150.sof", "sfl_enhanced_ep4cgx150.sof", "random_plane.sof"])
def test_o3_closed_form_bit_exact(name, sofs):
    rbf = os.path.join(WORK, name.replace(".sof", ".rbf"))
    S.to_rbf(sofs[name], rbf)
    bits = S.sof_bits(sofs[name])
    bad = compare(bits, S.rbf_cram(rbf))
    os.remove(rbf)
    report("O3", sof=name, set_bits=int(bits.sum()), cells=P.N_BITS, mismatching=bad)
    assert bad == 0


def test_o3_geometry_constants():
    assert P.BITS_PER_FRAME == 6344 and P.FRAMES == 6154 and P.N_BITS == 39_040_976
    assert P.ROWS * P.LANES == P.BITS_PER_FRAME
