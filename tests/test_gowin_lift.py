"""Tests for the GOWIN lifter (lifters/gowin_lift.py, first slice).

Two layers:
  * pure-logic: a small hand-built `.gwconfig` -> GowinLift.parse_config +
    recover_netlist, asserting the recovered LUT4s / DFFs and — critically —
    the LUT INIT bit-order convention (the #63-class trap).
  * DB round-trip: load that `.gwconfig` through load.load(..., lifter="gowin",
    fuzz=True) into a fresh temp SQLite DB and query it back via api.Netlist,
    mirroring tests/test_api.py's isolated-DB style.

Run with:
  python3 -m pytest tests/test_gowin_lift.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lifters.gowin_lift import GowinLift          # noqa: E402
from load import classify_lut                     # noqa: E402
from lifters import machxo2_lift as mx            # noqa: E402


# A tiny but complete design.  Node names are already-global (as
# scripts/gowin_unpack.py emits them); the lifter only unions the arcs.
#   LUT_AND4 = a & b & c & d   (INIT 0x8000 — the KNOWN-function bit-order anchor)
#   LUT_INV  = ~a              (INIT 0x5555)
#   DFF0     : D <- LUT_INV output, CE tied VCC, SR tied VSS, CLK routed
GWCONFIG = """\
# hand-built test gwconfig
.device GW1N-1
.tile 1 1 12
lut 1 1 LUT0 1000000000000000 A=nA B=nB C=nC D=nD F=nF0
lut 1 1 LUT1 0101010101010101 A=nINV B=- C=- D=- F=nF1
dff 1 1 DFF0 DFFS Q=nQ D=nF1 CLK=nCLK CE=nCE SR=nSR
arc 1 1 nA nSRC_A
arc 1 1 nB nSRC_B
arc 1 1 nC nSRC_C
arc 1 1 nD nSRC_D
arc 1 1 nINV nSRC_INV
arc 1 1 nCLK nSRC_CLK
arc 1 1 nCE VCC
arc 1 1 nSR VSS
arc 1 1 nSINK0 nF0
arc 1 1 nSINK1 nQ
hardip 1 1 ALU idx=0 mode=C2L F=nALU CIN=- A=- B=- C=- D=-
"""


@pytest.fixture
def gwconfig(tmp_path):
    p = tmp_path / "test.gwconfig"
    p.write_text(GWCONFIG)
    return str(p)


def _recover(gwconfig):
    lift = GowinLift("GW1N-1")
    pc = lift.parse_config(gwconfig)
    return lift, pc, lift.recover_netlist(pc)


def test_parse_counts(gwconfig):
    _lift, pc, _d = _recover(gwconfig)
    assert len(pc.luts) == 2
    assert len(pc.dffs) == 1
    assert len(pc.hardips) == 1
    assert pc.tile_type[(1, 1)] == "12"       # ttyp kept as a string
    assert len(pc.arcs) == 10


def test_recovered_luts_and_ffs(gwconfig):
    _lift, _pc, d = _recover(gwconfig)
    assert len(d.luts) == 2
    assert len(d.ffs) == 1
    by_name = {lt["name"]: lt for lt in d.luts}
    and4 = by_name["lut_r1c1_LUT0"]
    inv = by_name["lut_r1c1_LUT1"]

    # INIT strings are preserved verbatim (16-char MSB-first binary)
    assert and4["init"] == "1000000000000000"
    assert inv["init"] == "0101010101010101"

    # pluribus classify_lut agrees
    assert classify_lut(inv["init"]) == "INV(a)"
    assert classify_lut(and4["init"]) == "COMBO4"

    # every routed input resolved to a real net (not None), output driven
    for pin in ("a", "b", "c", "d"):
        assert and4[pin] and not and4[pin].startswith("1'b")
    assert and4["z"] and and4["z_used"]           # nF0 is consumed by an arc
    assert inv["a"] and inv["b"] is None          # only A routed

    # the DFF's D is the SAME net as the LUT_INV output (nF1 stitching)
    ff = d.ffs[0]
    assert ff["name"] == "ff_r1c1_DFF0"
    assert ff["q"] and not ff["q"].startswith("1'b")
    assert ff["d"] == inv["z"]
    assert not ff["clk"].startswith("1'b")        # CLK routed -> real net
    assert ff["ce"] == "1'b1"                     # tied VCC
    assert ff["lsr"] == "1'b0"                    # tied VSS
    assert ff["dtype"] == "DFFS"


def test_lut_init_bit_order_known_function(gwconfig):
    """The #63-class anchor: a LUT whose SOURCE function is a & b & c & d must
    recover as INIT 0x8000 AND evaluate to exactly a&b&c&d under the pluribus
    MSB-first convention (v = int(init,2); bit p = f(p), p = A+2B+4C+8D).

    A reversal/permutation bug would turn 0x8000 into 0x0001 (= ~a&~b&~c&~d),
    so this pins the bit-order end-to-end.  (0x8000 comes straight from
    apycula's decode — verified against its golden gowin_unpack -o output.)
    """
    _lift, _pc, d = _recover(gwconfig)
    and4 = next(lt for lt in d.luts if lt["name"] == "lut_r1c1_LUT0")
    v = int(and4["init"], 2)
    assert v == 0x8000

    def f(A, B, C, D):                            # recovered LUT as a function
        return (v >> (A + 2 * B + 4 * C + 8 * D)) & 1

    for A in (0, 1):
        for B in (0, 1):
            for C in (0, 1):
                for D in (0, 1):
                    assert f(A, B, C, D) == (A & B & C & D)

    # and lut_dependence sees all four inputs as functional
    assert sorted(mx.lut_dependence(and4["init"])) == ["a", "b", "c", "d"]


def test_inv_polarity_not_reversed(gwconfig):
    """INIT 0x5555 must classify as INV(a) — a reversed string would be 0xAAAA
    = BUF(a).  Guards the polarity half of the #63 trap."""
    _lift, _pc, d = _recover(gwconfig)
    inv = next(lt for lt in d.luts if lt["name"] == "lut_r1c1_LUT1")
    assert classify_lut(inv["init"]) == "INV(a)"
    assert classify_lut("1010101010101010") == "BUF(a)"    # the reversed form


def test_constants_resolve(gwconfig):
    """VCC/VSS nodes become 1'b1 / 1'b0 literals, not named nets."""
    _lift, _pc, d = _recover(gwconfig)
    lit_nets = {ff["ce"] for ff in d.ffs} | {ff["lsr"] for ff in d.ffs}
    assert "1'b1" in lit_nets and "1'b0" in lit_nets
    # neither literal leaked into the net list
    assert "1'b1" not in d.all_nets and "1'b0" not in d.all_nets


def test_alu_counted_not_emitted_as_logic(gwconfig):
    """ALU is preserved + counted but never emitted as a LUT (no wrong logic)."""
    _lift, _pc, d = _recover(gwconfig)
    assert d.n_alu == 1
    assert d.hardip_counts.get("ALU") == 1
    assert all("ALU" not in lt["name"] for lt in d.luts)


# ── DB round-trip (isolated temp SQLite, mirrors tests/test_api.py) ─────────

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


PINS_TSV = """\
# device:   GW1N-1
# package:  QN48
"""


def test_db_roundtrip(gwconfig, fresh_db, tmp_path):
    pins = tmp_path / "pins.tsv"
    pins.write_text(PINS_TSV)

    import load
    bs_id = load.load("GW_TEST", gwconfig, str(pins),
                      "GW1N-1", "QN48", fuzz=True, lifter="gowin")
    assert bs_id is not None

    import importlib
    import api
    importlib.reload(api)                 # bind api to the fresh engine
    nl = api.Netlist("GW_TEST")

    import schema
    from sqlalchemy import select, func
    with api.engine().connect() as c:
        n_luts = c.execute(select(func.count()).select_from(schema.luts)
                           .where(schema.luts.c.bitstream == nl.bs_id)).scalar()
        n_ffs = c.execute(select(func.count()).select_from(schema.ffs)
                          .where(schema.ffs.c.bitstream == nl.bs_id)).scalar()
        fns = {r[0] for r in c.execute(
            select(schema.luts.c.fn).where(schema.luts.c.bitstream == nl.bs_id))}
    assert n_luts == 2
    assert n_ffs == 1
    assert "INV(a)" in fns                # the LUT_INV recovered + classified
