"""O5: the mirrored 256-frame blocks of A5 (plane.sof_to_rbf mask).
(a) How many validated LUT (O1) and routing (O2) cells fall in mirrored cells.
(b) Real Quartus-built sofs (quartus_asm, from corpus designs and the LUT specimens; scripts/cycloneiv_clean_lut_specimens.py real|build)
    vs the rbf quartus_cpf made from the same sof: every cell compared, mirrored cells counted separately.  Any mismatch fails.
Skips without the local builds / tables."""
import glob
import os

import numpy as np
import pytest

import o1_model as M
from conftest import REPO, need, report
from lifters.cycloneiv_clean import plane as P
from lifters.cycloneiv_clean import sofio as S
from test_o2_r4_arcs import arcs, clean_ids, group_of, rows  # noqa: F401  (fixtures + helpers)

CHUNK = 4_000_000
SEEN = []          # set bits inside mirrored cells, per real sof compared
LUT_SPEC = os.path.join(REPO, "tmp", "cycloneiv_clean", "lut_specimens")
REAL = os.path.join(REPO, "tmp", "cycloneiv_clean", "real_sofs")


def mirrored(addr, tables):
    """True where A5 moves the cell off the default frame reversal (r != 6153 - s)."""
    r, _, _ = P.sof_to_rbf(addr, tables)
    return r != P.FRAMES - 1 - (np.asarray(addr, np.int64) % P.FRAMES)


def test_o5_table_size(tables):
    n = 0
    for a in range(0, P.N_BITS, CHUNK):
        n += int(mirrored(np.arange(a, min(a + CHUNK, P.N_BITS), dtype=np.int64), tables).sum())
    report("O5-table", mirrored_cells=n, blocks=len(tables.blocks), mask_cells_per_frame=int(tables.mask.sum()),
           cells=P.N_BITS)
    assert n == int(tables.mask.sum()) * 256 * len(tables.blocks)


def test_o5_lut_cells_in_mirrored(tables):
    need(M.BODY, M.BLK)
    hi0, lo = M.instance_cells()
    dx, dy = M.blkrba()
    c, r, le, k = np.meshgrid(*[np.arange(n) for n in (M.COLS, M.ROWS_, M.LES, M.KS)], indexing="ij")
    a = M.addresses(c, r, le, k, hi0, lo, dx, dy, 1, 1).ravel()
    m = mirrored(a, tables)
    cols = np.unique(c.ravel()[m])
    report("O5-lut", cells=int(a.size), mirrored=int(m.sum()), columns_touched=len(cols), columns=M.COLS)


def test_o5_routing_cells_in_mirrored(rows, clean_ids, routing, asm, tables):
    allc = prog = tot_arcs = hit_arcs = ngroups = 0
    allm = progm = 0
    for r, (s, d) in zip(rows, clean_ids):
        g = None if s is None or d is None else group_of(routing, asm, s, d)
        if g is None:
            continue
        ngroups += 1
        addr = asm.addr(g)
        b0, b1 = asm.flags(g)
        p = (b0 == 1) | (b1 == -1)
        m = mirrored(addr, tables)
        allc += len(addr)
        allm += int(m.sum())
        prog += int(p.sum())
        progm += int((m & p).sum())
        hit_arcs += bool(m.any())
    report("O5-routing", arcs=len(rows), arcs_with_group=ngroups, group_cells=allc, group_cells_mirrored=allm,
           programmed_cells=prog, programmed_mirrored=progm, arcs_touching_mirrored=hit_arcs)


def sof_bits_any(path):
    """S.sof_bits for both container forms: quartus_asm writes a plain sof (magic SO), the programmer sofs are gzipped."""
    import gzip
    raw = open(path, "rb").read()
    d = raw if raw[:2] == b"SO" else gzip.decompress(raw)
    for tag, off, ln in S._sections(d):
        if tag == 17:
            b = np.unpackbits(np.frombuffer(d[off + 12:off + ln], np.uint8), bitorder="little")
            assert len(b) == P.N_BITS, len(b)
            return b
    raise AssertionError("no tag 17 section")


def real_sofs():
    out = sorted(glob.glob(os.path.join(REAL, "*", "build.sof")))
    out += [os.path.join(LUT_SPEC, n, "build.sof") for n in ("base", "t00", "t13") if os.path.exists(os.path.join(LUT_SPEC, n, "build.sof"))]
    return out


@pytest.mark.parametrize("sof", real_sofs(), ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_o5_real_sof_vs_rbf(sof, tables):
    rbf = os.path.join(os.path.dirname(sof), "build.rbf")
    need(rbf)
    bits = sof_bits_any(sof)
    got = S.rbf_cram(rbf)
    tot_bad = mir_cells = mir_set = mir_bad = naive_bad = 0
    for a in range(0, P.N_BITS, CHUNK):
        i = np.arange(a, min(a + CHUNK, P.N_BITS), dtype=np.int64)
        r, j, k = P.sof_to_rbf(i, tables)
        m = r != P.FRAMES - 1 - i % P.FRAMES
        bad = got[r, j - 1, k] != bits[i]
        r0 = P.FRAMES - 1 - i % P.FRAMES
        naive = got[r0, j - 1, k] != bits[i]
        tot_bad += int(bad.sum())
        mir_cells += int(m.sum())
        mir_set += int((m & (bits[i] == 1)).sum())
        mir_bad += int((m & bad).sum())
        naive_bad += int((m & naive).sum())
    name = os.path.relpath(os.path.dirname(sof), REPO).split(os.sep)[-1]
    report("O5-sof", design=name, set_bits=int(bits.sum()), mirrored_cells=mir_cells, set_bits_in_mirrored=mir_set,
           mismatching_all=tot_bad, mismatching_mirrored=mir_bad, mismatching_if_mirror_ignored=naive_bad)
    SEEN.append(mir_set)
    assert tot_bad == 0 and mir_bad == 0


def test_o5_some_real_sof_has_content_in_mirrored_cells():
    """Without set bits inside mirrored cells the comparison above says nothing about the mirror: fail loudly."""
    if not SEEN:
        pytest.skip("no real sof compared")
    assert max(SEEN) > 0, "no real Quartus sof sets a bit inside a mirrored cell: the mirror is unverified on real content"
