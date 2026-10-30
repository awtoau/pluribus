"""P2 tracer: structural checks on corpus design gx150_rb_000 (skip when local data is missing).  No score thresholds: the numbers
live in scripts/cycloneiv_clean_gate.py (baseline run), this test checks the tracer's invariants and the ground-truth parse."""
import os
import re

import numpy as np
import pytest

from conftest import REPO, need, report
from lifters.cycloneiv_clean import ddb
from lifters.cycloneiv_clean import tracer as T

D = os.path.join(REPO, "corpus", "cycloneiv", "gx150_rb_000")


@pytest.fixture(scope="module")
def st():
    need(ddb.TMP, os.path.join(REPO, "databases", "cycloneiv", "sof2rbf_mask.npz"))
    try:
        return T.Static()
    except ddb.DdbMissing as e:
        pytest.skip(str(e))


@pytest.fixture(scope="module")
def fired(st):
    need(os.path.join(D, "bitstream.rbf"))
    return st.fire(T.plane_bits(os.path.join(D, "bitstream.rbf")))


def test_static_edge_table(st):
    assert st.n_edges == 14_862_095
    assert int(st.estart[-1]) == len(st.cell)
    report("tracer-static", edges=st.n_edges, empty_groups=int((st.size == 0).sum()), entries=len(st.cell))
    assert int(st.cell.max()) < T.CFF_BASE + 40_000                   # every entry resolves inside the die (outside_die = 0)
    assert int(st.xrec.max()) < 1 << 21 and len(st.xcell) == len(st.xrec)
    assert ((np.asarray(st.kind) & 2) != 0).all()              # every list bit is also a bit of the destination's exclusion groups


def test_variants_nested(fired):
    s = {k: set(v.tolist()) for k, v in fired.items()}
    assert s["vendor"] <= s["vendor_nx"]
    report("tracer-variants", **{k: len(v) for k, v in s.items()})
    assert len(s["vendor"]) > 0


def test_rcf_names_resolve_exactly():
    need(os.path.join(D, "routing.rcf"))
    nets = T.parse_rcf(os.path.join(D, "routing.rcf"))
    text = open(os.path.join(D, "routing.rcf")).read()
    assert len(nets) == len(re.findall(r"^signal_name", text, re.M))
    res = T.Resolver()
    nm = sorted({e for n in nets for pc in n["edges"] for e in pc})
    rec, why = res.resolve(nm)
    assert all(w == "ok" for w in why) and (rec >= 0).all()   # A7: 100 % exact on the 10 corpus designs, here rb_000


def test_programmed_graph_traces(st, fired):
    g = T.Graph(st, fired["vendor"])
    roots = g.roots()
    assert roots
    nets = T.tracer_nets(g)
    covered = set().union(*[set(v) for v in nets.values()])
    assert covered <= set(fired["vendor"].tolist()) and len(covered) >= 0.99 * len(fired["vendor"])   # nets cover the programmed edges (loops excepted)


def test_lut_cells_cover_every_used_lut(st):
    need(os.path.join(D, "postfit.vo"), os.path.join(D, "bitstream.rbf"))
    from lifters.cycloneiv_clean import sofio
    try:
        lut = T.Lut()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))
    cells = lut.cells(T.plane_bits(os.path.join(D, "bitstream.rbf")))
    used = int((cells.sum(axis=2) > 0).sum())
    vo = open(os.path.join(D, "postfit.vo")).read()
    n_vo = len(re.findall(r"^// Location: LCCOMB_", vo, re.M))
    report("tracer-lut", sites_with_cells=used, vo_lcells=n_vo)
    assert cells.shape == (9360, 16, 16) and used == n_vo
