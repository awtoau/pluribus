"""M9K SDP / TDP decode (m9k_tdp.py, ram_mapper explicit modes, scripts/cycloneiv_clean_m9k_modes.py, #165, #169; ledger M-020..M-022)."""
import os
import sys

import numpy as np

from conftest import REPO

sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import m9k_tdp, ram_mapper as R       # noqa: E402


def test_tdp_tables_per_width():
    """Explicit modes 6..9 / 16..18 of the constructor tables: x18 has 18 data pins per port, x16 skips the parity lane idx 8, port-B data is type 4."""
    for W, n in ((18, 18), (16, 16), (9, 9), (8, 8), (1, 1)):
        ia, da, ib, db, aa, ab = m9k_tdp._tables(W)
        assert len(ia) == n and len(ib) == n
        assert all(ty == R.TYPE_DATA_B for _, ty, _ in R.entries_mode("RAM_MS_DATA_INPUT_B", R.TDP_MODE[W]) if ty != R.TYPE_ADDR_B)
    ia, *_ = m9k_tdp._tables(16)
    assert 8 not in ia


def test_sdp_x36_mode_identity():
    """Explicit mode 13 (x36 atom): data gi k = DATAIN idx k, address pin ix = gi ix (0..7)."""
    assert R.data_gi(36) == {k: k for k in range(36)}
    assert sorted((gi, ix) for gi, ty, ix in R.entries("RAM_MS_WRITE_ADDRESS_INPUT", 36)) == [(k, k) for k in range(8)]
    assert sorted((gi, ix) for gi, ty, ix in R.entries("RAM_MS_READ_ADDRESS_INPUT", 36)) == [(k, k) for k in range(8)]


def test_mode_classifier():
    import cycloneiv_clean_m9k_modes as M
    n = 5

    def mk(tdp, packed, data, datab, rd, we):
        ctl = {("RAM_USE_TRUE_DUAL_PORT_MODE", -1): np.array([[t] for t in tdp]), ("RAM_USE_PACKED_MODE", -1): np.array([[p] for p in packed])}
        return dict(ctl=ctl, data=np.array([[0 if d else -1] * 18 for d in data]), data_b=np.array([[0 if d else -1] * 18 for d in datab]),
                    read_groups=np.array(rd), we=np.array([0 if w else -1 for w in we]))
    m = mk([0, 1, 1, 1, 1], [0, 0, 0, 0, 0], [1, 0, 1, 1, 1], [0, 0, 0, 1, 0], [1, 0, 0, 0, 1], [1, 0, 1, 1, 1])
    assert M.modes(m, np.ones(n, bool)) == {0: "sdp", 1: "rom", 2: "single", 3: "tdp", 4: "tdp"}


def test_image_init_depth_and_bits():
    """Every modelled image tile: init list length == declared depth, and no content bit is dropped (needs env PLURIBUS_DJI_IMAGE; counts only)."""
    import pytest
    path = os.environ.get("PLURIBUS_DJI_IMAGE")
    if not path or not os.path.exists(path):
        pytest.skip("PLURIBUS_DJI_IMAGE not set")
    import cycloneiv_decompress as cd
    from lifters.cycloneiv_clean import emit
    plane = os.path.join(REPO, "tmp", "test_m9k_modes_plane.rbf")
    open(plane, "wb").write(cd.decompress(open(path, "rb").read(), {}))
    try:
        nl = emit.Builder(emit.Ctx(), plane, "image", 2).run()
    finally:
        os.remove(plane)
    mod = [M for M in nl.m9k if M.get("modelled")]
    assert len(mod) == len(nl.m9k)
    assert all(len(M["init"]) == 1 << M["A"] for M in mod)
    assert sum(int(M["content"].sum()) for M in nl.m9k) == sum(bin(v).count("1") for M in mod for v in M["init"])
