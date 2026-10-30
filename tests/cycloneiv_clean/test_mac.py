"""MAC control-bit signatures: site A pair signature scored against the same pair at a second MAC column (#169)."""
from _hb import score_module
from conftest import report


def test_mac_signatures_cross_column():
    m = score_module("gxhb_macpa_base", "gxhb_macpb_base")
    rows, tot = m.score_mac()
    report("hardblocks_mac", features=len(rows), **tot)
    assert tot["wrong"] == 0 and tot["matched"] >= 30
    sign = next(r for r in rows if r["feature"] == "signed_ab")
    assert sign["matched"] == 2 and sign["missing"] == sign["extra"] == 0


def test_mac_instance_map():
    from lifters.cycloneiv_clean import mac
    assert len(mac.columns()) == 4 and mac.instance(103, 87) == 3 * 90 + 86
