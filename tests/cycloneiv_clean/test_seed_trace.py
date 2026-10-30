"""scripts/cycloneiv_clean_seed_trace.py: lock state of a hand-built XNOR LFSR, and the seed of the Quartus PRBS15 specimen (skipped when absent)."""
import logging
import os
import sys

from conftest import REPO, need

sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cycloneiv_clean_seed_trace as ST  # noqa: E402
from lifters.cycloneiv_clean import patterns as P  # noqa: E402
from test_patterns import fib_netlist  # noqa: E402

SPEC = os.path.join(REPO, "tmp", "sig", "prbs15_lfsr", "bitstream.rbf")
SEED = 0x6E2A      # w_prbs15 reset value in tmp/sig/prbs15_lfsr/w.v


def test_xnor_lock_state_is_all_ones():
    nl = fib_netlist(15, [13, 14])
    D = P.Design(nl).prepare()
    ffs = [f"ff_{i}_1_0" for i in range(15)]
    assert ST.fixed_point(D, ffs) == [1] * 15


def test_specimen_seed_popcount_and_reset_pad():
    need(SPEC)
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    with heavy_guard.lease(gb, "cyc4_seed_trace_test", logging.getLogger("t")):
        nl = emit.Builder(emit.Ctx(), SPEC, "seed_test").run()
    D = P.Design(nl).prepare()
    g = P.detect(nl)["parallel"][0]
    r = ST.trace(D, g["members"], 0, {}, None)
    assert len(r["seed"]) == 1
    s = r["seed"][0]
    assert sum(int(c) for c in s["logical"]) == bin(SEED).count("1")      # state order is a permutation of w.v's `st`
    assert not s["locked"]
    assert list(s["fixed"].values()) == [1] and len(s["fixed"]) == 1      # reset pad io_A27 = rst
