"""scripts/cycloneiv_clean_mac_check.py parse_const_pins on a synthetic postfit.vo MAC block (no Quartus / corpus needed)."""
import os
import sys

from conftest import REPO

sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_mac_check as M  # noqa: E402

BODY = """cycloneiv_mac_mult \\m|mac_mult2 (
\t.signa(gnd),
\t.dataa({\\da[3]~input_o ,vcc,gnd,\\da[0]~input_o }),
\t.datab({gnd,gnd,
vcc,\\db[0]~input_o }),
\t.devclrn(devclrn));
"""


def test_const_pins_bus_msb_first():
    assert M.parse_const_pins(BODY) == {"DATAA[2]": "vcc", "DATAA[1]": "gnd", "DATAB[3]": "gnd", "DATAB[2]": "gnd", "DATAB[1]": "vcc"}


def test_no_const():
    assert M.parse_const_pins(".dataa({\\a ,\\b }),\n.datab({\\c ,\\d })") == {}
