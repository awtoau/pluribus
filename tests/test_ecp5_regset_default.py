"""#110: ECP5 FF REGSET default comes from device-db PLC2/bits.db (SET), not a hardcoded RESET."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from lifters import ecp5_lift  # noqa: E402


def test_regset_default_is_set_for_every_slice_register():
    d = ecp5_lift.plc_enum_defaults(os.path.join(REPO, "device-db"))
    for sl in "ABCD":
        for j in (0, 1):
            assert d[f"SLICE{sl}.REG{j}.REGSET"] == "SET"


def test_lifter_has_no_hardcoded_regset_default():
    src = open(os.path.join(REPO, "lifters", "ecp5_lift.py")).read()
    assert '"REGSET", "RESET")' not in src


def test_gsr_default_is_enabled_in_db_and_not_hardcoded():
    """#118: SLICE GSR omitted from a .config means the DB default (ENABLED)."""
    d = ecp5_lift.plc_enum_defaults(os.path.join(REPO, "device-db"))
    for sl in "ABCD":
        assert d[f"SLICE{sl}.GSR"] == "ENABLED"
    src = open(os.path.join(REPO, "lifters", "ecp5_lift.py")).read()
    assert '"GSR", "DISABLED")' not in src
