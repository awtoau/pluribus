"""Pure-logic checks of scripts/cycloneiv_bit_hunter.py (no Quartus)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cycloneiv_bit_hunter as h  # noqa: E402


def test_pair_cells_signs():
    a, b = frozenset({10 * 2}), frozenset()          # a has key 10 set, b not
    assert h.pair_cells(a, b) == [(10, True)]
    assert h.pair_cells(b, a) == [(10, False)]
    r = frozenset({7 * 2 + 1})                       # a lacks key 7 that the base has
    assert h.pair_cells(r, frozenset()) == [(7, False)]
    assert h.pair_cells(frozenset(), r) == [(7, True)]


def test_step_toward_mask_one_bit():
    pa, pb = h.base_b(), {**h.base_b(), "kmask": "0007"}
    (st,) = h.step_toward(pa, pb)
    assert st["kmask"] == "0001"


def test_default_knobs_do_not_change_names():
    p = h.base_b()
    assert h.pname(p) == h.pname(dict(p))
    assert h.pname({**p, "seed": 2}) != h.pname(p)


def test_verilog_ties_every_port():
    v = h.verilog(h.base_params())
    assert v.count("(ina)") >= 7      # no mask may depend on an unconnected port
