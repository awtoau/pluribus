"""Cyclone V PRAM-only access: light tables (no routing), PRAM/ORAM planes, bit-owner map.

PRAM planes need no CRAM, so this works on images whose CRAM is not readable.
Geometry and block tables are the native decoder's (scripts/cyclonev_native_tables.py).
"""
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_db_import as cvd  # noqa: E402
import cyclonev_decode as cdc  # noqa: E402
import cyclonev_decompress as cd  # noqa: E402
import cyclonev_native_tables as nt  # noqa: E402

DEVICE_BY_DIE_BYTE = {0x05: "5CEBA4U19C8", 0x13: "5CEBA7U19C8"}
_CACHE = {}


def light_tables(name):
    """Tables for PRAM decode only (no routes/patterns): ~100 MB instead of 1-4 GB."""
    if name in _CACHE:
        return _CACHE[name]
    mdl = nt.parse_model(name)
    die = mdl["die"]
    g = cvd.parse_cvd_file(os.path.join(nt.MISTRAL_ROOT, "libmistral", f"cvd-{die}.cc"))
    pram = nt.parse_pram(die)
    fixed, dq = nt.fixed_and_dqs16(pram)
    t = dict(model=mdl, die=die, geom=g, routes={"type_names": []}, p2r=[], p2p=[], fixed=fixed, dqs16=dq,
             iob=nt.parse_iob(die, pram), tile_types={}, pos={}, pins=nt.parse_pkg(die, mdl["pkg"]), dcram=[],
             muxes=nt.block_muxes(), pram_blocks=pram)
    _CACHE[name] = t
    return t


def read_image(data):
    """(die byte, aligned bytes, sync offset). Realigns a bit-shifted container."""
    s, sh = cd.find_sync(data)
    d = cd.realign(data, sh) if sh else data
    return cd.oram_strip(d, s, 6) >> 19 & 0xFF, d, s


def load_planes(data, tables=None):
    """-> (model, Bits) with oram + pram planes filled from a raw .rbf (compressed or not)."""
    db, d, _ = read_image(data)
    dev = DEVICE_BY_DIE_BYTE[db]
    tb = tables or light_tables(dev)
    geo = cdc.Geometry(tb["geom"])
    a = np.frombuffer(d, np.uint8)
    b = cdc.Bits(geo)
    b.raw = a
    for strip in range(32):
        for bit in range(40):
            if a[0x84 + (strip >> 3) + (bit << 2)] & (0x80 >> (strip & 7)):
                b.oram[strip] |= 1 << bit
    for bit in range(32):
        cnt = geo.pram_sizes[bit]
        if not cnt:
            continue
        i = np.arange(cnt)
        base = geo.mpram - i - 1
        idx = geo.oram_frame_bytes + 4 + (bit >> 3) + base * 4 + (base // geo.fs) * 8
        b.pram[bit] = ((a[idx] & (1 << (bit & 7))) != 0).astype(np.uint8)
    m = cdc.Model(tb, None, claims=True)
    m.bits = b
    return m, b, db, dev


def owners(m):
    """(strip, pos) -> (block, tile pos, mux name, span idx, bit idx in mux). Last writer wins on double claims."""
    own = {}
    for key, mk, tiles, mode in m.pram_group_list():
        for mx in m.mux[mk]:
            for i in range(mx["span"]):
                bits = mx["bits"][i]
                for (pos, base, var) in tiles:
                    if mx["variant"] not in (-1, var):
                        continue
                    strip = (base >> 16) & 31
                    for k, bo in enumerate(bits):
                        p = (base & 0xFFFF) + bo
                        if base & (1 << 23):
                            p = cdc.dqs16_adjust(p, bo, bool(base & (1 << 22)))
                        own[(strip, p)] = (key, pos, mx["mux"], i, k)
    return own


def set_bits(b):
    return {(s, int(p)) for s in range(32) for p in np.nonzero(b.pram[s])[0]}
