"""scripts/cycloneiv_clean_annotate.py + cycloneiv_clean_annotate_emit.py on a hand-built netlist and a temp SQLite file (no local data needed)."""
import os
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert

from conftest import REPO

sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_annotate as A  # noqa: E402
import cycloneiv_clean_annotate_emit as E  # noqa: E402
import schema as S  # noqa: E402

IMG = "t"


@pytest.fixture
def eng(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    S.init(e)
    return e


@pytest.fixture
def trace(tmp_path):
    p = tmp_path / "trace.log"
    p.write_text("group FFs: ff_1_1_0 ff_1_1_1 ff_1_1_2\n")
    return str(p)


def nl():
    ffs = [dict(name=f"ff_1_1_{i}", clk="u_clkbuf_out_0_0_0_0", d=f"lc_1_1_{i}") for i in range(4)]
    luts = [dict(name=f"lc_1_1_{i}", pins=[f"ff_1_1_{(i + 1) % 4}"]) for i in range(4)]
    return SimpleNamespace(ffs=ffs, luts=luts, m9k=[dict(x=3, y=4)], mac=[dict(x=5, y=6)], pll=[dict(k=2)], ios=[dict(ball="A1")])


def members(*ids):
    return [(i, None) for i in ids]


def test_block_ids_are_kind_counters_and_stable(eng, trace):
    ev = f"log:{trace}"
    a, act = A.add_block(eng, IMG, "SCR", "p15", "lfsr", "V", ev, members("ff_1_1_0", "ff_1_1_1"))
    b, _ = A.add_block(eng, IMG, "SCR", "p11", "lfsr", "V", ev, members("ff_1_1_2"))
    c, _ = A.add_block(eng, IMG, "CNT", "c", "counter", "I", "json:schema.py", members("ff_1_1_3"))
    assert (a, b, c, act) == ("SCR001", "SCR002", "CNT001", "new")
    # same sorted member set, different order and a new name: same id
    assert A.add_block(eng, IMG, "SCR", "renamed", "lfsr", "V", ev, members("ff_1_1_1", "ff_1_1_0"))[0] == "SCR001"
    # same name, member set grew: same id, hash updated
    assert A.add_block(eng, IMG, "SCR", "p11", "lfsr", "V", ev, members("ff_1_1_2", "ff_1_1_3")) == ("SCR002", "updated")
    assert A.add_block(eng, IMG, "SCR", "p11", "lfsr", "V", ev, members("ff_1_1_3", "ff_1_1_2")) == ("SCR002", "same")
    with pytest.raises(ValueError):
        A.add_block(eng, IMG, "SCR", "x", "y", "V", "", members("ff_1_1_0"))


def test_check_passes_then_rejects(eng, trace):
    ev = f"log:{trace}"
    A.add_block(eng, IMG, "SCR", "ok", "lfsr", "V", ev, members("ff_1_1_0", "ff_1_1_1"))
    A.add_block(eng, IMG, "CNT", "ok2", "ctr", "I", "json:schema.py", members("ff_1_1_3"))
    assert A.check(eng, IMG, A.netlist_totals(nl())) == []

    def problems(**kw):
        A.add_block(eng, IMG, "DAT", "bad", "x", **kw)
        out = A.check(eng, IMG)
        A.remove_block(eng, IMG, "DAT001")
        return out
    # V without any log / trace / ledger reference
    assert any("tag V without" in p for p in problems(tag="V", evidence="json:schema.py", members=members("ff_1_1_2")))
    # V with a reference that does not exist
    assert any("does not exist" in p for p in problems(tag="V", evidence="log:tmp/logs/nope.log", members=members("ff_1_1_2")))
    # V whose trace names none of the block's FFs
    assert any("mentions none" in p for p in problems(tag="V", evidence=f"log:{trace}", members=members("ff_1_1_3")))
    # ledger row that is not there / is there
    assert any("ledger row" in p for p in problems(tag="V", evidence="ledger:ZZ-999", members=members("ff_1_1_2")))
    assert problems(tag="V", evidence="ledger:M-019", members=members("ff_1_1_2")) == []
    # duplicate physical id across blocks
    assert any("duplicate physical id ff_1_1_0" in p for p in problems(tag="I", evidence="json:schema.py", members=members("ff_1_1_0")))
    # id missing from the netlist
    A.add_block(eng, IMG, "DAT", "ghost", "x", "I", "json:schema.py", members("ff_9_9_9"))
    assert any("not in the netlist" in p for p in A.check(eng, IMG, A.netlist_totals(nl())))


def test_check_rejects_missing_evidence_and_alias_collisions(eng):
    A.add_block(eng, IMG, "DAT", "a", "x", "I", "json:schema.py", [("ff_1_1_0", "foo"), ("ff_1_1_1", "foo")])
    A.add_block(eng, IMG, "DAT", "b", "x", "I", "json:schema.py", [("ff_1_1_2", "ff_1_1_3"), ("ff_1_1_3", None)])
    bad = A.check(eng, IMG)
    assert any("alias collision 'foo'" in p for p in bad)
    assert any("equals the physical id of another object" in p for p in bad)
    with eng.begin() as c:        # an evidence-less row written behind add_block's back
        c.execute(S.annotations.update().where(S.annotations.c.block_id == "DAT001").values(evidence=""))
    assert any("DAT001: missing evidence" in p for p in A.check(eng, IMG))


def test_coverage_counts_named_by_tag_and_records(eng):
    A.add_block(eng, IMG, "CNT", "c", "ctr", "I", "json:schema.py", members("ff_1_1_0", "ff_1_1_1", "lc_1_1_0"))
    A.add_block(eng, IMG, "MEM", "m", "mem", "U", "json:schema.py", members("m9k_3_4"))
    A.add_block(eng, IMG, "MAC", "x", "mac", "I", "ledger:MA-004", members("mac_5_6"))
    r = A.coverage(eng, IMG, A.netlist_totals(nl()))
    assert (r["ff"]["named"], r["ff"]["total"], r["lut"]["named"], r["m9k"]["named"], r["mac"]["named"]) == (2, 4, 1, 0, 1)
    assert r["by_tag"]["U"]["m9k"] == 1 and r["by_tag"]["I"]["ff"] == 2
    with eng.connect() as c:
        row = c.execute(S.annotation_coverage.select()).mappings().one()
    assert (row["ff_named"], row["ff_total"], row["m9k_total"]) == (2, 4, 1)


def test_seed_cone_absorbs_only_private_luts():
    n = nl()
    rd = A.readers(n)
    lut_by = dict(ff={f["name"]: f for f in n.ffs}, lut={l["name"]: l for l in n.luts})
    cone = A.absorb_cone(["ff_1_1_0", "ff_1_1_1"], lut_by, rd, set())
    assert cone == {"ff_1_1_0", "ff_1_1_1", "lc_1_1_0", "lc_1_1_1"}      # lc_1_1_i is read only by ff_1_1_i


def test_emit_headers_aliases_and_name_map(eng, tmp_path):
    A.add_block(eng, IMG, "CNT", "ctr", "claim text", "I", "json:schema.py", [("ff_1_1_0", "cnt_q0"), ("lc_1_1_0", "cnt_d0"), ("m9k_3_4", "rom_a")])
    A.add_block(eng, IMG, "MEM", "unk", "mem", "U", "json:schema.py", members("ff_1_1_2"))
    src = tmp_path / "in.v"
    src.write_text("reg ff_1_1_2;\nreg ff_1_1_0;\nassign lc_1_1_0 = ff_1_1_0;\nassign co_1_1_0 = I_lc_1_1_0[1];\nwire [3:0] m9k_3_4_o;\nassign x = m9k_3_4_o[0];\n")
    blocks, mem = A.load_all(eng, IMG)
    out = tmp_path / "out.v"
    rep = E.annotate(str(src), str(out), blocks, mem)
    text = out.read_text().splitlines()
    assert rep["named_blocks"] == 1 and rep["aliases"] == 3
    assert text[1].startswith("// [CNT001 I] ctr") and len(text[1:4]) == 3 and not text[4].startswith("//")   # header <= 3 lines, before first member line
    assert "reg cnt_q0;" in text and "assign cnt_d0 = cnt_q0;" in text and "assign co_cnt_d0 = I_cnt_d0[1];" in text
    assert "wire [3:0] rom_a_o;" in text and "reg ff_1_1_2;" in text      # unnamed (U) logic stays under its physical id
    names = dict(l.split("\t") for l in (tmp_path / "out.v.names.tsv").read_text().splitlines()[1:])
    assert names == {"cnt_q0": "ff_1_1_0", "cnt_d0": "lc_1_1_0", "rom_a": "m9k_3_4"}
