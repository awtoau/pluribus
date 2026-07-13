"""Smoke test for the SQLite backend.

Does NOT require pytrellis or a real bitstream.  Directly exercises:
  - schema.init() creates all tables in a fresh SQLite file
  - engine().begin() / engine().connect() with SQLAlchemy text() queries
  - Basic INSERT / SELECT / ON CONFLICT round-trips on core tables

Run with:
  python3 -m pytest tests/test_sqlite.py -v
"""

import os
import sys
import json
import pytest
from sqlalchemy import text

# Add repo root to sys.path so imports work from tests/ or from root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Fixture: isolated SQLite DB per test ─────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite file and a freshly initialised schema."""
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

    import db as _db
    _db._engine = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def eng():
    import db
    return db.engine()


def insert_bitstream(label="TEST"):
    with eng().begin() as conn:
        conn.execute(text(
            "INSERT INTO bitstreams (label, filename, device, package) "
            "VALUES (:l,:f,:d,:p) ON CONFLICT (label) DO NOTHING"
        ), {"l": label, "f": "test.config", "d": "LCMXO2-1200", "p": "TQFP100"})
    with eng().connect() as conn:
        row = conn.execute(
            text("SELECT id FROM bitstreams WHERE label=:l"), {"l": label}
        ).fetchone()
    return row[0]


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_schema_creates_all_required_tables():
    with eng().connect() as conn:
        tables = {r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )}
    for t in ("bitstreams", "nets", "ffs", "luts", "net_fanout", "pad_map",
              "efb_ports", "ebr_ports", "reachability", "net_names", "cell_names",
              "reachability_rev", "ff_cones", "critical_paths", "dominators",
              "cdc_synchronisers"):
        assert t in tables, f"Table {t!r} missing from SQLite schema"


def test_bitstream_insert_and_select():
    with eng().begin() as conn:
        conn.execute(text(
            "INSERT INTO bitstreams (label, filename, device, package) "
            "VALUES (:l,:f,:d,:p)"
        ), {"l": "V01", "f": "v01.config", "d": "LCMXO2-1200", "p": "TQFP100"})

    with eng().connect() as conn:
        row = conn.execute(
            text("SELECT id, label, device FROM bitstreams WHERE label=:l"),
            {"l": "V01"}
        ).fetchone()

    assert row is not None
    assert row[1] == "V01"
    assert row[2] == "LCMXO2-1200"


def test_nets_bulk_insert():
    bs_id = insert_bitstream()
    rows = [{"bs": bs_id, "n": f"n{i}"} for i in range(200)]
    with eng().begin() as conn:
        conn.execute(text("INSERT INTO nets (bitstream,name) VALUES (:bs,:n)"), rows)
    with eng().connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM nets WHERE bitstream=:bs"), {"bs": bs_id}
        ).fetchone()[0]
    assert count == 200


def test_on_conflict_do_nothing():
    bs_id = insert_bitstream()
    with eng().begin() as conn:
        conn.execute(text(
            "INSERT INTO nets (bitstream,name) VALUES (:bs,:n)"
        ), {"bs": bs_id, "n": "n1"})
        conn.execute(text(
            "INSERT INTO nets (bitstream,name) VALUES (:bs,:n) ON CONFLICT DO NOTHING"
        ), {"bs": bs_id, "n": "n1"})
    with eng().connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM nets WHERE bitstream=:bs AND name=:n"),
            {"bs": bs_id, "n": "n1"}
        ).fetchone()[0]
    assert count == 1


def test_bulk_insert_net_fanout():
    bs_id = insert_bitstream()
    rows = [{"bs": bs_id, "net": f"net_{i}", "ct": "FF",
             "cell": f"ff_{i}", "pin": "D", "out": f"net_{i+1}"}
            for i in range(50)]
    with eng().begin() as conn:
        conn.execute(text(
            "INSERT INTO net_fanout (bitstream,net,cell_type,cell,pin,out_net) "
            "VALUES (:bs,:net,:ct,:cell,:pin,:out) ON CONFLICT DO NOTHING"
        ), rows)
    with eng().connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM net_fanout WHERE bitstream=:bs"), {"bs": bs_id}
        ).fetchone()[0]
    assert count == 50


def test_upsert_bitstream_stable_id():
    """ON CONFLICT DO UPDATE keeps the same primary key."""
    upsert = text(
        "INSERT INTO bitstreams (label,filename,device,package) "
        "VALUES (:l,:f,:d,:p) "
        "ON CONFLICT (label) DO UPDATE SET filename=:f, device=:d, package=:p "
        "RETURNING id"
    )
    with eng().begin() as conn:
        id1 = conn.execute(upsert, {"l": "U", "f": "v1.cfg", "d": "LCMXO2-1200", "p": "TQFP100"}).fetchone()[0]
        id2 = conn.execute(upsert, {"l": "U", "f": "v2.cfg", "d": "LCMXO2-1200", "p": "TQFP100"}).fetchone()[0]
    assert id1 == id2
    with eng().connect() as conn:
        fn = conn.execute(text("SELECT filename FROM bitstreams WHERE label=:l"), {"l": "U"}).fetchone()[0]
    assert fn == "v2.cfg"


def test_ffs_and_net_names():
    bs_id = insert_bitstream()
    with eng().begin() as conn:
        conn.execute(text("INSERT INTO nets (bitstream,name) VALUES (:bs,:n)"),
                     {"bs": bs_id, "n": "n307"})
        conn.execute(text(
            "INSERT INTO ffs (bitstream,cell,clk,ce,d,q) VALUES (:bs,:c,:clk,:ce,:d,:q)"
        ), {"bs": bs_id, "c": "ff_r3c10_A0", "clk": "clk_h0",
            "ce": "1'b1", "d": "n307", "q": "n308"})
        conn.execute(text(
            "INSERT INTO net_names (bitstream,net,name,confidence,source) "
            "VALUES (:bs,:net,:nm,:conf,:src)"
        ), {"bs": bs_id, "net": "n307", "nm": "JUPDATE",
            "conf": "confirmed", "src": "pins_tsv"})

    with eng().connect() as conn:
        ff_count = conn.execute(
            text("SELECT count(*) FROM ffs WHERE bitstream=:bs"), {"bs": bs_id}
        ).fetchone()[0]
        name = conn.execute(
            text("SELECT name FROM net_names WHERE bitstream=:bs AND net=:net"),
            {"bs": bs_id, "net": "n307"}
        ).fetchone()[0]

    assert ff_count == 1
    assert name == "JUPDATE"


def test_json_columns():
    """TEXT[] columns stored as JSON lists round-trip correctly."""
    bs_id = insert_bitstream()
    deps = ["a", "c"]
    with eng().begin() as conn:
        conn.execute(text(
            "INSERT INTO luts (bitstream,cell,init,deps,fn) VALUES (:bs,:c,:init,:deps,:fn)"
        ), {"bs": bs_id, "c": "lut_r2c5_A0", "init": "0110011001100110",
            "deps": json.dumps(deps), "fn": "XOR(a,c)"})

    with eng().connect() as conn:
        raw = conn.execute(
            text("SELECT deps FROM luts WHERE bitstream=:bs"), {"bs": bs_id}
        ).fetchone()[0]

    result = raw if isinstance(raw, list) else json.loads(raw)
    assert result == deps
