"""Full asmdb object walk and the per-site IO CFF bits (#168).  Vendor-derived; oracle (Quartus corpus) is a check, never an input.

Missing is a fault: fields confirmed by the oracle vs located-but-unconfirmed are counted separately in the log.
"""
import collections
import glob
import os
import re
import sys

import pytest

from conftest import REPO, need, report
from lifters.cycloneiv_clean import asmdb_walk as W
from lifters.cycloneiv_clean import cycloneiv_io as IO

sys.path.insert(0, os.path.join(REPO, "scripts"))
CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
LOC = re.compile(r"// Location: (IO[OI]BUF)_X(\d+)_Y(\d+)_N(\d+)")


@pytest.fixture(scope="module")
def walk():
    from lifters.cycloneiv_clean import sofio
    try:
        return W.Walk()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))


@pytest.fixture(scope="module")
def sites(walk):
    import cycloneiv_clean_dirt as D
    names = D.enum_tables()["arch_group_type"]
    return W.io_cff_sites(walk, names)


def test_walk_consumes_body_exactly(walk):
    assert walk.main_end == 38044 and walk.end == len(walk.b)


def test_class_counts_equal_type_table(walk):
    from lifters.cycloneiv_clean import sofio
    p = os.path.join(sofio.quartus_bin(), "..", "common", "devinfo", "cycloneivgx", IO.ASMDB_NAME)
    want = {cid: cnt for cid, _, cnt, _ in IO.ddb_types(p) if cnt and cid != 1}     # class 1 = the DIE root
    got = walk.class_counts()
    report("asmdb_walk_classes", classes=got)
    assert got == want            # 8 / 277 / 4,996 / 1,032 / 7 groups, 37,564 muxes, 605 defaults, 4 labeled muxes, 7 index maps


def test_io_block_sites(walk):
    bi = {b["btype"]: b for b in walk.block_infos()}
    assert {k: len(v["lists"][1]) for k, v in bi.items() if k in (5, 6)} == {5: 131, 6: 325}     # HIO / VIO sites
    assert sorted(bi[5]["lists"]) == [1, 2, 3, 4, 5, 6, 8, 9, 10, 12, 13, 14]


def test_site_cff_fields(sites):
    # source: asmdb arch groups of the IO blocks; one entry per site, CFF-tagged mux / bit addresses
    assert len(sites) == 131 + 325
    s0 = sites[(5, 0)]
    report("io_site0_hio", **{k: [hex(a) for a in v] for k, v in s0.items()})
    assert s0["MIO_USE_PULL_UP"] == [0x2D1D] and s0["MIO_USE_BUS_HOLD"] == [0x2D1C]
    assert len(s0["MIO_SET_PULLUP_STRENGTH"]) == 8 and len(s0["MIO_SET_PULLDOWN_STRENGTH"]) == 9
    assert len(s0["MIO_SET_SLEW_RATE"]) == 2 and len(s0["MIO_SELECT_IOST_DIRT"]) == 3 and len(s0["MIO_PIN_MODE"]) == 1
    sizes = collections.Counter(sum(len(v) for v in g.values()) for g in sites.values())
    assert sum(sizes.values()) == 456


def test_oracle_signatures_are_inside_decoded_fields(sites):
    """Oracle: per used IOBUF site the CFF bits set in >= 95 % of designs using it and <= 3 % of the rest (see test_io_cff)."""
    import numpy as np
    files = sorted(glob.glob(os.path.join(CORPUS, "gx150_sp_*", "bitstream.rbf")))[:150]
    need(*(files[:1] or [os.path.join(CORPUS, "gx150_sp_000", "bitstream.rbf")]))
    cff = IO.Cff()
    vals, used = [], []
    for f in files:
        v, _ = cff.read(f)
        vals.append(v)
        text = open(os.path.join(os.path.dirname(f), "postfit.vo")).read()
        used.append({(m[1], int(m[2]), int(m[3]), int(m[4])) for m in LOC.finditer(text)})
    V = np.stack(vals).astype(np.float32)
    by_addr = collections.defaultdict(set)
    for (bt, s), g in sites.items():
        for nm, a in g.items():
            for x in a:
                by_addr[x].add((bt, s, nm))
    uses = collections.defaultdict(list)
    for i, u in enumerate(used):
        for k in u:
            uses[k].append(i)
    fields = collections.Counter()
    unique = missing = 0
    for k, pos in uses.items():
        if len(pos) < 8:
            continue
        neg = np.setdiff1d(np.arange(len(files)), pos)
        cand = np.nonzero((V[pos].mean(0) >= 0.95) & (V[neg].mean(0) <= 0.03))[0].tolist() if len(neg) else []
        if not cand:
            continue
        keys = set.intersection(*[{(bt, s) for bt, s, _ in by_addr.get(a, ())} for a in cand])
        if len(keys) == 1:
            unique += 1
            key = next(iter(keys))
            fields[(k[0], tuple(sorted(collections.Counter(nm for a in cand for bt, s, nm in by_addr[a] if (bt, s) == key).items())))] += 1
        else:
            missing += 1
    report("io_oracle_site_fields", sites_unique=unique, sites_unplaced=missing,
           fields=sorted((a, list(b), n) for (a, b), n in fields.items()))
    obuf = [(a, b, n) for (a, b), n in fields.items() if a == "IOOBUF"]
    assert sum(n for *_, n in obuf) >= 150
    assert all(dict(b).keys() == {"MIO_SET_PULLUP_STRENGTH", "MIO_SET_PULLDOWN_STRENGTH", "MIO_SET_SLEW_RATE"} for _, b, _ in obuf)
    assert {tuple(b) for a, b in fields if a == "IOIBUF"} == {(("MIO_USE_PCI_DIODE_CLAMP", 1),)}
