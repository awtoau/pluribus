"""EFB 0x72 payload -> primitive attributes (efb_decode.py).

Payloads are Diamond-oracle measurements (scripts/efb_oracle.py), one attribute
changed per build against the SPI-slave default.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import efb_decode  # noqa: E402

DEFAULT = [0x00, 0x80, 0x00, 0x00, 0xFF, 0, 0, 0, 0, 0x00]


def with_(**kw):
    p = list(DEFAULT)
    for k, v in kw.items():
        p[int(k[1:])] = v
    return p


CASES = [
    (DEFAULT, {"SPI_MODE": "SLAVE"}),
    (with_(b2=0x01), {"SPI_LSB_FIRST": "ENABLED"}),
    (with_(b2=0x02), {"SPI_PHASE_ADJ": "ENABLED"}),
    (with_(b2=0x04), {"SPI_CLK_INV": "ENABLED"}),
    (with_(b2=0x28), {"SPI_SLAVE_HANDSHAKE": "ENABLED"}),
    (with_(b1=0xC0), {"SPI_WAKEUP": "ENABLED"}),
    (with_(b9=0x02), {"SPI_INTR_RXOVR": "ENABLED"}),
    (with_(b9=0x04), {"SPI_INTR_TXOVR": "ENABLED"}),
    (with_(b9=0x08), {"SPI_INTR_RXRDY": "ENABLED"}),
    (with_(b9=0x10), {"SPI_INTR_TXRDY": "ENABLED"}),
    (with_(b2=0x80), {"SPI_MODE": "MASTER", "SPI_CLK_DIVIDER": "1"}),
    (with_(b2=0x80, b3=0x07), {"SPI_MODE": "MASTER", "SPI_CLK_DIVIDER": "8"}),
]


@pytest.mark.parametrize("payload,expect", CASES)
def test_single_attribute(payload, expect):
    attrs, unexplained = efb_decode.decode_spi(payload)
    assert unexplained == []
    for k, v in expect.items():
        assert attrs[k] == v
    base, _ = efb_decode.decode_spi(DEFAULT)
    changed = {k for k in attrs if attrs[k] != base.get(k)}
    assert changed <= set(expect)       # nothing else moved


def test_unknown_bits_are_reported_not_guessed():
    _, unexplained = efb_decode.decode_spi(with_(b6=0x40))
    assert unexplained == [("SPISR", 6, 0x40)]


def test_block_enables():
    rows = [(0x54, "SPI", 10, DEFAULT)]
    attrs, unexplained, _ = efb_decode.decode(rows)
    assert attrs["EFB_SPI"] == "ENABLED"
    assert attrs["EFB_TC"] == attrs["EFB_I2C1"] == attrs["EFB_I2C2"] == "DISABLED"
    assert unexplained == []
