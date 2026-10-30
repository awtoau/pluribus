"""scripts/cycloneiv_clean_pin_clusters.py on the rb_000 corpus design: every emitted IO pad is counted, runs are consecutive (#168)."""
import os
import sys

from conftest import REPO, need

RB = os.path.join(REPO, "corpus", "cycloneiv", "gx150_rb_000")


def test_runs():
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import cycloneiv_clean_pin_clusters as C
    assert C.runs([5, 3, 4, 10, 4]) == [(3, 5), (10, 10)]
    assert C.runs([]) == []


def test_rb000_pad_counts():
    need(os.path.join(RB, "bitstream.rbf"), os.path.join(REPO, "databases", "cycloneiv", "io_decode.json"))
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import cycloneiv_clean_pin_clusters as C
    from lifters.cycloneiv_clean import emit
    nl = emit.Builder(emit.Ctx(), os.path.join(RB, "bitstream.rbf"), "rb_000", package="F896").run()
    ios = C.parse_io(emit.verilog(nl))
    assert len(ios) == len(nl.ios)
    s = C.stats(ios, "F896", "F896")
    assert s["pads"] == len(ios) and sum(s["direction"].values()) == len(ios)
    for side in s["sides"].values():
        assert side["pairs_both_p_n"] <= side["pairs_touched"]
        assert all(b >= a for a, b in side["runs"])
