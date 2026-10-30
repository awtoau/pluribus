"""M9K control-pin edges (m9k_pia.py, #165): 12 RAM_PIA_TO_INPUT_YGR groups <-> 12 M4K_LEFT_CONTROL_INPUT records per tile; gate-confirmed on gxm9k_*."""
import numpy as np
import pytest

from lifters.cycloneiv_clean import asmdb_walk as W, ddb, m9k, m9k_pia, names


def test_pia_edges_per_tile():
    try:
        rt = ddb.Routing()
        walk = W.Walk()
    except (SystemExit, FileNotFoundError) as e:
        pytest.skip(str(e))
    imp = m9k_pia.Implicit(walk, rt, n_real=0)
    e_ctl = names.enum_of("M4K_LEFT_CONTROL_INPUT")
    enum = np.where(rt.tpl >= 0, rt.enum[np.maximum(rt.tpl, 0)].astype(np.int32), -1)
    x, y = m9k.columns()[0], 1
    n = int(((enum == e_ctl) & (rt.x == x) & (rt.y == y)).sum())
    assert n == m9k_pia.N_CTL
    assert len(imp.esrc) == len(imp.edst) > 0
    assert all(len(imp.eid[g][0]) >= 80 for g in range(m9k_pia.N_CTL))     # one edge per LOCAL_INTERCONNECT of the M9K tile (86 records)
