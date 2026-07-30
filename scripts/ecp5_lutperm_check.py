#!/usr/bin/env python3.15t
"""Is a recovered LUT INIT an input-PERMUTATION of the reference INIT?

Explains the one round-trip discrepancy that is not a lifter bug.

nextpnr-ecp5 routes LUT inputs through permutation pseudo-pips: any of the
four physical slice inputs A/B/C/D can carry any of the LUT's logical inputs.
When the router picks a permutation it rewrites the INIT word to match, so the
bitstream's INIT and the pre-route netlist's INIT differ while describing the
SAME function.  (`get_routing_graph_ecp5` builds that crossbar explicitly —
the `include_lutperm_pips` argument.)

So an exact INIT comparison is the wrong test.  The right test is: does there
exist a permutation of the four inputs that maps one INIT onto the other?  If
yes, the lifter recovered the function correctly and only the input labelling
differs — which the routing already tells us.

INIT bit indexing follows the `.config` convention: bit i of the 16-bit word
is the output for {D,C,B,A} = i, i.e. A is the LSB of the index.

    python3.15t scripts/ecp5_lutperm_check.py <ref-dir> [--device LFE5U-12F]

Logs to ./tmp/logs/ecp5_lutperm_check.log as well as the terminal.
"""
import argparse
import itertools
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain  # noqa: E402  (path set above)

DEF_DBROOT = toolchain.trellis_dbroot()


def setup_logging(name):
    os.makedirs("tmp/logs", exist_ok=True)
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(f"tmp/logs/{name}.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def init_to_bits(init):
    """'0101...' (MSB-first, 16 chars) -> list indexed by {D,C,B,A}."""
    s = init.strip()
    # The textcfg/JSON word is written MSB-first, so index i (A as LSB) is
    # character (15 - i).
    return [int(s[15 - i]) for i in range(16)]


def permute(bits, perm):
    """Apply an input permutation: physical input `perm[j]` carries logical j."""
    out = [0] * 16
    for i in range(16):
        # i is the physical index {D,C,B,A}; build the logical index.
        li = 0
        for j in range(4):
            if (i >> perm[j]) & 1:
                li |= 1 << j
        out[i] = bits[li]
    return out


def find_perm(want, got):
    """Return a permutation mapping `want` onto `got`, or None."""
    wb, gb = init_to_bits(want), init_to_bits(got)
    for perm in itertools.permutations(range(4)):
        if permute(wb, perm) == gb:
            return perm
    return None


_IDX = {"A": 0, "B": 1, "C": 2, "D": 3}


def tied_inputs(slice_enums, k):
    """Physical LUT inputs forced to a constant by the slice input muxes.

    `.config` carries per-input muxes like `SLICEA.A0MUX 1`, meaning the K0
    LUT's physical A input is tied to constant 1 rather than driven from the
    fabric.  The bitstream INIT is then written *pre-folded* for that constant
    — the vendor tool bakes the cofactor into the truth table.  So the
    reference INIT (which is the unfolded function) only matches after the
    same cofactor is applied.

    This is not an ECP5 quirk so much as a general Trellis one; it shows up
    here because nextpnr uses the tie-off muxes heavily for CCU2 carry cells,
    where a LUT often needs fewer than four real inputs.

    Returns {physical_index: value}.
    """
    tied = {}
    for letter, idx in _IDX.items():
        v = slice_enums.get(f"{letter}{k}MUX")
        if v in ("0", "1"):
            tied[idx] = int(v)
    return tied


def cofactor(bits, tied):
    """Fold constant-tied inputs into a truth table (see tied_inputs)."""
    out = [0] * 16
    for i in range(16):
        src = i
        for idx, v in tied.items():
            src = (src | (1 << idx)) if v else (src & ~(1 << idx))
        out[i] = bits[src]
    return out


def find_perm_with_ties(want, got, tied):
    """Permutation mapping `want` onto `got` once `tied` inputs are folded."""
    wb, gb = init_to_bits(want), init_to_bits(got)
    for perm in itertools.permutations(range(4)):
        if cofactor(permute(wb, perm), tied) == gb:
            return perm
    return None


def functions_equal(want, got, tied):
    """Do the two INITs describe the same function of the LIVE inputs?

    A tied input contributes nothing, so the comparison must ignore it — but
    it must ignore it on BOTH sides, and it must allow the live inputs to have
    been permuted onto different physical positions (nextpnr's lutperm
    crossbar moves them freely).

    So: enumerate permutations, apply, and compare only over the sub-cube
    where the tied inputs hold their tied value.  Equivalently, compare the
    cofactored tables.  A LUT that reads only B while A/C/D are tied is
    equal to a reference XOR(A,B) only if the reference's live inputs land on
    the same live positions — which is exactly what the permutation search
    decides.
    """
    wb, gb = init_to_bits(want), init_to_bits(got)
    live = [i for i in range(4) if i not in tied]
    if not live:
        # Fully tied: both sides reduce to a single constant.
        return cofactor(wb, tied)[0] == cofactor(gb, tied)[0]
    for perm in itertools.permutations(range(4)):
        pw = cofactor(permute(wb, perm), tied)
        if pw == cofactor(gb, tied):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref_dir")
    ap.add_argument("--device", default="LFE5U-12F")
    ap.add_argument("--dbroot", default=DEF_DBROOT)
    args = ap.parse_args()

    log = setup_logging("ecp5_lutperm_check")
    from lifters.ecp5_lift import ECP5Lift
    from scripts.ecp5_roundtrip import load_truth

    t0 = time.time()
    lift = ECP5Lift(args.device, dbroot=args.dbroot)
    log.info("routing graph built in %.1fs", time.time() - t0)
    pc = lift.parse_config(os.path.join(args.ref_dir, "ref.config"))
    combs, _ffs, _pios, _counts = load_truth(
        os.path.join(args.ref_dir, "ref_placed.json"))

    exact = perm_ok = tie_ok = unexplained = 0
    bad = []
    for key, truth in sorted(combs.items()):
        want = truth["init"]
        got = pc.lut_init.get(key)
        if got is None or not want:
            continue
        if want == got:
            exact += 1
            continue
        if find_perm(want, got) is not None:
            perm_ok += 1
            continue
        r, c, sl, k = key
        tied = tied_inputs(pc.slice_enum.get((r, c, sl), {}), k)
        if tied and functions_equal(want, got, tied):
            tie_ok += 1
        else:
            unexplained += 1
            bad.append((key, want, got, tied))

    total = exact + perm_ok + tie_ok + unexplained
    log.info("LUT INIT vs reference over %d sites:", total)
    log.info("  identical                       %d", exact)
    log.info("  input-permutation equivalent    %d", perm_ok)
    log.info("  equivalent after constant ties  %d", tie_ok)
    log.info("  UNEXPLAINED                     %d", unexplained)
    for key, want, got, tied in bad[:20]:
        log.error("  UNEXPLAINED %s want=%s got=%s tied=%s",
                  key, want, got, tied)

    if unexplained:
        log.error("FAILED: %d LUTs are not permutations of the reference",
                  unexplained)
        return 1
    log.info("PASSED: every recovered LUT computes the reference function "
             "(up to nextpnr input permutation)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
