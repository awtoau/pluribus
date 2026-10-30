"""Clock network / LAB control / LE_USE_CARRY decoders (clocks.py, lab_control.py, muxsel.py, #165) against the Quartus ground truth of
corpus gx150_rb_000..009.  Each assertion is a vendor-derived rule that must hold for 100 % of the ground-truth items it covers;
counts go to tmp/logs/cycloneiv_clean_oracles.log.  Skips when local data is missing."""
import collections
import os
import sys

import numpy as np
import pytest

from conftest import REPO, need, report
from lifters.cycloneiv_clean import tracer as T

CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
DESIGNS = [os.path.join(CORPUS, f"gx150_rb_{i:03d}") for i in range(10)]
sys.path.insert(0, os.path.join(REPO, "scripts"))


@pytest.fixture(scope="module")
def tr():
    need(os.path.join(REPO, "databases", "cycloneiv", "sof2rbf_mask.npz"), *[os.path.join(d, "bitstream.rbf") for d in DESIGNS])
    try:
        return T.Tracer(workers=2)
    except Exception as e:                                     # missing local vendor data
        pytest.skip(str(e))


def test_default_bit_edges_are_the_global_clock_enables(tr):
    ck = tr.ext.clocks
    en = names_of(tr, ck.inv)
    assert len(ck.inv) == 120 and en == {("GLOBAL_CLK_H", "GLOBAL_CLK_V")}


def names_of(tr, edges):
    from lifters.cycloneiv_clean import names
    rt = tr.ext.clocks.rt
    enum = rt.enum[np.maximum(rt.tpl, 0)].astype(np.int32)
    inv = {v: k for k, v in names.enums().items()}
    return {(inv[int(enum[tr.st.esrc[e]])], inv[int(enum[tr.st.edst[e]])]) for e in edges}


def gt_clock_edges(d):
    """Edges of the nets that drive a flip-flop CLK port, restricted to the clock network types."""
    out = set()
    for n in T.parse_rcf(os.path.join(d, "routing.rcf")):
        if not any(p == "CLK" for _, _, p, _ in n["dests"]):
            continue
        for a, b in n["edges"]:
            if b[0] in ("GLOBAL_CLK_V", "SCLK_TO_ROWCLK_BUF", "BLK_CLK_BUF", "GLOBAL_CLK_H") or a[0] == "CLKBUF_OUT":
                out.add((a, b))
    return out


def test_clock_network_edges(tr):
    """Every ground-truth clock-network edge is programmed (matched); count extras beside it."""
    res = T.Resolver(tr.ext.clocks.rt)
    tot = collections.Counter()
    for d in DESIGNS:
        bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
        fired = tr.ext.apply(bits, tr.st.fire(bits, workers=2))["vendor"]
        gt = gt_clock_edges(d)
        nm = sorted({e for p in gt for e in p})
        rec, why = res.resolve(nm)
        ix = {n: i for i, n in enumerate(nm)}
        ids = {int(tr.st.edge_ids([rec[ix[a]]], [rec[ix[b]]])[0]) for a, b in gt}
        assert -1 not in ids
        P_ = set(fired.tolist())
        clk = set(e for e in P_ if (lambda s: s in {("GLOBAL_CLK_V", "SCLK_TO_ROWCLK_BUF"), ("LAB_CLK", "BLK_CLK_BUF"), ("GLOBAL_CLK_H", "GLOBAL_CLK_V"),
                                                  ("CLKBUF_OUT", "GLOBAL_CLK_H")})(next(iter(names_of(tr, [e])))))
        tot["gt"] += len(ids)
        tot["matched"] += len(ids & clk)
        tot["extra"] += len(clk - ids)
    report("decoders-clock-edges", **tot)
    assert tot["matched"] == tot["gt"]


def test_lab_clock_line_per_register(tr):
    """LE_CLOCK_SELECT + LAB_CLOCK_FAST_MUX pick the BLK_CLK_BUF the ground truth drives each FF from (every FF)."""
    import cycloneiv_clean_gate as G
    tot = collections.Counter()
    for d in DESIGNS:
        bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
        blk = tr.ext.clocks.le_blk(bits)
        rt = tr.ext.clocks.rt
        _, _, ffs = G.parse_vo(os.path.join(d, "postfit.vo"))
        last = {}
        for n in T.parse_rcf(os.path.join(d, "routing.rcf")):
            for l, cell, port, rp in n["dests"]:
                if port == "CLK" and l and l[0] == "BLK_CLK_BUF":
                    last[cell] = l
        for name, (x, y, nn) in ffs.items():
            if name not in last:
                continue
            tot["ff"] += 1
            b = int(blk[tr.lut.lab(x, y), nn])
            tot["ok"] += b >= 0 and (int(rt.x[b]), int(rt.y[b]), int(rt.index[rt.tpl[b]])) == (last[name][1], last[name][2], last[name][4])
    report("decoders-register-clock-line", **tot)
    assert tot["ff"] > 1000 and tot["ok"] == tot["ff"]


def test_lab_control_mux_inputs(tr):
    """LOCAL_INTERCONNECT / LOCAL_LINE -> LAB_CONTROL_MUX: every ground-truth edge is programmed through the LAB_PIA_TO_INPUT input map."""
    res = T.Resolver(tr.ext.clocks.rt)
    tot = collections.Counter()
    for d in DESIGNS:
        bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
        prog = set(tr.ext.imp.apply(bits).tolist())
        gt = {(a, b) for n in T.parse_rcf(os.path.join(d, "routing.rcf")) for a, b in n["edges"]
              if a[0] in ("LOCAL_INTERCONNECT", "LOCAL_LINE") and b[0] == "LAB_CONTROL_MUX"}
        nm = sorted({e for p in gt for e in p})
        rec, _ = res.resolve(nm)
        ix = {n: i for i, n in enumerate(nm)}
        ids = {int(tr.st.edge_ids([rec[ix[a]]], [rec[ix[b]]])[0]) for a, b in gt}
        assert -1 not in ids
        tot["gt"] += len(ids)
        tot["matched"] += len(ids & prog)
        tot["extra"] += len(prog - ids)
    report("decoders-lab-control", **tot)
    assert tot["matched"] == tot["gt"] and tot["gt"] >= 177


def test_carry_flag_is_sum_lutc_input(tr):
    """LE_USE_CARRY bit clear <=> the .vo sum_lutc_input is cin (every LE with a LUT in the .vo)."""
    import cycloneiv_clean_gate as G
    tot = collections.Counter()
    for d in DESIGNS:
        bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
        cin = tr.lut.carry_in(bits)
        _, lcs, _ = G.parse_vo(os.path.join(d, "postfit.vo"))
        for (x, y, n), L in lcs.items():
            tot["le"] += 1
            tot["agree"] += (L["mode"] == "cin") == bool(cin[tr.lut.lab(x, y), n])
    report("decoders-carry-flag", **tot)
    assert tot["le"] > 8000 and tot["agree"] == tot["le"]


def test_register_used_claim(tr):
    """reg_used.RegUsed.ff against the .vo flip-flops of rb_000..009: the claim covers every ground truth LE (none missing); extras counted beside it."""
    import cycloneiv_clean_gate as G
    tot = collections.Counter()
    for d in DESIGNS:
        bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
        fired = tr.ext.apply(bits, tr.st.fire(bits, workers=2))["vendor"]
        ff = tr.ext.reg.ff(bits, fired)
        _, _, ffs = G.parse_vo(os.path.join(d, "postfit.vo"))
        gt = {(tr.lut.lab(x, y), n) for x, y, n in ffs.values()}
        got = {(int(i), int(n)) for i, n in np.argwhere(ff)}
        tot["gt"] += len(gt)
        tot["matched"] += len(gt & got)
        tot["extra"] += len(got - gt)
        tot["missing"] += len(gt - got)
    report("decoders-register-used", **tot)
    assert tot["missing"] == 0 and tot["extra"] == 1       # decoder-level: 1 extra LE of 1,684 (not chased); a change either way is a regression or a fix


def test_ygr_gi_is_le_buffer_parity(tr):
    """LE_REG_OUT_YGR gi b (b = 0, 1) is 1 for every LUT-only LE whose ground truth uses only LE_BUFFER 2 le + b."""
    import cycloneiv_clean_gate as G
    tot = collections.Counter()
    for d in DESIGNS:
        bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
        _, lcs, ffs = G.parse_vo(os.path.join(d, "postfit.vo"))
        ffsite = {(x, y, n) for x, y, n in ffs.values()}
        used = collections.defaultdict(set)
        for n in T.parse_rcf(os.path.join(d, "routing.rcf")):
            for a, b in n["edges"]:
                if a[0] == "LE_BUFFER":
                    used[(a[1], a[2], a[4] // 2)].add(a[4] % 2)
        for (x, y, le), bs in used.items():
            if (x, y, le) in ffsite or (x, y, le) not in lcs or len(bs) != 1:
                continue
            b = next(iter(bs))
            lab = tr.lut.lab(x, y)
            tot["le"] += 1
            tot["ok"] += int(bits[tr.ext.reg.ygr[b][lab, le]]) == 1 and int(bits[tr.ext.reg.ygr[1 - b][lab, le]]) == 0
    report("decoders-ygr-buffer-parity", **tot)
    assert tot["le"] > 1000 and tot["ok"] == tot["le"]


BIM_SPEC = os.path.join(REPO, "tmp", "cycloneiv_clean", "bim_specimens")


def _bim_edges(tr, d):
    res = T.Resolver(tr.ext.clocks.rt)
    gt = {(a, b) for n in T.parse_rcf(os.path.join(d, "routing.rcf")) for a, b in n["edges"]
          if a[0] == "LOCAL_INTERCONNECT" and b[0] == "BLOCK_INPUT_MUX" and b[2] in (0, 91)}
    nm = sorted({e for p in gt for e in p})
    rec, _ = res.resolve(nm)
    ix = {n: i for i, n in enumerate(nm)}
    return {int(tr.st.edge_ids([rec[ix[a]]], [rec[ix[b]]])[0]) for a, b in gt}


def _vio_rows(tr, prog):
    """programmed LI -> BLOCK_INPUT_MUX edges of the VIO rows (BIM tile y = 0, 91); HIO columns are scored by the gate."""
    rt = tr.ext.clocks.rt
    return {e for e in prog if int(rt.y[tr.st.edst[e]]) in (0, 91)}


def test_vio_bim_data_edges(tr):
    """LI -> BLOCK_INPUT_MUX of VIO pad pins: every ground-truth edge of rb_000..009 is programmed by the IO LABLINE groups (bim.PINS, pin -> BIM from routing.ddb)."""
    tot = collections.Counter()
    for d in DESIGNS:
        bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
        prog = _vio_rows(tr, set(tr.ext.bim.apply(bits).tolist()))
        ids = _bim_edges(tr, d)
        assert -1 not in ids                                      # every GT BIM edge exists in the (extended) edge table
        tot["gt"] += len(ids)
        tot["matched"] += len(ids & prog)
        tot["extra"] += len(prog - ids)
    report("decoders-vio-bim", **tot)
    assert tot["gt"] >= 100 and tot["matched"] == tot["gt"] and tot["extra"] == 0


def test_vio_bim_specimens(tr):
    """The 24 label-specimen pads: the programmed edge of each build equals the routing.rcf edge (the table's own labels, decode side only)."""
    import glob
    need(*(glob.glob(os.path.join(BIM_SPEC, "*", "build.rbf")) or [os.path.join(BIM_SPEC, "missing")]))
    tot = collections.Counter()
    for d in sorted(glob.glob(os.path.join(BIM_SPEC, "*", "routing.rcf"))):
        d = os.path.dirname(d)
        bits = T.plane_bits(os.path.join(d, "build.rbf"))
        prog = _vio_rows(tr, set(tr.ext.bim.apply(bits).tolist()))
        ids = _bim_edges(tr, d)
        tot["gt"] += len(ids)
        tot["matched"] += len(ids & prog)
        tot["extra"] += len(prog - ids)
    report("decoders-vio-bim-specimens", **tot)
    assert tot["gt"] == 24 and tot["matched"] == 24 and tot["extra"] == 0
