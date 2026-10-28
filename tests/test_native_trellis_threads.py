"""Concurrent read-only use of the shared native routing graph (#146).

N threads hammer the same graph object (globalise_net, tiles/wires/bels, has_wire, geometry)
and must return exactly what one thread returns.  Also: concurrent Chip() construction yields
ONE graph build per device.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import pytest  # noqa: E402

import toolchain  # noqa: E402
from native_trellis import pytrellis_compat as pt  # noqa: E402

DBROOT = toolchain.trellis_dbroot()
DEVICES = ["LFE5U-12F", "LCMXO2-1200"]
N_THREADS = 8


def _digest(rg, chip, sample):
    """Everything a lifter reads, as one comparable value."""
    out = []
    for (row, col, name) in sample:
        g = rg.globalise_net(row, col, name)
        out.append((g.loc.x, g.loc.y, g.id))
        out.append(rg.has_wire(col, row, name))
    for x in range(chip.get_max_col() + 1):
        for y in range(chip.get_max_row() + 1):
            t = rg.tiles[pt.Location(x, y)]
            out.append((x, y, tuple(sorted(t.wires.keys())),
                        tuple((k, b.type, b.z, tuple(sorted((p, w[0]) for p, w in b.pins.items())))
                              for k, b in sorted(t.bels.items())),
                        tuple(chip.get_tiles_by_position(y, x) and
                              [(i.info.name, i.info.type) for i in chip.get_tiles_by_position(y, x)])))
    return out


def _sample(rg, chip, k=4000):
    names = []
    for x in range(chip.get_max_col() + 1):
        for y in range(chip.get_max_row() + 1):
            for w in sorted(rg.tiles[pt.Location(x, y)].wires)[:6]:
                names.append((y, x, w))
    names += [(3, 3, "G_HPBX0000"), (3, 3, "G_VPTX0000"), (3, 3, "N1_" + "F0"), (0, 0, "bogus")]
    return names[:k]


@pytest.mark.parametrize("device", DEVICES)
def test_concurrent_reads_match_single_thread(device):
    pt.load_database(DBROOT)
    chip = pt.Chip(device)
    rg = chip.get_routing_graph(True, True)
    sample = _sample(rg, chip)
    ref = _digest(rg, chip, sample)
    with ThreadPoolExecutor(N_THREADS) as ex:
        outs = list(ex.map(lambda _i: _digest(rg, chip, sample), range(N_THREADS * 2)))
    assert all(o == ref for o in outs)


@pytest.mark.parametrize("device", DEVICES)
def test_concurrent_chip_construction_builds_once(device):
    pt.load_database(DBROOT)
    pt.clear_shared()
    with ThreadPoolExecutor(N_THREADS) as ex:
        chips = list(ex.map(lambda _i: pt.Chip(device), range(N_THREADS)))
    assert len({id(c._native) for c in chips}) == 1
    rgs = list(ThreadPoolExecutor(N_THREADS).map(lambda c: c.get_routing_graph(True, True), chips))
    assert len({id(r) for r in rgs}) == 1


def test_gil_stays_off():
    if getattr(sys, "_is_gil_enabled", lambda: True)():
        pytest.skip("not a free-threaded interpreter")
    assert sys._is_gil_enabled() is False
