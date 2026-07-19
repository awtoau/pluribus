"""Tests for the Anlogic EG4 (eagle_s20) lifter (lifters/anlogic_lift.py) — #67.

Two layers, mirroring tests/test_gowin_lift.py:
  * pure-logic: a small hand-built `.anloconfig` -> AnlogicLift.parse_config +
    recover_netlist, asserting the recovered tile grid + LUT4s and the LUT-init
    bit-order convention (the #63-class trap: a&b&c&d must stay 0x8000).
  * DB round-trip: load that config through the dedicated anlogic load path
    (load.load(..., lifter="anlogic")) into a fresh temp SQLite DB and query
    back the anlogic_tiles grid + luts.

Run with:
  python3 -m pytest tests/test_anlogic_lift.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lifters.anlogic_lift import AnlogicLift        # noqa: E402
from load import classify_lut                       # noqa: E402
from lifters import machxo2_lift as mx              # noqa: E402


# A tiny but complete config in the shape scripts/anlogic_unpack.py emits.
#   x1y1: an active plb with 3 LUTs —
#     LUT_AND4 = a & b & c & d   (INIT 0x8000, the bit-order anchor)
#     LUT_INV  = ~a              (INIT 0x5555)
#     LUT_ZERO = 0               (unconfigured — must be dropped, not a cell)
#   x1y2: an empty plb (occupancy 0)
ANLOCONFIG = """\
# hand-built test anloconfig
.device EG4S20BG256
.package BG256
.idcode 0x0a014c35
.sysconfig cfg1 0x21010500
.tile x1y1 plb 1 1 29 3784 31 54 137
.tile x1y2 plb 1 2 29 3730 31 54 0
.tile x0y0 pib 0 0 2 3838 27 54 5
lut x1y1 SLICE0 LUT0 1000000000000000
lut x1y1 SLICE0 LUT1 0101010101010101
lut x1y1 SLICE2 LUTF0 0000000000000000
"""


@pytest.fixture
def anloconfig(tmp_path):
    p = tmp_path / "test.anloconfig"
    p.write_text(ANLOCONFIG)
    return str(p)


def _recover(cfg):
    lift = AnlogicLift("EG4S20BG256")
    pc = lift.parse_config(cfg)
    return lift, pc, lift.recover_netlist(pc)


def test_parse_counts(anloconfig):
    _lift, pc, _d = _recover(anloconfig)
    assert pc.device == "EG4S20BG256"
    assert pc.package == "BG256"
    assert pc.idcode == "0x0a014c35"
    assert pc.sysconfig["cfg1"] == "0x21010500"
    assert len(pc.tiles) == 3
    assert len(pc.luts) == 3
    types = {t["type"] for t in pc.tiles}
    assert types == {"plb", "pib"}


def test_recovered_luts(anloconfig):
    _lift, _pc, d = _recover(anloconfig)
    # the all-zero LUT is dropped (unconfigured), leaving two real cells
    assert len(d.luts) == 2
    assert d.n_luts_nonzero == 2
    assert d.active_tiles == 2                       # x1y1 + x0y0 have occupancy
    assert d.tile_counts == {"plb": 2, "pib": 1}
    by_name = {lt["name"]: lt for lt in d.luts}
    inv = by_name["lut_x1y1_SLICE0_LUT1"]
    assert inv["init"] == "0101010101010101"
    assert classify_lut(inv["init"]) == "INV(a)"
    # each recovered LUT has a real output net; inputs unconnected (no routing)
    for lt in d.luts:
        assert lt["z"] and lt["z"].startswith("n")
        assert lt["a"] is None and lt["b"] is None


def test_lut_init_bit_order_known_function(anloconfig):
    """The #63-class anchor: a LUT whose function is a&b&c&d recovers as INIT
    0x8000 and evaluates to exactly a&b&c&d under the pluribus MSB-first
    convention (v = int(init,2); bit p = f(p), p = A+2B+4C+8D)."""
    _lift, _pc, d = _recover(anloconfig)
    and4 = next(lt for lt in d.luts if lt["name"] == "lut_x1y1_SLICE0_LUT0")
    v = int(and4["init"], 2)
    assert v == 0x8000

    def f(A, B, C, D):
        return (v >> (A + 2 * B + 4 * C + 8 * D)) & 1

    for A in (0, 1):
        for B in (0, 1):
            for C in (0, 1):
                for D in (0, 1):
                    assert f(A, B, C, D) == (A & B & C & D)
    assert sorted(mx.lut_dependence(and4["init"])) == ["a", "b", "c", "d"]


def test_no_routing_endpoints(anloconfig):
    """Routing is not decoded for anlogic — arc endpoint sets are empty."""
    lift, pc, _d = _recover(anloconfig)
    sources, sinks = lift.arc_endpoint_sets(pc)
    assert sources == set() and sinks == set()


# ── DB round-trip (isolated temp SQLite, mirrors tests/test_gowin_lift.py) ──────

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "pluribus.db")
    monkeypatch.setenv("PLURIBUS_DB_BACKEND", "sqlite")
    monkeypatch.setenv("PLURIBUS_SQLITE_PATH", db_path)
    import db
    db.BACKEND = "sqlite"
    db._SQPATH = db_path
    db._engine = None
    import schema
    schema.init()
    yield db_path
    db._engine = None


def test_db_roundtrip(anloconfig, fresh_db):
    import load
    bs_id = load.load("EG4_TEST", anloconfig, None,
                      "EG4S20BG256", "BG256", lifter="anlogic")
    assert bs_id is not None

    import importlib
    import api
    importlib.reload(api)
    nl = api.Netlist("EG4_TEST")

    import schema
    from sqlalchemy import select, func
    with api.engine().connect() as c:
        n_tiles = c.execute(select(func.count()).select_from(schema.anlogic_tiles)
                            .where(schema.anlogic_tiles.c.bitstream == nl.bs_id)).scalar()
        n_luts = c.execute(select(func.count()).select_from(schema.luts)
                           .where(schema.luts.c.bitstream == nl.bs_id)).scalar()
        types = {r[0] for r in c.execute(
            select(schema.anlogic_tiles.c.tile_type)
            .where(schema.anlogic_tiles.c.bitstream == nl.bs_id))}
        fns = {r[0] for r in c.execute(
            select(schema.luts.c.fn).where(schema.luts.c.bitstream == nl.bs_id))}
    assert n_tiles == 3
    assert n_luts == 2
    assert types == {"plb", "pib"}
    assert "INV(a)" in fns
