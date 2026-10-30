"""Configuration facts from the vendor pcf device payload (docs/cycloneiv-manual-review.md F6).  Skips without the local payload.

source: vendor-analysis/altera/analysis/ep4cgx150_pcf_payload.bin (extracted EP4CGX150 pcf record, local); handbook Table 10-2 IDCODE.
"""
import os
import struct

from conftest import REPO, VA, need

PAYLOAD = os.path.join(VA, "analysis", "ep4cgx150_pcf_payload.bin")
IDCODE = 0x028040DD          # source: Cyclone IV handbook vol.1 ch.10 Table 10-2 (version 0, part 0010 1000 0000 0100, mfg 000 0110 1110, LSB 1)


def test_pcf_payload_carries_idcode_with_full_mask():
    need(PAYLOAD)
    d = open(PAYLOAD, "rb").read()
    hits = [i for i in range(len(d) - 8) if struct.unpack_from("<II", d, i) == (IDCODE, 0xFFFFFFFF)]
    assert len(hits) == 1, hits        # one (idcode, mask) pair, mask = all 32 bits compared


# ---- dual-purpose configuration pads: the CRAM cells a QSF option changes, resolved to (asmdb group, VIO site) ----
PAIRS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp", "cycloneiv_clean", "option_pairs", "builds")
# pair id -> (QSF option, expected {(group, site)}); source: asmdb walk (site_bits) of the sof tag-17 diff of option_pairs builds, pin file for the ball -> site
DUAL = {
    "init_done_on": ("ENABLE_INIT_DONE_OUTPUT", {("MIO_OE_INVERT", 0)}),                              # AE8 INIT_DONE
    "crc_check_on": ("CRC_ERROR_CHECKING", {("MIO_OE_INVERT", 1), ("MIO_DATA_INVERT", 1)}),            # AD6 CRC_ERROR
    "nceo_io": ("CYCLONEII_RESERVE_NCEO_AFTER_CONFIGURATION USE AS REGULAR IO", {("MIO_OE_INVERT", 2)}),   # AE7 nCEO
    "reserve_dclk_io": ("RESERVE_DCLK_AFTER_CONFIGURATION USE AS REGULAR IO", {("MIO_OE_INVERT", 324), ("MIO_DATA_INVERT", 324)}),   # B3 DCLK (UDCLK pseudo pad)
    "scheme_ps": ("CYCLONEIII_CONFIGURATION_SCHEME PASSIVE SERIAL", {("MIO_OE_INVERT", 324), ("MIO_DATA_INVERT", 324)}),
    "spi_tristate_on": ("TRI_STATE_SPI_PINS", {("MIO_OE_INVERT", 324), ("MIO_DATA_INVERT", 324)}),
}


def _diff_addrs(pair):
    import numpy as np
    f = os.path.join(PAIRS, f"min.{pair}", "result.npz")
    b = os.path.join(PAIRS, "min.BASE", "result.npz")
    need(f, b)
    x = np.unpackbits(np.load(b)["cram"] ^ np.load(f)["cram"], bitorder="little")
    return [int(i) for i in np.nonzero(x)[0]]


def test_dual_purpose_pad_cells():
    import sys
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import cycloneiv_clean_dirt as D
    from lifters.cycloneiv_clean import asmdb_walk as W
    from lifters.cycloneiv_clean import sofio
    import pytest
    try:
        w = W.Walk()
    except sofio.VendorMissing as e:
        pytest.skip(str(e))
    names = D.enum_tables()["arch_group_type"]
    byaddr = {}
    for g in w.groups():
        if g["cls"] not in (5, 6, 7, 8) or g["btype"] != 6:
            continue
        n = len(g["bits"]) if g["cls"] == 7 else len(g.get("paths", []))
        for s in range(n):
            for a in W._site_bits(w, g, s):
                byaddr.setdefault(a, set()).add((names.get(g["type"], g["type"]), s))
    for pair, (_opt, want) in DUAL.items():
        got = set()
        for a in _diff_addrs(pair):
            got |= byaddr.get(a, set())
        assert got == want, (pair, got)


# ---- unused-pin states (scripts/cycloneiv_clean_io_unused.py builds): bus-hold, driving ground vs unspecified ----
UNUSED = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp", "cycloneiv_clean", "io_unused")


def test_unused_bus_hold_state():
    import collections
    import numpy as np
    import pytest
    from lifters.cycloneiv_clean import io_decode as D
    for pin in ("AD25", "C29", "A23"):
        need(*(os.path.join(UNUSED, pin, t, "result.npz") for t in ("pullup", "gnd", "unspec", "bushold")))
    try:
        chain = D.Chain()
    except Exception as e:     # noqa: BLE001  local vendor data missing
        pytest.skip(str(e))
    own = {b: n for g in chain.cff.values() for n, bs in g.items() for b in bs}
    for pin in ("AD25", "C29", "A23"):
        r = {t: np.load(os.path.join(UNUSED, pin, t, "result.npz")) for t in ("pullup", "gnd", "unspec", "bushold")}
        d = np.nonzero(r["bushold"]["cff"] != r["pullup"]["cff"])[0]
        got = collections.Counter(own.get(int(x)) for x in d)
        assert got == {"MIO_USE_BUS_HOLD": 446, "MIO_USE_PULL_UP": 446}, (pin, got)         # bus-hold state = pull-up cell off, bus-hold cell on, 446 unused sites
        assert not (r["bushold"]["cram"] ^ r["pullup"]["cram"]).any()
        assert (r["gnd"]["cff"] == r["unspec"]["cff"]).all() and (r["gnd"]["cram"] == r["unspec"]["cram"]).all()   # driving ground == unspecified, CFF and CRAM
