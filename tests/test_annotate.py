"""Tests for the board-annotation importer (annotate.py, issue #12).

Fresh temp SQLite DB, one bitstream row, synthetic annotation TSVs — verify the
importer populates spi_registers/cell_names/open_questions and that api.py's
spi_reg() then returns the imported data (the gap #12 flagged).

Run with:
  python3 -m pytest tests/test_annotate.py -v
"""
import json
import os
import sys

import pytest
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
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

    eng = db.engine()
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO bitstreams (label, filename, device, package) "
            "VALUES ('TEST','test.config','LCMXO2-1200','TQFP100')"))
    yield db_path
    db._engine = None


def _write(p, text_):
    p.write_text(text_)
    return str(p)


def _spi_tsv(tmp_path):
    return _write(tmp_path / "spi_registers.tsv",
        "# bank\taddress\tname\tdescription\tbit_fields\n"
        "bank\taddress\tname\tdescription\tbit_fields\n"
        'CTRL\t0x02\tAWG_ENABLE\tAWG enable\t[{"bit":6,"name":"AWG_EN"}]\n'
        'CTRL\t0x0f\tTB_DIV\ttimebase divisor\t[]\n'
        'READ\t0x05\tIDENT\tident bytes\t[]\n')


def test_import_spi_registers(tmp_path):
    import annotate
    n = annotate.annotate("TEST", paths={"spi_registers.tsv": _spi_tsv(tmp_path)})
    assert n == 3

    import db
    with db.engine().begin() as c:
        rows = c.execute(text(
            "SELECT bank,address,name FROM spi_registers ORDER BY address")).fetchall()
    assert (rows[0].bank, rows[0].address, rows[0].name) == ("CTRL", 2, "AWG_ENABLE")
    assert {r.address for r in rows} == {0x02, 0x05, 0x0f}


def test_api_spi_reg_after_annotate(tmp_path):
    """The #12 gap: spi_reg() returns None until annotate.py populates the table."""
    import annotate
    from api import Netlist

    nl = Netlist("TEST")
    assert nl.spi_reg(0x02) is None            # empty before import

    annotate.annotate("TEST", paths={"spi_registers.tsv": _spi_tsv(tmp_path)})
    reg = Netlist("TEST").spi_reg(0x02)
    assert reg is not None
    assert reg["name"] == "AWG_ENABLE"
    assert reg["bit_fields"] == [{"bit": 6, "name": "AWG_EN"}]


def test_cell_names_and_open_questions(tmp_path):
    import annotate
    cn = _write(tmp_path / "cell_names.tsv",
        "cell\tname\tdescription\tconfidence\n"
        "ff_r3c14_A0\tafe_sr_bit0\tCH1 AFE shift bit 0\tconfirmed\n")
    oq = _write(tmp_path / "open_questions.tsv",
        "issue_num\ttitle\tdescription\tstatus\trelated_nets\trelated_cells\tblocker\n"
        '57\tclock route\tFF clocked by ghost net\topen\t["n3"]\t[]\tedge-cib\n')
    annotate.annotate("TEST", paths={"cell_names.tsv": cn, "open_questions.tsv": oq})

    import db
    with db.engine().begin() as c:
        cells = c.execute(text("SELECT cell,name,confidence FROM cell_names")).fetchall()
        qs = c.execute(text("SELECT issue_num,title,related_nets FROM open_questions")).fetchall()
    assert (cells[0].cell, cells[0].name, cells[0].confidence) == \
           ("ff_r3c14_A0", "afe_sr_bit0", "confirmed")
    assert qs[0].issue_num == 57
    assert json.loads(qs[0].related_nets) == ["n3"]


def test_always_rebuild(tmp_path):
    """A second import replaces, not appends."""
    import annotate
    p = _spi_tsv(tmp_path)
    annotate.annotate("TEST", paths={"spi_registers.tsv": p})
    annotate.annotate("TEST", paths={"spi_registers.tsv": p})
    import db
    with db.engine().begin() as c:
        n = c.execute(text("SELECT count(*) FROM spi_registers")).fetchone()[0]
    assert n == 3   # not 6
