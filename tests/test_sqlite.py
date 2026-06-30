"""Smoke test for the SQLite backend.

Does NOT require pytrellis or a real bitstream.  Directly exercises:
  - schema.init() creates all tables in a fresh SQLite file
  - db.connect() shim: cursor, execute, executemany, fetchone, fetchall, commit
  - execute_values() replacement
  - Basic INSERT / SELECT / ON CONFLICT round-trips on core tables

Run with:
  python3 -m pytest tests/test_sqlite.py -v
"""

import os
import sys
import pytest

# Add repo root to sys.path so imports work when running from tests/ or from root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Fixture: isolated SQLite DB per test ─────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite file and a freshly initialised schema."""
    db_path = str(tmp_path / "pluribus.db")
    monkeypatch.setenv("PLURIBUS_DB_BACKEND", "sqlite")
    monkeypatch.setenv("PLURIBUS_SQLITE_PATH", db_path)

    # Force db module to rebuild its cached engine so it picks up the new path.
    # The module was already imported above (sys.path.insert), so we patch in-place.
    import db
    db.BACKEND  = "sqlite"
    db._SQPATH  = db_path
    db._engine  = None   # discard previous engine

    import schema
    schema.init()

    yield db_path

    # Cleanup: reset engine so the next test starts clean
    import db as _db
    _db._engine = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _insert_bitstream(cur, label="TEST"):
    cur.execute(
        "INSERT INTO bitstreams (label, filename, device, package) "
        "VALUES (%s,%s,%s,%s) ON CONFLICT (label) DO NOTHING",
        (label, "test.config", "LCMXO2-1200", "TQFP100")
    )
    cur.execute("SELECT id FROM bitstreams WHERE label=%s", (label,))
    return cur.fetchone()[0]


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_schema_creates_all_required_tables():
    import db
    conn = db.connect()
    cur  = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {r[0] for r in cur.fetchall()}
    conn.close()

    for t in ("bitstreams", "nets", "ffs", "luts", "net_fanout", "pad_map",
              "efb_ports", "ebr_ports", "reachability", "net_names", "cell_names",
              "reachability_rev", "ff_cones", "critical_paths", "dominators",
              "cdc_synchronisers"):
        assert t in tables, f"Table {t!r} missing from SQLite schema"


def test_bitstream_insert_and_select():
    import db
    conn = db.connect()
    cur  = conn.cursor()
    cur.execute(
        "INSERT INTO bitstreams (label, filename, device, package) "
        "VALUES (%s,%s,%s,%s)",
        ("V01", "v01.config", "LCMXO2-1200", "TQFP100")
    )
    conn.commit()
    cur.execute("SELECT id, label, device FROM bitstreams WHERE label=%s", ("V01",))
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[1] == "V01"
    assert row[2] == "LCMXO2-1200"


def test_nets_executemany():
    import db
    conn = db.connect()
    cur  = conn.cursor()
    bs_id = _insert_bitstream(cur)
    nets = [(bs_id, f"n{i}") for i in range(200)]
    cur.executemany("INSERT INTO nets (bitstream,name) VALUES (%s,%s)", nets)
    conn.commit()
    cur.execute("SELECT count(*) FROM nets WHERE bitstream=%s", (bs_id,))
    assert cur.fetchone()[0] == 200
    conn.close()


def test_on_conflict_do_nothing():
    import db
    conn = db.connect()
    cur  = conn.cursor()
    bs_id = _insert_bitstream(cur)
    cur.execute("INSERT INTO nets (bitstream,name) VALUES (%s,%s)", (bs_id, "n1"))
    cur.execute(
        "INSERT INTO nets (bitstream,name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (bs_id, "n1")
    )
    conn.commit()
    cur.execute("SELECT count(*) FROM nets WHERE bitstream=%s AND name=%s", (bs_id, "n1"))
    assert cur.fetchone()[0] == 1
    conn.close()


def test_execute_values():
    import db
    conn = db.connect()
    cur  = conn.cursor()
    bs_id = _insert_bitstream(cur)
    conn.commit()

    rows = [(bs_id, f"net_{i}", "FF", f"ff_{i}", "D", f"net_{i+1}") for i in range(50)]
    db.execute_values(cur, """
        INSERT INTO net_fanout (bitstream, net, cell_type, cell, pin, out_net)
        VALUES %s ON CONFLICT DO NOTHING
    """, rows)
    conn.commit()

    cur.execute("SELECT count(*) FROM net_fanout WHERE bitstream=%s", (bs_id,))
    assert cur.fetchone()[0] == 50
    conn.close()


def test_upsert_bitstream_stable_id():
    """ON CONFLICT DO UPDATE keeps the same primary key."""
    import db
    conn = db.connect()
    cur  = conn.cursor()

    upsert = ("INSERT INTO bitstreams (label, filename, device, package) "
              "VALUES (%s,%s,%s,%s) "
              "ON CONFLICT (label) DO UPDATE SET filename=%s, device=%s, package=%s "
              "RETURNING id")

    cur.execute(upsert, ("UPSERT", "v1.config", "LCMXO2-1200", "TQFP100",
                          "v1.config", "LCMXO2-1200", "TQFP100"))
    id1 = cur.fetchone()[0]

    cur.execute(upsert, ("UPSERT", "v2.config", "LCMXO2-1200", "TQFP100",
                          "v2.config", "LCMXO2-1200", "TQFP100"))
    id2 = cur.fetchone()[0]
    conn.commit()

    assert id1 == id2, "upsert must not change the primary key"

    cur.execute("SELECT filename FROM bitstreams WHERE label=%s", ("UPSERT",))
    assert cur.fetchone()[0] == "v2.config"
    conn.close()


def test_ffs_and_net_names():
    import db
    conn = db.connect()
    cur  = conn.cursor()
    bs_id = _insert_bitstream(cur)
    cur.execute(
        "INSERT INTO nets (bitstream,name) VALUES (%s,%s)",
        (bs_id, "n307")
    )
    cur.executemany(
        "INSERT INTO ffs (bitstream,cell,clk,ce,d,q) VALUES (%s,%s,%s,%s,%s,%s)",
        [(bs_id, "ff_r3c10_A0", "clk_h0", "1'b1", "n307", "n308")]
    )
    cur.execute(
        "INSERT INTO net_names (bitstream,net,name,confidence,source) "
        "VALUES (%s,%s,%s,%s,%s)",
        (bs_id, "n307", "JUPDATE", "confirmed", "pins_tsv")
    )
    conn.commit()

    cur.execute("SELECT count(*) FROM ffs WHERE bitstream=%s", (bs_id,))
    assert cur.fetchone()[0] == 1

    cur.execute("SELECT name FROM net_names WHERE bitstream=%s AND net=%s",
                (bs_id, "n307"))
    assert cur.fetchone()[0] == "JUPDATE"
    conn.close()


def test_json_columns():
    """TEXT[] columns stored as JSON lists round-trip correctly."""
    import db, json
    conn = db.connect()
    cur  = conn.cursor()
    bs_id = _insert_bitstream(cur)
    deps = ["a", "c"]
    cur.execute(
        "INSERT INTO luts (bitstream,cell,init,deps,fn) VALUES (%s,%s,%s,%s,%s)",
        (bs_id, "lut_r2c5_A0", "0110011001100110", json.dumps(deps), "XOR(a,c)")
    )
    conn.commit()
    cur.execute("SELECT deps FROM luts WHERE bitstream=%s", (bs_id,))
    raw = cur.fetchone()[0]
    # SQLAlchemy JSON type returns the decoded Python object
    result = raw if isinstance(raw, list) else json.loads(raw)
    assert result == deps
    conn.close()
