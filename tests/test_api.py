"""Tests for the Netlist query API (api.py, issue #12).

Builds a small hand-made netlist in a fresh temp SQLite DB (schema.init() +
direct INSERTs — no pytrellis, no bitstream, no server) and exercises every
public Netlist method against known-good expected values.

Run with:
  python3 -m pytest tests/test_api.py -v
"""

import json
import os
import sys

import pytest
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Fixture: isolated SQLite DB, schema + fixture netlist loaded ─────────────

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite file, freshly initialised schema, and the
    hand-built fixture netlist below."""
    db_path = str(tmp_path / "pluribus.db")
    monkeypatch.setenv("PLURIBUS_DB_BACKEND", "sqlite")
    monkeypatch.setenv("PLURIBUS_SQLITE_PATH", db_path)

    import db
    db.BACKEND = "sqlite"
    db._SQPATH = db_path
    db._engine = None

    import schema
    schema.init()

    _load_fixture()

    yield db_path

    import db as _db
    _db._engine = None


def _eng():
    import db
    return db.engine()


def _load_fixture():
    """Insert a tiny but complete netlist covering every API method.

    Topology (forward reachability from n307):
        n307 --1--> n1 --2--> n2 --3--> n3
    FFs:
        ff_r1c1_A  d=n2            (reached at hop 2 via D)
        ff_r1c2_A  d=n3  ce=n1     (reached at hop 1 via CE — nearest)
    """
    eng = _eng()
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO bitstreams (label, filename, device, package) "
            "VALUES ('TEST','test.config','LCMXO2-1200','TQFP100')"))
        bs = c.execute(
            text("SELECT id FROM bitstreams WHERE label='TEST'")).fetchone()[0]

        # nets
        for n in ("n1", "n2", "n3", "n75", "n80", "n307"):
            c.execute(text("INSERT INTO nets (bitstream,name) VALUES (:b,:n)"),
                      {"b": bs, "n": n})

        # net_names: n307 -> JUPDATE
        c.execute(text(
            "INSERT INTO net_names (bitstream,net,name,confidence,source) "
            "VALUES (:b,'n307','JUPDATE','confirmed','pins_tsv')"), {"b": bs})

        # pad_map: an input pad (net_in) and an output pad (net_out only)
        c.execute(text(
            "INSERT INTO pad_map (bitstream,pin,label,direction,net_in,net_out) "
            "VALUES (:b,10,'ADC_D0A','in','n75',NULL)"), {"b": bs})
        c.execute(text(
            "INSERT INTO pad_map (bitstream,pin,label,direction,net_in,net_out) "
            "VALUES (:b,20,'OUT_A','out',NULL,'n80')"), {"b": bs})

        # efb_ports: JUPDATE -> n307
        c.execute(text(
            "INSERT INTO efb_ports (bitstream,port_name,net) "
            "VALUES (:b,'JUPDATE','n307')"), {"b": bs})

        # ffs
        c.execute(text(
            "INSERT INTO ffs (bitstream,cell,clk,ce,d,q,lsr) "
            "VALUES (:b,'ff_r1c1_A','clk0','1''b1','n2','qA','1''b0')"),
            {"b": bs})
        c.execute(text(
            "INSERT INTO ffs (bitstream,cell,clk,ce,d,q,lsr) "
            "VALUES (:b,'ff_r1c2_A','clk0','n1','n3','qB','1''b0')"),
            {"b": bs})

        # reachability: n307 -> n1(1), n2(2), n3(3)
        for dst, hops in (("n1", 1), ("n2", 2), ("n3", 3)):
            c.execute(text(
                "INSERT INTO reachability (bitstream,src,dst,min_hops) "
                "VALUES (:b,'n307',:d,:h)"), {"b": bs, "d": dst, "h": hops})

        # patterns + shift_reg_bits: one 2-bit shift register
        detail = json.dumps({"length": 2, "clk_net": "clk0", "ce_net": "1'b1",
                             "head_ff": "sr0", "tail_ff": "sr1"})
        pat_id = c.execute(text(
            "INSERT INTO patterns (bitstream,pattern_type,label,detail) "
            "VALUES (:b,'shift_reg','shift_reg_0',:d) RETURNING id"),
            {"b": bs, "d": detail}).fetchone()[0]
        for bi, (ff, q) in enumerate((("sr0", "q0"), ("sr1", "q1"))):
            c.execute(text(
                "INSERT INTO shift_reg_bits "
                "(pattern_id,bit_index,ff_cell,q_net,clk_net,load_en_net) "
                "VALUES (:p,:i,:f,:q,'clk0','1''b1')"),
                {"p": pat_id, "i": bi, "f": ff, "q": q})

        # a non-shift pattern too, so patterns() filtering is exercised
        c.execute(text(
            "INSERT INTO patterns (bitstream,pattern_type,label,detail) "
            "VALUES (:b,'const_ff','ff_x',:d)"),
            {"b": bs, "d": json.dumps({"stuck_value": "0"})})

        # spi_registers: register at 0x17
        bf = json.dumps([{"name": "enable", "bit": 0},
                         {"name": "mode", "bits": [2, 1]}])
        c.execute(text(
            "INSERT INTO spi_registers "
            "(bitstream,bank,address,name,description,bit_fields) "
            "VALUES (:b,'trigger',23,'TRIG_CFG','trigger config',:bf)"),
            {"b": bs, "bf": bf})


def _nl():
    import api
    return api.Netlist(bitstream="TEST")


# ── Construction ─────────────────────────────────────────────────────────────

def test_init_resolves_bitstream():
    nl = _nl()
    assert nl.label == "TEST"
    assert isinstance(nl.bs_id, int)


def test_init_unknown_bitstream_dies():
    import api
    with pytest.raises(SystemExit):
        api.Netlist(bitstream="NOPE")


# ── name() ───────────────────────────────────────────────────────────────────

def test_name_known():
    assert _nl().name("n307") == "JUPDATE"


def test_name_unknown_returns_none():
    assert _nl().name("n999") is None


def test_net_info():
    info = _nl().net_info("n307")
    assert info["name"] == "JUPDATE"
    assert info["confidence"] == "confirmed"
    assert info["source"] == "pins_tsv"


# ── net_for_pad() ────────────────────────────────────────────────────────────

def test_net_for_pad_input():
    assert _nl().net_for_pad("ADC_D0A") == "n75"


def test_net_for_pad_output():
    assert _nl().net_for_pad("OUT_A") == "n80"


def test_net_for_pad_unknown():
    assert _nl().net_for_pad("NO_SUCH_PAD") is None


def test_pad_for_net():
    pads = _nl().pad_for_net("n75")
    assert len(pads) == 1
    assert pads[0]["label"] == "ADC_D0A"


# ── efb_port() ───────────────────────────────────────────────────────────────

def test_efb_port():
    assert _nl().efb_port("JUPDATE") == "n307"


def test_efb_port_case_insensitive():
    assert _nl().efb_port("jupdate") == "n307"


def test_efb_port_unknown():
    assert _nl().efb_port("JNOPE") is None


def test_efb_ports_list():
    ports = _nl().efb_ports()
    assert {"port_name": "JUPDATE", "net": "n307"} in ports


# ── reachable() ──────────────────────────────────────────────────────────────

def test_reachable_nets():
    r = _nl().reachable("n307")
    assert [(e["net"], e["hops"]) for e in r] == [("n1", 1), ("n2", 2), ("n3", 3)]


def test_reachable_depth_limit():
    r = _nl().reachable("n307", depth=1)
    assert [e["net"] for e in r] == ["n1"]


def test_reachable_stop_at_ff():
    r = _nl().reachable("n307", stop_at="FF")
    by_cell = {e["ff_cell"]: e for e in r}
    # ff_r1c2_A is reached via CE=n1 at hop 1 (its nearest input)
    assert by_cell["ff_r1c2_A"]["hops"] == 1
    assert by_cell["ff_r1c2_A"]["pin"] == "CE"
    # ff_r1c1_A is reached via D=n2 at hop 2
    assert by_cell["ff_r1c1_A"]["hops"] == 2
    assert by_cell["ff_r1c1_A"]["pin"] == "D"
    # ordered nearest-first
    assert [e["ff_cell"] for e in r] == ["ff_r1c2_A", "ff_r1c1_A"]


def test_reachable_stop_at_ff_depth():
    # depth=1 only reaches n1 -> ff_r1c2_A via CE; ff_r1c1_A (needs n2) excluded
    r = _nl().reachable("n307", stop_at="FF", depth=1)
    assert [e["ff_cell"] for e in r] == ["ff_r1c2_A"]


def test_reachable_bad_stop_at():
    with pytest.raises(ValueError):
        _nl().reachable("n307", stop_at="LUT")


# ── taint_fwd() ──────────────────────────────────────────────────────────────

def test_taint_fwd_nets():
    assert _nl().taint_fwd("n307") == ["n1", "n2", "n3"]


def test_taint_fwd_ffs():
    assert _nl().taint_fwd("n307", stop_at="FF") == ["ff_r1c1_A", "ff_r1c2_A"]


# ── shift_registers() ────────────────────────────────────────────────────────

def test_shift_registers():
    srs = _nl().shift_registers()
    assert len(srs) == 1
    sr = srs[0]
    assert sr["label"] == "shift_reg_0"
    assert sr["length"] == 2
    assert sr["clk_net"] == "clk0"
    assert [b["ff_cell"] for b in sr["bits"]] == ["sr0", "sr1"]
    assert [b["bit_index"] for b in sr["bits"]] == [0, 1]


# ── patterns() ───────────────────────────────────────────────────────────────

def test_patterns_all():
    types = {p["pattern_type"] for p in _nl().patterns()}
    assert types == {"shift_reg", "const_ff"}


def test_patterns_filtered():
    ps = _nl().patterns(pattern_type="const_ff")
    assert len(ps) == 1
    assert ps[0]["detail"]["stuck_value"] == "0"


# ── spi_reg() ────────────────────────────────────────────────────────────────

def test_spi_reg():
    reg = _nl().spi_reg(0x17)
    assert reg["name"] == "TRIG_CFG"
    assert reg["bank"] == "trigger"
    assert reg["address"] == 0x17
    assert reg["bit_fields"][0]["name"] == "enable"


def test_spi_reg_unknown_returns_none():
    assert _nl().spi_reg(0x99) is None


def test_spi_regs_list():
    regs = _nl().spi_regs()
    assert len(regs) == 1
    assert regs[0]["name"] == "TRIG_CFG"
