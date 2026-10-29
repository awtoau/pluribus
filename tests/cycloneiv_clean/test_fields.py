"""LAB / M9K / MAC fields from the vendor asmdb (#169).  Oracle = existing Quartus-built corpus (no new builds).

Pair results come from scripts/cycloneiv_clean_fields_pairs.py (tmp/cycloneiv_clean/fields_pairs.json); numbers go to
tmp/logs/cycloneiv_clean_oracles.log.  A pair = two builds differing in one named feature; a diff cell is matched when a vendor
group (or asm.ddb routing) claims it, missing when nothing does.
"""
import json
import os
import sys

import numpy as np
import pytest

import o1_model as M
from conftest import REPO, need, report
from lifters.cycloneiv_clean import asmdb_walk as W, fields as F, plane as P

sys.path.insert(0, os.path.join(REPO, "scripts"))
PAIRS = os.path.join(REPO, "tmp", "cycloneiv_clean", "fields_pairs.json")


@pytest.fixture(scope="module")
def walk():
    from lifters.cycloneiv_clean import sofio
    try:
        return W.Walk()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))


@pytest.fixture(scope="module")
def flds(walk):
    import cycloneiv_clean_dirt as D
    return F.fields(walk, D.enum_tables())


def test_instances_and_groups(walk, flds):
    assert {bt: len(F.bases(walk, bt)) for bt in F.PLACED} == {18: 9360, 39: 720, 41: 360}
    n = {bt: sum(1 for f in flds if f.btype == bt) for bt in F.PLACED}
    assert n == {18: 37, 39: 147, 41: 93}
    # every offset set lands inside the die for every instance
    for bt in F.PLACED:
        bs = F.bases(walk, bt)
        for f in flds:
            if f.btype == bt:
                for s in f.sites:
                    for o in s:
                        F.absolute(bs, o)


def test_lut_function_bits_are_disjoint_and_complete(walk, flds):
    f = next(f for f in flds if f.name == "LE_LUT_FUNCTION")
    a = np.concatenate([F.absolute(F.bases(walk, 18), o).ravel() for s in f.sites for o in s])
    assert len(a) == len(np.unique(a)) == 9360 * 256 == 2_396_160


def test_lut_specimens_exact(walk, flds):
    """1,023 Quartus-built LUT sites: the 16 observed rbf cells = the 16 cells of LE_LUT_FUNCTION at (column, row, LE); no constant."""
    need(M.OBS, M.LABS)
    tab = P.load_tables()
    o = M.observed()
    xs, _ = M.lab_columns()
    oc = M.site_cells(o)
    g = next(f for f in flds if f.name == "LE_LUT_FUNCTION")
    bs = F.bases(walk, 18)
    ok = 0
    for i in range(len(o["sx"])):
        idx = xs.index(int(o["sx"][i])) * F.ROWS_PER_COLUMN + int(o["sy"][i]) - 1
        r, j, k = P.sof_to_rbf(F.absolute(bs[idx:idx + 1], g.sites[int(o["le"][i])][0]).ravel(), tab)
        ok += sorted(((r * 800 + j) * 8 + k).tolist()) == sorted(oc[i].tolist())
    report("fields_lut_specimens", sites=len(o["sx"]), matched_sites=int(ok), cells=16 * int(ok), missing=0, extra=0, wrong=0)
    assert ok == len(o["sx"]) == 1023


def pairs():
    need(PAIRS)
    return json.load(open(PAIRS))


def test_lab_control_pairs():
    """gxct_a_pos_{b,<ctl>}PP: 8 LE positions x 5 controls, one feature each (FF_X10_Y10)."""
    rows = pairs()["lab"]
    assert len(rows) == 40
    cells = sum(r["diff"] for r in rows)
    miss = sum(r.get("unclaimed", 0) for r in rows)
    grp = sum(r.get("group", 0) for r in rows)
    asm = sum(r.get("asm_ddb", 0) for r in rows)
    report("fields_lab_pairs", pairs=len(rows), diff_cells=cells, in_lab_groups=grp, in_asm_ddb=asm, missing=miss)
    assert miss == 0 and grp + asm == cells
    # position-dependent labels land on the LE the specimen uses (site == position)
    want = {"aclr": "LE_CLEAR_SELECT", "sclr": "LE_USE_SYNC_CLEAR"}
    for r in rows:
        if r["ctl"] in want:
            hit = [g for g, _ in r["groups"] if g.startswith(want[r["ctl"]] + "#-1@")]
            assert hit and all(g.split("@")[1].split(":")[0] == str(r["pos"]) for g in hit), r["variant"]


def test_m9k_pairs():
    rows = pairs()["m9k"]
    clean = [r for r in rows if r["src_lines"] >= 1 and 0 < r["diff"] <= 64]
    init = [r for r in clean if r["variant"].startswith(("gxm9k_h", "gxm9k_b"))]
    mode = [r for r in clean if r not in init]
    miss = sum(r.get("unclaimed", 0) for r in clean)
    report("fields_m9k_pairs", clean_pairs=len(clean), init_pairs=len(init), mode_pairs=len(mode), diff_cells=sum(r["diff"] for r in clean),
           missing=miss, instances=sorted({(r["site"][0], r["col"], r["row"]) for r in clean}))
    assert len(clean) >= 40 and miss == 0
    assert all(r["unique"] and r["row"] == r["site"][1] - 1 for r in clean)
    assert all(r["groups"] and r["groups"][0][0].startswith("RAM_CONTENT_YGR_MEAB#0@0") or "RAM_CONTENT" in r["groups"][0][0] for r in init)
    # M9K column rank is ascending in X
    by_x = {}
    for r in clean:
        by_x.setdefault(r["site"][0], set()).add(r["col"])
    assert all(len(v) == 1 for v in by_x.values())
    xs = sorted(by_x)
    assert [min(by_x[x]) for x in xs] == sorted(min(by_x[x]) for x in xs)
