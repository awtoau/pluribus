"""IO configuration lives in the CFF region, not in asm.ddb CRAM (docs/altera/cycloneIV/cycloneiv-clean-io.md).  Counts go to the oracle log.

Vendor-derived checks: address tags, die head, sof section sizes, asm.ddb census, CFF -> rbf table.
Oracle (Quartus corpus, never an input): replica agreement over rbf files; IO site signatures in CFF space.
Missing is a fault: IO fields decoded = 0, reported as missing, not hidden.
"""
import collections
import glob
import os
import re

import numpy as np
import pytest

from conftest import REPO, need, report
from lifters.cycloneiv_clean import cycloneiv_io as IO
from lifters.cycloneiv_clean import plane as P

CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
LOC = re.compile(r"// Location: (IO[OI]BUF)_X(\d+)_Y(\d+)_N(\d+)")


@pytest.fixture(scope="module")
def cff():
    try:
        return IO.Cff()
    except IO.CffMissing as e:
        pytest.skip(str(e))


def test_classify_synthetic():
    a = np.array([5, 0x7FFFFFFF, 0xA0000000 | 17, 0x90000000 | 3, 0x88000000 | 9, 0x84000000 | 2, 0xFFFFFFFD, 0xB0000000 | 1])
    sp, ix = IO.classify(a)
    assert sp.tolist() == ["CRAM", "CRAM", "CFF", "UNVM", "OPTION", "DPRIO", "LITERAL", "CFF"]
    assert ix[:6].tolist() == [5, 0x7FFFFFFF, 17, 3, 9, 2]


def test_die_head():
    from lifters.cycloneiv_clean import sofio
    try:
        h = IO.die_head()
    except sofio.VendorMissing as e:
        pytest.skip(f"vendor file missing: {e}")
    report("io_die_head", **h)
    assert h["num_bits"] == P.N_BITS            # CRAM = geometry A6, independent source (pcf / rbf)
    assert h["num_unvm_bits"] == 0


def test_sof_sections():
    from lifters.cycloneiv_clean import sofio
    try:
        sizes = IO.sof_section_sizes(sofio.programmer_sof("sfl_ep4cgx150.sof"))
        h = IO.die_head()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))
    report("io_sof_sections", sizes=sizes, cff_bits=h["num_cff_bits"])
    assert sizes[IO.SOF_TAG_CRAM] == IO.packed_len(h["num_bits"])
    assert sizes[IO.SOF_TAG_CFF] == IO.packed_len(h["num_cff_bits"])     # CFF is its own sof section


def test_asm_ddb_is_cram_only(asm):
    census, lo, hi = IO.asm_census(asm)
    report("io_asm_census", census=census, min=lo, max=hi)
    assert census == {"CRAM": len(asm.pos)}      # 0 entries in CFF / UNVM / OPTION / DPRIO
    assert hi < P.N_BITS


def test_cff_table(cff):
    from lifters.cycloneiv_clean import sofio
    try:
        want = IO.die_head()["num_cff_bits"]
    except sofio.VendorMissing as e:
        pytest.skip(str(e))
    mult = collections.Counter(cff.count.tolist())
    frames = sorted(set(cff.cells[:, 0].tolist()))
    report("io_cff_table", bits=cff.n_bits, multiplicity=dict(mult), frames=[frames[0], frames[-1]], cells=len(cff.cells))
    assert cff.n_bits == want and (cff.count > 0).all()           # every vendor CFF bit seen, none unseen
    assert set(mult) == {4}                                          # check groups (frame-end parity cells) dropped by cycloneiv_clean_cff_tables.data_groups
    assert frames[0] >= 1 and frames[-1] < P.RBF_PRE_FRAMES        # periphery frames only, never a CRAM frame
    assert (cff.primary[..., 1] < P.RBF_FRAME_BYTES).all()


def _rbfs(n):
    return sorted(glob.glob(os.path.join(CORPUS, "gx150_sp_*", "bitstream.rbf")))[:n]


def test_replicas_agree_in_quartus_rbfs(cff):
    files = _rbfs(60)
    need(*(files[:1] or [os.path.join(CORPUS, "gx150_sp_000", "bitstream.rbf")]))
    bad = cells = 0
    for f in files:
        _, mis = cff.read(f)
        bad += mis
        cells += cff.n_bits * IO.CFF_REPLICAS
    report("io_replica_agreement", designs=len(files), cells=cells, matched=cells - bad, wrong=bad)
    assert bad == 0


def test_io_site_signatures_in_cff_space(cff):
    """Oracle: per used IO site, CFF bits set in >= 95 % of designs using it and <= 3 % of the rest.  Specimen shape only."""
    files = _rbfs(150)
    need(*(files[:1] or [os.path.join(CORPUS, "gx150_sp_000", "bitstream.rbf")]))
    vals, sites = [], []
    for f in files:
        v, _ = cff.read(f)
        vals.append(v)
        text = open(os.path.join(os.path.dirname(f), "postfit.vo")).read()
        sites.append({(m[1], int(m[2]), int(m[3]), int(m[4])) for m in LOC.finditer(text)})
    V = np.stack(vals).astype(np.float32)
    use = collections.defaultdict(list)
    for i, s in enumerate(sites):
        for k in s:
            use[k].append(i)
    shapes = collections.Counter()
    sigs = collections.Counter()
    for k, pos in use.items():
        if len(pos) < 8:
            continue
        neg = np.setdiff1d(np.arange(len(files)), pos)
        if not len(neg):
            continue
        cand = np.nonzero((V[pos].mean(0) >= 0.95) & (V[neg].mean(0) <= 0.03))[0]
        sigs[(k[0], len(cand))] += 1
        if len(cand):
            shapes[(k[0], tuple((cand - cand[0]).tolist()))] += 1
    report("io_site_signatures", designs=len(files), sites_used=len(use), signature_bits=sorted((f"{a}:{b}", n) for (a, b), n in sigs.items()),
           shapes=sorted(((a, list(s)), n) for (a, s), n in shapes.items()), fields_decoded=0)
    # IOOBUF: one shared 9-bit shape; IOIBUF: one bit.  Sites below that count are reported, not hidden.
    assert max(n for (a, _), n in shapes.items() if a == "IOOBUF") >= len(files)   # >= 1 per design (150 / 150 on the full corpus, 74 / 73 on the pruned one)
    assert all(len(s) == 1 for (a, s) in shapes if a == "IOIBUF")


def test_pin_mode_mux_values():
    assert sorted(IO.PIN_MODE_MUX.values()) == list(range(7))      # direction mux: 7 selectable states, 0 = input


def test_asmdb_main_stream():
    from lifters.cycloneiv_clean import sofio
    try:
        b = IO.asmdb_body()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))
    s = IO.asmdb_main_stream(b)
    sp = collections.Counter(IO.classify(np.array(s["m_default_bit_list"]))[0].tolist())
    report("io_asmdb_main_stream", block_types=s["block_types"], arch_groups=s["m_arch_group_list"],
           default_groups=s["m_default_group_list"], default_bits=dict(sp), forced_bits=len(s["m_forced_bit_list"]),
           end=s["end"], body=len(b))
    assert len(s["block_types"]) == 8 and sum(s["m_arch_group_list"].values()) == 6087
    assert s["m_hc_wires"] == 0 and s["end"] < len(b)
    assert sp["CFF"] > 0 and sp["OPTION"] > 0                  # default bits exist in both peripheral spaces


def test_asmdb_class_binding():
    from lifters.cycloneiv_clean import sofio
    try:
        path = os.path.normpath(os.path.join(sofio.quartus_bin(), "..", "common", "devinfo", "cycloneivgx", IO.ASMDB_NAME))
        types = {i: (name, cnt) for i, _sz, cnt, name in IO.ddb_types(path)}
        s = IO.asmdb_main_stream(IO.asmdb_body(path))
    except sofio.VendorMissing as e:
        pytest.skip(str(e))
    bound = {name: (s["m_arch_group_list"].get(i, 0), cnt) for i, (name, cnt) in types.items() if i in s["m_arch_group_list"]}
    report("io_asmdb_class_binding", bound=bound, block_info=types[2])
    assert types[2] == ("ASMDB_BLOCK_INFO", 8) and len(s["block_types"]) == 8
    assert bound["ASMDB_ARCH_GROUP_CALC"] == (277, 277)                  # tag >> 2 -> type table class
    assert all(m <= c for m, c in bound.values())                        # main-stream pointers <= objects of the class
