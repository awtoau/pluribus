"""Package pins, pads and the pad -> IO site -> pin chain (#168).  Vendor-derived; oracle = Quartus corpus pin assignments (check only)."""
import collections
import glob
import os
import re

import pytest

from conftest import REPO, need, report
from lifters.cycloneiv_clean import pkgpad as K

CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
SIG = re.compile(r"// (\S+)\s+=>\s+Location: PIN_(\w+)")
CELL = re.compile(r"// Location: IO([OI])BUF_X(\d+)_Y(\d+)_N(\d+)\ncycloneiv_io_[io]buf \\(\S+?)~(?:output|input)")


@pytest.fixture(scope="module")
def data():
    from lifters.cycloneiv_clean import sofio
    try:
        return K.pins(), K.pads()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))


def test_objects_consume_bodies_exactly(data):
    pins, pads = data
    cls = collections.Counter(p["strs"][3] for p in pads)
    report("pkgpad_counts", pins=len(pins), pads=len(pads), pad_classes=dict(cls),
           pins_with_pad=sum(1 for p in pins if p["pad_raw"]))
    assert (len(pins), len(pads)) == (896, 520)
    assert sum(1 for p in pins if p["pad_raw"]) == 520                    # every pad has exactly one pin
    assert cls["Row I/O"] == 131 and cls["Column I/O"] == 324             # HIO 131 sites; VIO 325 = 324 + 1


def test_pad_ids_are_ordinals(data):
    pins, pads = data
    assert [p["id"] for p in pads] == list(range(1, 521))
    assert [x for p in pins if p["pad_raw"] for x in p["pad_raw"]] == list(range(520))


def _oracle():
    seen = {}
    for d in sorted(glob.glob(os.path.join(CORPUS, "gx150_sp_*")))[:400]:
        try:
            t = open(os.path.join(d, "postfit.vo")).read()
        except OSError:
            continue
        sig = {m[1]: m[2] for m in SIG.finditer(t)}
        for m in CELL.finditer(t):
            if m[5] in sig:
                seen[sig[m[5]]] = (int(m[2]), int(m[3]), (int(m[4]) - (2 if m[1] == "O" else 1)) // 7)
    return seen


def test_pin_to_pad_site_matches_oracle(data):
    pins, pads = data
    need(os.path.join(CORPUS, "gx150_sp_000", "postfit.vo"))
    rank = K.pin_pad_rank(pins)
    ball = {p["strs"][0]: i for i, p in enumerate(pins)}
    orc = _oracle()
    ok = bad = miss = 0
    for b, site in orc.items():
        if b not in ball or ball[b] not in rank:
            miss += 1
        elif K.pad_site(pads[rank[ball[b]]]) == site:
            ok += 1
        else:
            bad += 1
    report("pin_pad_oracle", balls=len(orc), matched=ok, wrong=bad, missing=miss)
    assert bad == 0 and miss == 0 and ok >= 390


def test_io_site_to_pad_matches_oracle(data):
    pins, pads = data
    need(os.path.join(CORPUS, "gx150_sp_000", "postfit.vo"))
    import sys
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import cycloneiv_clean_dirt as D
    from lifters.cycloneiv_clean import asmdb_walk as W
    walk = W.Walk()
    sites = W.io_cff_sites(walk, D.enum_tables()["arch_group_type"])
    sp = K.io_site_pads(pads)
    # every IO site with a pad is a Row / Column I/O pad of the matching edge; HIO sites sit on X=117 and X=0, VIO on Y=91 and Y=0
    for (bt, s), j in sp.items():
        x, y, _ = K.pad_site(pads[j])
        assert (x in (0, 117)) if bt == 5 else (y in (0, 91))
    # the CFF field bits of the pin's site: ball -> pad -> site index -> groups
    rank = K.pin_pad_rank(pins)
    inv = {j: k for k, j in sp.items()}
    ball_sites = {p["strs"][0]: inv.get(rank[i]) for i, p in enumerate(pins) if i in rank}
    orc = _oracle()
    placed = [b for b in orc if ball_sites.get(b) in sites]
    report("pin_to_site_fields", io_sites=len(sp), io_pins=sum(1 for v in ball_sites.values() if v), oracle_balls=len(orc),
           oracle_balls_with_fields=len(placed))
    assert len(sp) == 131 + 324                                     # site 324 of VIO has no 'Column I/O' pad
    assert len(placed) >= 390
