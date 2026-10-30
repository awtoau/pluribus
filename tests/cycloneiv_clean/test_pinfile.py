"""Official EP4CGX150 pin list vs our decoded package tables, and the unbonded-pad sets (#168, #172).  Skips without the vendor store / Quartus install."""
import os

import pytest

from lifters.cycloneiv_clean import pinfile as PF
from lifters.cycloneiv_clean import pkgpad as K


@pytest.fixture(scope="module")
def have():
    if not os.path.exists(PF.PATH):
        pytest.skip("pin file not in vendor store")
    try:
        K.pins(484)
    except Exception as e:  # noqa: BLE001
        pytest.skip(str(e))


@pytest.mark.parametrize("pkg", list(PF.PACKAGES))
def test_ball_table_matches_official(have, pkg):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
    import cycloneiv_clean_pin_xcheck as X
    res, _wrong = X.check(pkg)
    n = PF.PACKAGES[pkg][1]
    assert res == {"official": n, "ours": n, "matched": n, "missing": 0, "extra": 0, "wrong": 0}


def test_unbonded_io_pads_per_package(have):
    pads = K.pads()
    got = {}
    for pkg, (_c, n) in PF.PACKAGES.items():
        bonded = set(K.pin_pad(K.pins(n)).values())
        got[pkg] = sum(1 for j, p in enumerate(pads) if j not in bonded and p["strs"][3] in ("Row I/O", "Column I/O"))
    assert got == {"F896": 0, "F672": 82, "F484": 201}
