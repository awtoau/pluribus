"""emit.py: rb_000 emits parseable Verilog with the structural counts of the post-fit netlist (#165)."""
import os
import subprocess

from conftest import REPO

RB = os.path.join(REPO, "corpus", "cycloneiv", "gx150_rb_000")


def test_emit_rb000_matches_postfit_counts(tmp_path):
    import sys
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    from lifters.cycloneiv_clean import emit
    import cycloneiv_clean_emit_check as C
    nl = emit.Builder(emit.Ctx(), os.path.join(RB, "bitstream.rbf"), "rb_000").run()
    lcs, _ln, ffs, _fn, _q = C.parse_gt(RB)
    assert {(L["x"], L["y"], L["le"]): L["init"] for L in nl.luts} == {k: g["mask"] for k, g in lcs.items()}
    assert {(F["x"], F["y"], F["le"]) for F in nl.ffs} == set(ffs)
    v = tmp_path / "e.v"
    v.write_text(emit.verilog(nl))
    assert subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "e.vvp"), str(v)], capture_output=True).returncode == 0
