"""High-level corpus (scripts/cycloneiv_hl_corpus.py): generator determinism, manifest consistency, emitted FF count vs Quartus fit (#165)."""
import json
import os
import subprocess
import sys

import pytest

from conftest import REPO

sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_hl_corpus as H  # noqa: E402

ROOT = os.path.join(REPO, "corpus", "cycloneiv")


def test_generator_deterministic_and_manifest_consistent():
    for kind in ("counter", "fsm", "fifo", "mix", "dpath"):
        a, b = H.make(kind, 3), H.make(kind, 3)
        assert a.verilog() == b.verilog() and a.truth == b.truth
        assert H.expected(a) == dict(sorted(a.counts.items()))
        assert any(t["role"] == "dut" for t in a.truth)
        assert sum(1 for t in a.truth if t["role"] == "observer" and t["kind"] == "xor_reduce") == 1


def test_minimal_io_style_has_one_clock_one_output():
    v = H.make("mac", 1).verilog()
    assert v.count("input clk") == 1 and "output y" in v and "input [" not in v


def test_generated_designs_parse(tmp_path):
    names = []
    for kind in H.PLAN:
        names.append(H.write_design(H.make(kind, 1), tmp_path))
    assert H.lint(tmp_path, names) == []


def test_built_design_ff_count_matches_fit():
    d = os.path.join(ROOT, "hl_counter_1")
    for f in ("bitstream.rbf", "src/hl_truth.json"):
        if not os.path.exists(os.path.join(d, f)):
            pytest.skip(f"local data missing: {f}")
    truth = json.load(open(os.path.join(d, "src", "hl_truth.json")))
    if not truth.get("fit"):
        pytest.skip("no fit summary")
    from lifters.cycloneiv_clean import emit
    nl = emit.Builder(emit.Ctx(), os.path.join(d, "bitstream.rbf"), "hl_counter_1").run()
    assert len(nl.ffs) == truth["fit"]["registers"]
    assert subprocess.run(["iverilog", "-g2012", "-o", os.devnull, os.path.join(d, "src", "top.v")]).returncode == 0
