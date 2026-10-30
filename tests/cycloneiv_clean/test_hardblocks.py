"""Class -> group binding from the vendor factory switches, and absolute-address groups (#169)."""
import json
import os
import sys

import pytest

from conftest import REPO

sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import hardblocks as H, options as O  # noqa: E402


def test_binding_reproduces_pair_confirmed_option_groups():
    # every option group the pair builds confirmed (options_table.json) has the class bound to the same enum
    gt = {e["name"]: e["group_type"] for e in O.entries() if e["klass"] == "group"}
    assert len(gt) == 13
    assert all(H.groups_of("ASM_" + n).get(n) == t for n, t in gt.items())


def test_binding_matches_earlier_decompile_findings():
    # ASM_IO_USE_BUS_HOLD enum 165 (reference/ghidra/functions.tsv, #168 c4); LE_USE_CARRY = LE factory case 0xb
    assert H.groups_of("ASM_IO_USE_BUS_HOLD") == {"IO_USE_BUS_HOLD": 165}
    assert H.groups_of("ASM_LE_USE_CARRY") == {"LE_USE_CARRY": 11}
    assert all(r["source"] for r in H.rows())


def test_absolute_groups_counts():
    pytest.importorskip("numpy")
    from lifters.cycloneiv_clean import asmdb_walk as W
    try:
        import cycloneiv_clean_dirt as D
        w, names = W.Walk(), D.enum_tables()
    except Exception as e:                                   # vendor install missing
        pytest.skip(str(e))
    a = H.absolute_bits(w, names)
    cram = {k: v.get("cram", []) for k, v in a.items()}
    assert sum(len(v) for k, v in cram.items() if k[0] == "HIO") > 20000
    assert all(0 <= b < 39040976 for v in cram.values() for b in v)


def test_default_bit_calc_objects():
    # 8 ASMDB_DEFAULT_BIT_CALC objects (LAB 1, MEAB 6, MAC 1) x instances (9,360 / 720 / 360) = 14,040 cells, inside the die
    from lifters.cycloneiv_clean import asmdb_walk as W, fields as F
    w = W.Walk()
    dbc = [o for o in w.S["DG"].objs[1:] if o["cls"] == 11]
    assert len(dbc) == 8
    n = 0
    for o in dbc:
        bt = w.block_infos()[o["bi"][1] - 1]["btype"]
        a = F.absolute(F.bases(w, bt), [o["bit"]])
        assert a.min() >= 0
        n += a.size
    assert n == 14040 and len(dbc) == 8
