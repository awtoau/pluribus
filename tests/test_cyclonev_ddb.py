"""Cyclone V .ddb container decoder + option-RAM die byte (docs/cyclonev-ddb-format.md).

The ddb tests need the Quartus devinfo tree and skip without it; the die-byte tests are self-contained.
"""
import os
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_ddb_decode as dd  # noqa: E402
import cyclonev_decode as nd  # noqa: E402

E50F = os.path.join(dd.DEVINFO, "cyclonev", "cyclonev_e50f")
needs_quartus = pytest.mark.skipif(not os.path.isdir(E50F), reason="Quartus devinfo not installed")


def _rbf_with_die_byte(value):
    a = bytearray(b"\xff" * 0x80 + b"jjjj" + bytes(4 * 40 + 8))
    for k in range(8):
        if value >> k & 1:
            a[0x84 + (nd.DIE_BYTE_STRIP >> 3) + ((nd.DIE_BYTE_BIT0 + k) << 2)] |= 0x80 >> (nd.DIE_BYTE_STRIP & 7)
    return bytes(a)


@pytest.mark.parametrize("value", [0x05, 0x13, 0x00, 0xFF, 0xA5])
def test_die_byte_roundtrip(value):
    assert nd.die_byte(_rbf_with_die_byte(value)) == value


def test_detect_device():
    assert nd.detect_device(_rbf_with_die_byte(0x05)) == "5CEBA4U19C8"
    assert nd.detect_device(_rbf_with_die_byte(0x13)) == "5CEBA7U19C8"
    with pytest.raises(nd.ContainerError):
        nd.detect_device(_rbf_with_die_byte(0x42))


@needs_quartus
def test_container_zlib_and_trailer():
    f = os.path.join(E50F, "ddb_cyclonev_e50f_place.ddb")
    hdr, types = dd.check(f)
    assert hdr.method == dd.METHOD_ZLIB and hdr.raw_size == 3246003
    assert hdr.body_end < hdr.file_len
    assert [t[0] for t in types] == list(range(1, len(types) + 1))
    assert types[0][5] == "DYGR_PLACE_INFO_BODY"


@needs_quartus
def test_container_xz_and_hdr_strings():
    f = os.path.join(E50F, "ddb_cyclonev_e50f_hdr.ddb")
    hdr, types = dd.check(f)
    assert hdr.method == dd.METHOD_XZ
    names = dd.hdr_strings(f)[0]
    assert names[0] == "5CEFA4" and names[1] == "Cyclone V"


@needs_quartus
def test_asm_type_table_counts():
    f = os.path.join(E50F, "ddb_cyclonev_e50f_asm.ddb")
    hdr = dd.read_header(f)
    t = {x[5]: x for x in dd.read_types(f, hdr)}
    assert t["DYGR_ROUTE_ASM_NODE"][3] == 1054414
    assert t["unsigned short"][3] == 13229131
    assert t["DYGR_ROUTE_ASM_BIT"][3] == 29159476
    first = next(iter(dd.iter_body(f, hdr)))
    assert first[:16] == bytes.fromhex("04000000ce161000ce1610002a005400")


def test_truncated_file_rejected(tmp_path):
    p = tmp_path / "x.ddb"
    p.write_bytes(b"\x14\x00\x00\x00\xad\x0b\x01\x00" + bytes(200))
    with pytest.raises(dd.DdbError):
        dd.check(str(p))
