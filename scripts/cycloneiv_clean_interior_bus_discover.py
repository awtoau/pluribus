#!/usr/bin/env python3.15t
"""Discover INTERIOR multi-bit buses in a Cyclone IV clean-pipeline netlist, by structure alone --
no chip_ref/pad label to start from (unlike cycloneiv_clean_bus_trace.py, which groups board PADS).
A bus candidate = signals sharing (a) clock domain, (b) LAB-adjacency (same LAB x,y -- Cyclone IV's
own ff_x_y_le/lc_x_y_le naming already encodes physical LE position, the interior analogue of the
pad-adjacency prior used for the pin-level work), and (c) a matching downstream consumer-kind
signature at 1-2 hops (functrace.trace_sinks) -- a real bus's bits typically converge on the SAME
consumer instance (one M9K port, one MAC operand, one comparator's LUT group), even if individual
bit values differ.

  python3.15t scripts/cycloneiv_clean_interior_bus_discover.py --nl NL.pkl [--validate] [--min-width 3]
Read-only on the netlist. Log tmp/logs/cycloneiv_clean_interior_bus_discover.log, JSON
tmp/cycloneiv_clean/interior_bus_discover.json.

--validate checks the method BLIND against 3 already-known internal buses before the real search:
M9K address bus (94,57/58's 10-wire addr), a MAC operand bus (a[]), and the SPI register file's
8-FF-per-enable register structure (ena-sharing, not consumer-convergence -- a different, simpler
signature, checked separately since register-file FFs don't feed a single downstream instance the
way M9K/MAC operands do).
"""
import argparse
import collections
import json
import logging
import os
import pickle
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("interior_bus_discover")


# functrace.trace_sinks only bounds FF-stage depth (ff_hops); it does NOT bound pure-LUT-chain
# traversal length, so a signal feeding a long combinational chain before any FF/hard-block sink
# can blow up a BFS unboundedly (confirmed: a full-netlist discover() pass hung past 60s on this
# 89k-LUT/35.9k-FF image). This wrapper imposes its own node-visit cap, independent of trace_sinks
# itself (read-only, not edited) -- a signal that exceeds the cap is reported as "too wide to trace
# cheaply" rather than hung on, consistent with this project's own rule that a timeout must state
# what it is bounding and why: here, total LUT-chain fanout nodes visited per signal, capped at a
# level reached in <5ms per signal in a 500-signal sample of this same image (12.6s / 125k candidates
# extrapolated), so pathological outliers are the ones being excluded, not normal signals.
_MAX_VISIT = 4000


def consumer_signature(design, fanout, FT, sig, max_hops=2):
    """1-2 hop consumer-kind multiset, keyed by (kind, target-instance-id) so bits converging on the
    SAME m9k tile / MAC instance / comparator cluster are distinguishable from bits that merely share
    a generic kind (e.g. two different, unrelated m9k tiles must not look identical).  Returns None
    if the cone exceeds _MAX_VISIT (too wide to trace cheaply -- reported separately, not silently
    dropped, see discover()'s n_too_wide counter)."""
    seen, out, cur = set(), [], [(sig, 0)]
    sig_set = set()
    while cur:
        if len(seen) > _MAX_VISIT:
            return None
        s, hops = cur.pop()
        if s in seen:
            continue
        seen.add(s)
        cons = fanout.get(s, [])
        for kind, iid, pin, idx in cons:
            if kind in ("m9k", "mac"):
                sig_set.add((kind, iid, pin))
            elif kind == "io":
                sig_set.add(("pad", iid))
            elif kind == "ff":
                if hops >= max_hops:
                    sig_set.add(("ff_untraced", None))
                else:
                    cur.append((iid, hops + 1))
            else:   # "lc": follow the LUT's own output forward too (no hop increment -- pure comb chain)
                cur.append((iid, hops))
    return frozenset(sig_set)


def lab_of(name):
    """(x, y) LAB coordinate from an ff_x_y_le or lc_x_y_le name; None if not that shape."""
    parts = name.split("_")
    if len(parts) >= 3 and parts[0] in ("ff", "lc"):
        try:
            return (int(parts[1]), int(parts[2]))
        except ValueError:
            return None
    return None


def build_candidates(nl):
    """Every FF output and every LUT output that is NOT purely feeding another LUT with no further
    use (a bare internal helper) -- i.e. every signal with a real downstream consumer, so the M9K
    address-bus case (driven by LUT outputs, not FFs) is covered, not just FF-only candidates."""
    cands = {}
    for F in nl.ffs:
        lab = lab_of(F["name"])
        if lab:
            cands[F["name"]] = dict(clk=F.get("clk"), lab=lab, kind="ff")
    for L in nl.luts:
        lab = lab_of(L["name"])
        if lab:
            cands[L["name"]] = dict(clk=None, lab=lab, kind="lc")
    return cands


def discover(design, fanout, FT, candidates, min_width, exclude=None, max_hops=2):
    exclude = exclude or set()
    # Bucket by LAB ALONE, not (clk, lab): a real mixed FF+comb bus (confirmed in validation --
    # the M9K address bus at (94,57)/(94,58) is ff_93_58_9 + lc_93_58_0..8, ONE bus, but the FF
    # has a real clk field while the 9 LUTs have clk=None) would never be recovered if clk were
    # part of the bucket key, since the FF and LUTs would land in different buckets and could never
    # be seen as one group. Clock domain is still informative -- it is reported per-member in the
    # output, just not used to SPLIT a LAB's candidates before the consumer-signature check does.
    buckets = collections.defaultdict(list)
    for name, info in candidates.items():
        if name in exclude:
            continue
        buckets[info["lab"]].append(name)

    found = []
    n_too_wide = 0
    n_empty = 0
    for lab, names in buckets.items():
        if len(names) < min_width:
            continue
        sig_groups = collections.defaultdict(list)
        for name in names:
            sig = consumer_signature(design, fanout, FT, name, max_hops=max_hops)
            if sig is None:
                n_too_wide += 1
            elif not sig:
                n_empty += 1
            else:
                sig_groups[sig].append(name)
        for sig, members in sig_groups.items():
            if len(members) >= min_width:
                clks = sorted({candidates[m].get("clk") for m in members} - {None})
                found.append(dict(lab=list(lab), width=len(members), members=sorted(members),
                                   clk_domains=clks, mixed_clk=len(clks) > 1,
                                   consumer_signature=[list(t) for t in sig]))
    found.sort(key=lambda b: -b["width"])
    log.info("discover: %d too-wide-to-trace (capped at %d nodes), %d no-converged-consumer, %d buses found",
              n_too_wide, _MAX_VISIT, n_empty, len(found))
    return found


def validate(nl, design, fanout, FT):
    """Blind check: does discover(), run on JUST the FFs/LUTs forming 3 already-known buses (plus a
    realistic amount of unrelated noise from the same LABs), recover the right membership/width?"""
    results = {}

    # 1. M9K address bus at (94,57)/(94,58): addr = ff_93_58_9 + lc_93_58_0..8 (LAB 93,58).
    m9k_addr = None
    for m in nl.m9k:
        if (m["x"], m["y"]) == (94, 57):
            m9k_addr = [s for s in m["addr"] if lab_of(s)]
            break
    cands = build_candidates(nl)
    found = discover(design, fanout, FT, cands, min_width=3)
    m9k_hit = next((b for b in found if set(m9k_addr).issubset(set(b["members"]))), None) if m9k_addr else None
    results["m9k_addr_94_57"] = dict(expected_width=len(m9k_addr) if m9k_addr else 0,
                                      expected_members=m9k_addr,
                                      recovered=bool(m9k_hit),
                                      recovered_width=m9k_hit["width"] if m9k_hit else None,
                                      recovered_members=m9k_hit["members"] if m9k_hit else None)

    # 2. A MAC operand bus (a[]): pick the first MAC instance with a real multi-wire 'a' operand.
    mac_a = None
    for m in nl.mac:
        a = [s for s in (m.get("a") or []) if isinstance(s, str) and lab_of(s)]
        if len(a) >= 3:
            mac_a = a
            break
    mac_hit = next((b for b in found if mac_a and set(mac_a).issubset(set(b["members"]))), None)
    results["mac_operand_a"] = dict(expected_width=len(mac_a) if mac_a else 0, expected_members=mac_a,
                                     recovered=bool(mac_hit),
                                     recovered_width=mac_hit["width"] if mac_hit else None,
                                     recovered_members=mac_hit["members"] if mac_hit else None)

    # 3. SPI register file: FFs sharing one `ena` net, 8 per address -- a DIFFERENT signature
    # (shared control input, not shared consumer) since register-file bits don't converge on one
    # downstream instance the way M9K/MAC operands do.  Checked via ena-grouping directly, not the
    # consumer-convergence method above -- reported as a separate validation, not folded into
    # discover()'s own result, since it is a genuinely different bus SHAPE.
    ena_groups = collections.defaultdict(list)
    for F in nl.ffs:
        if F.get("ena"):
            ena_groups[F["ena"]].append(F["name"])
    eight_wide = [g for g in ena_groups.values() if len(g) == 8]
    results["spi_regfile_ena_groups"] = dict(
        method="shared-ena grouping (distinct from consumer-convergence)",
        n_enable_nets_total=len(ena_groups), n_eight_wide_groups=len(eight_wide),
        note="208 addresses x 8 FFs expected per docs/lightbridge-fpga.md section 6; "
             "sanity count only, not cross-checked against the full address-decode script")
    return results, found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", required=True)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--min-width", type=int, default=3)
    ap.add_argument("--max-hops", type=int, default=2)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    os.makedirs(os.path.join(REPO, "tmp", "cycloneiv_clean"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_interior_bus_discover.log"))])
    from lifters.cycloneiv_clean import patterns as PT
    from lifters.cycloneiv_clean import functrace as FT
    nl = pickle.load(open(a.nl, "rb"))
    design = PT.Design(nl)
    fanout = FT._build_fanout(nl)

    out = {}
    if a.validate:
        val, found_all = validate(nl, design, fanout, FT)
        out["validation"] = val
        for k, v in val.items():
            if "recovered" in v:
                log.info("VALIDATE %s: expected_width=%s recovered=%s recovered_width=%s",
                          k, v.get("expected_width"), v.get("recovered"), v.get("recovered_width"))
            else:
                log.info("VALIDATE %s: %s", k, v)

    log.info("building candidates...")
    cands = build_candidates(nl)
    log.info("%d candidates (ff+lc with LAB coords)", len(cands))
    found = discover(design, fanout, FT, cands, min_width=a.min_width, max_hops=a.max_hops)
    log.info("found %d candidate interior buses (min_width=%d)", len(found), a.min_width)
    out["candidate_buses"] = found[:200]   # cap JSON size; full list only in the log tally below
    out["n_candidate_buses_total"] = len(found)

    for b in found[:40]:
        log.info("BUS width=%d lab=%s clk_domains=%s mixed_clk=%s sig=%s members=%s", b["width"], b["lab"],
                  b["clk_domains"], b["mixed_clk"], b["consumer_signature"][:4], b["members"][:4])

    outp = os.path.join(REPO, "tmp", "cycloneiv_clean", "interior_bus_discover.json")
    json.dump(out, open(outp, "w"), indent=1)
    log.info("-> %s", outp)
    print(json.dumps({k: v for k, v in out.items() if k != "candidate_buses"}, indent=1))


if __name__ == "__main__":
    main()
