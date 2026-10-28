"""scripts/import_legacy_lift.py: old-schema fixture -> new per-family DB, imported claims, integrity gate, ingest loop."""
import json
import os
import sqlite3
import sys

from sqlalchemy import select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

OLD_DDL = """
CREATE TABLE bitstreams (id INTEGER PRIMARY KEY, label TEXT, filename TEXT, device TEXT, package TEXT, diamond_version TEXT, loaded_at TEXT);
CREATE TABLE nets (id INTEGER PRIMARY KEY, bitstream INT, name TEXT);
CREATE TABLE luts (id INTEGER PRIMARY KEY, bitstream INT, cell TEXT, init TEXT, a TEXT, b TEXT, c TEXT, d TEXT, e TEXT, z TEXT, deps TEXT, fn TEXT);
CREATE TABLE ffs (id INTEGER PRIMARY KEY, bitstream INT, cell TEXT, clk TEXT, ce TEXT, d TEXT, q TEXT, lsr TEXT, dtype TEXT);
CREATE TABLE net_fanout (id INTEGER PRIMARY KEY, bitstream INT, net TEXT, cell_type TEXT, cell TEXT, pin TEXT, out_net TEXT);
CREATE TABLE pad_map (id INTEGER PRIMARY KEY, bitstream INT, pin INT, label TEXT, row INT, col INT, pio TEXT, direction TEXT, net_in TEXT, net_out TEXT, iostd TEXT, drive TEXT, pull TEXT, si_function TEXT, conn_class TEXT, chip_ref TEXT, chip_pin TEXT, chip_signal TEXT);
CREATE TABLE arcs (id INTEGER PRIMARY KEY, bitstream INT, tile_row INT, tile_col INT, sink_wire TEXT, source_wire TEXT, sink_net TEXT, source_net TEXT, sink_gx INT, sink_gy INT, sink_gid INT, source_gx INT, source_gy INT, source_gid INT);
CREATE TABLE efb_ports (id INTEGER PRIMARY KEY, bitstream INT, port_name TEXT, net TEXT, direction TEXT);
CREATE TABLE ebr_ports (id INTEGER PRIMARY KEY, bitstream INT, block TEXT, port TEXT, role TEXT, net TEXT);
CREATE TABLE net_names (id INTEGER PRIMARY KEY, bitstream INT, net TEXT, name TEXT, description TEXT, confidence TEXT, source TEXT, freq_mhz REAL, updated_at TEXT);
CREATE TABLE critical_paths (id INTEGER PRIMARY KEY, bitstream INT, src_ff TEXT, dst_ff TEXT, hops INT, path_nets TEXT);
CREATE TABLE reachability (id INTEGER PRIMARY KEY, bitstream INT, src TEXT, dst TEXT, min_hops INT);
"""


def make_old(path):
    c = sqlite3.connect(path)
    c.executescript(OLD_DDL)
    c.execute("INSERT INTO bitstreams VALUES (7,'OLD','old.bin.config','LCMXO2-1200','TQFP100','3.14.0.201','2026-01-01')")
    c.executemany("INSERT INTO nets (bitstream,name) VALUES (7,?)", [("n1",), ("n2",), ("n3",)])
    c.execute("INSERT INTO luts (bitstream,cell,init,a,z,deps,fn) VALUES (7,'lut_r1c1_A0','0101010101010101','n1','n2','[\"a\"]','NOT(a)')")
    c.execute("INSERT INTO luts (bitstream,cell,init,a,z,deps,fn) VALUES (7,'lut_r1c1_B0','1111000011110000','n2','n3','[\"c\"]','c')")
    c.execute("INSERT INTO ffs (bitstream,cell,clk,ce,d,q) VALUES (7,'ff_r1c1_A0','clk','1''b1','n3','n1')")
    c.execute("INSERT INTO net_fanout (bitstream,net,cell_type,cell,pin,out_net) VALUES (7,'n1','LUT','lut_r1c1_A0','A','n2')")
    c.execute("INSERT INTO pad_map (bitstream,pin,label,direction,net_in,chip_ref,chip_signal) VALUES (7,5,'CLK','in','clk','U1','CLKOUT')")
    c.execute("INSERT INTO pad_map (bitstream,pin,label,direction,net_in,chip_ref,chip_signal) VALUES (7,6,'?','out',NULL,'?','?')")
    c.execute("INSERT INTO arcs (bitstream,tile_row,tile_col,sink_wire,source_wire,sink_net,source_net) VALUES (7,1,1,'A0','H02W0001','n1','n2')")
    c.execute("INSERT INTO efb_ports (bitstream,port_name,net,direction) VALUES (7,'JWBDATO0','n2','out')")
    c.execute("INSERT INTO ebr_ports (bitstream,block,port,role,net) VALUES (7,'R2C5','DIA0','write','n3')")
    c.execute("INSERT INTO net_names (bitstream,net,name,confidence,source) VALUES (7,'clk','SYS_CLK','confirmed','pins_tsv')")
    c.execute("INSERT INTO net_names (bitstream,net,name,confidence,source) VALUES (7,'n2','maybe_adc','estimate','auto_spatial')")
    c.execute("INSERT INTO critical_paths (bitstream,src_ff,dst_ff,hops) VALUES (7,'a','b',3)")
    c.execute("INSERT INTO reachability (bitstream,src,dst,min_hops) VALUES (7,'n1','n2',1)")
    c.commit()
    c.close()


def test_import_registers_claims_and_gate(tmp_path, monkeypatch):
    new_db = str(tmp_path / "new.db")
    old_db = str(tmp_path / "old.db")
    make_old(old_db)
    monkeypatch.setenv("PLURIBUS_SQLITE_PATH", new_db)
    import db
    db.BACKEND, db._SQPATH, db._engine = "sqlite", new_db, None
    import schema as S
    S.init()
    import import_legacy_lift as IL
    old = sqlite3.connect(f"file:{old_db}?mode=ro", uri=True)
    bs = IL.import_label(old, old_db, "machxo2", "OLD", "deadbeef", dry=False)
    with db.engine().connect() as conn:
        b = conn.execute(select(S.bitstreams).where(S.bitstreams.c.id == bs)).fetchone()
        assert b.family == "machxo2" and b.toolchain == "3.14.0.201" and b.label == "OLD"
        assert conn.execute(select(S.luts.c.cell).where(S.luts.c.bitstream == bs)).fetchall() == [("lut_r1c1_A0",), ("lut_r1c1_B0",)]
        hc = {r.cell: r.kind for r in conn.execute(select(S.hard_cells).where(S.hard_cells.c.bitstream == bs))}
        assert hc == {"EFB": "EFB", "R2C5": "EBR"}
        hp = conn.execute(select(S.hard_cell_ports.c.cell, S.hard_cell_ports.c.port, S.hard_cell_ports.c.direction, S.hard_cell_ports.c.role)).fetchall()
        assert set(hp) == {("EFB", "JWBDATO0", "out", None), ("R2C5", "DIA0", None, "write")}
        assert conn.execute(select(S.reachability)).fetchall() == []          # derived tables not copied
        claims = {r.subject_key: r for r in conn.execute(select(S.claims))}
        assert claims["OLD:LUT:lut_r1c1_A0:init"].tier == "vendor-decoded" and claims["OLD:LUT:lut_r1c1_A0:init"].status == "open"
        assert claims["OLD:LUT:lut_r1c1_A0:init"].pattern_id == "decoder:machxo2:lut"
        assert claims["OLD:PAD:5"].tier == "measured" and claims["OLD:PAD:6"].tier == "vendor-decoded"
        assert claims["OLD:clk:name"].tier == "measured"
        assert claims["OLD:A0<-H02W0001@1,1"].tier == "vendor-decoded"
        assert "OLD:n2:name" not in claims                                   # estimate -> expectation, never a claim
        e = conn.execute(select(S.expectations)).fetchone()
        assert e.subject_key == "OLD:n2:name" and e.matcher_id == "human-annotation-v1" and e.status == "open"
        lp = conn.execute(select(S.lift_provenance)).fetchall()
        assert len(lp) == len(claims) and all(r.min_status == "open" for r in lp)
        ev = conn.execute(select(S.evidence)).fetchone()
        assert ev.kind == "vendor-decode" and ev.result["counts_old"]["luts"] == 2 and "critical_paths" in ev.result["old_tables"]
        gr = conn.execute(select(S.gate_results)).fetchall()
        assert gr and all(r.passed for r in gr)                              # integrity: counts equal
        m = conn.execute(select(S.corpus_members)).fetchone()
        assert m.name == "legacy:OLD" and m.required is False                # never part of the family's done criterion
    # re-import is an always-rebuild (no duplicates)
    IL.import_label(old, old_db, "machxo2", "OLD", "deadbeef", dry=False)
    with db.engine().connect() as conn:
        assert conn.execute(select(S.bitstreams)).fetchall().__len__() == 1
        assert len(conn.execute(select(S.claims)).fetchall()) == len(claims)
    # validation with an ingested report: matched cell confirmed, wrong cell refuted -> decoder pattern suspect
    rep = tmp_path / "rep.json"
    rep.write_text(json.dumps({"lut_init": {"matched": 1, "missing": 0, "extra": 0, "wrong": 1,
                                            "matched_cells": ["lut_r1c1_A0"], "wrong_cells": ["lut_r1c1_B0"]}}))
    res = IL.validate(old_db, "machxo2", "OLD", str(rep), "deadbeef")
    assert res["lift_summary"]["wrong"] == 0 and res["lut_init"]["wrong"] == 1
    with db.engine().connect() as conn:
        rows = {r.subject_key: r for r in conn.execute(select(S.claims))}
        st = {k: r.status for k, r in rows.items()}
        assert st["OLD:LUT:lut_r1c1_B0:init"] == "refuted"
        # A0 was confirmed by the report, then its decoder pattern was refuted through B0: the sibling goes
        # suspect (confirmation count kept) until an audit clears the pattern — the designed fan-out
        assert st["OLD:LUT:lut_r1c1_A0:init"] == "suspect" and rows["OLD:LUT:lut_r1c1_A0:init"].confirmations == 1
        assert conn.execute(select(S.claim_patterns.c.status).where(S.claim_patterns.c.id == "decoder:machxo2:lut")).scalar() == "suspect"
        assert st["OLD:FF:ff_r1c1_A0"] == "open"                             # another decode kind: untouched
    old.close()
    db._engine = None
