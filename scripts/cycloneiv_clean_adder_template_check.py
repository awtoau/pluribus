#!/usr/bin/env python3.15t
"""#188 direct disambiguation check: does the template library contain a real adder-shaped template,
and if so does it match one of rtl.py's own already-confirmed-real DJI adder chains?

Reuses the committed tmp/image_sim_dji_push/nl.pkl (post F-021 + multi-LE-tail-strip).  Read-only on
rtl.py/emit.py; calls into rtl.Lift the same way scripts/cycloneiv_clean_rtl.py already does.

  python3.15t scripts/cycloneiv_clean_adder_template_check.py   # log tmp/logs/cycloneiv_clean_adder_template_check.log
"""
import json
import logging
import os
import pickle
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("adder_template_check")


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_adder_template_check.log"))])

    for path in ("reference/template_library.json", "reference/template_library_area.json"):
        lib = json.load(open(os.path.join(REPO, path)))
        adder_templates = [t for t in lib["templates"] if any(
            s["source"].startswith(("add_", "sub_")) for s in t["sources"])]
        log.info("%s: %d templates total, %d touched by an add_*/sub_* specimen, leaf counts %s",
                  path, len(lib["templates"]), len(adder_templates), sorted({t["n_leaves"] for t in adder_templates}))
        for t in adder_templates:
            srcs = sorted({s["source"] for s in t["sources"] if s["source"].startswith(("add_", "sub_"))})
            other_srcs = sorted({s["source"] for s in t["sources"] if not s["source"].startswith(("add_", "sub_"))})
            log.info("  tt=%s n_leaves=%d add/sub sources=%s ALSO MATCHED BY=%s", t["tt_hex"], t["n_leaves"], srcs, other_srcs)

    nl = pickle.load(open(os.path.join(REPO, "tmp", "image_sim_dji_push", "nl.pkl"), "rb"))
    from lifters.cycloneiv_clean import rtl, patterns as PT
    import cycloneiv_clean_template_match as TM
    L = rtl.Lift(nl)
    L.run()
    log.info("DJI image: %d confirmed adder/addc chains (self.adder_widths), widths=%s",
              len(L.adder_widths), sorted(set(L.adder_widths)))

    D = PT.Design(nl)
    # Pick chains whose width (len of luts, minus a free head if any) is 4 or 8 to match the library's add_w4/add_w8 specimens.
    candidates = []
    for ch in L.chain_list:
        if not ch.get("ok") or ch.get("sub"):
            continue
        n = len(ch["luts"]) - (1 if ch.get("free_head") else 0)
        if n in (4, 8):
            candidates.append((n, ch))
    log.info("DJI chains with width matching library's add_w4/add_w8 specimens: %d candidates (widths found: %s)",
             len(candidates), sorted({n for n, _ in candidates}))

    if not candidates:
        log.info("RESULT: no DJI adder chain at width 4 or 8 exists to test against the library's add_w4/add_w8 specimens -- "
                  "inconclusive by construction, not evidence either way.")
        print("RESULT: inconclusive, no width-4/8 DJI adder chain found")
        return 0

    n, ch = candidates[0]
    head_lut = ch["luts"][1 if ch.get("free_head") else 0]
    sig = head_lut["name"]
    try:
        if TM.cone_has_cycle(D, sig):
            log.info("RESULT: picked chain's head LE cone is cyclic, cannot compute truth table -- trying next candidate")
            for n, ch in candidates[1:]:
                head_lut = ch["luts"][1 if ch.get("free_head") else 0]
                sig = head_lut["name"]
                if not TM.cone_has_cycle(D, sig):
                    break
            else:
                print("RESULT: all width-4/8 candidates had cyclic cones, inconclusive")
                return 0
        leaves = sorted(D.support(sig))
        kinds = [D.kind(s) for s in leaves]
        all_pad = all(k == "pad" for k in kinds)
        log.info("Testing DJI chain width=%d head_le=%s leaves=%d kinds=%s all_pad=%s", n, sig, len(leaves), kinds, all_pad)
        if not all_pad:
            log.info("RESULT: this chain's head-LE cone leaves are NOT all pads (kinds=%s) -- this is exactly the stripper bug "
                      "the library build hit: only a chain's bit-0 LE (constant carry-in, pure a[0]^b[0] on pads) passes the "
                      "all-pad-leaf filter.  A real DJI adder's bit>0 LEs read the previous bit's carry (a 'co_*'/'lc_*' leaf, "
                      "not a pad), so the SAME filter that produced only a trivial 2-leaf template from the synthetic "
                      "add_w4/add_w8 specimens also means this real chain's non-trivial LEs were never even CANDIDATES for "
                      "stripping -- the comparison the library was built to make is not reachable with the current stripper "
                      "rule, for adders specifically, regardless of toolchain/settings.", kinds)
            print(json.dumps(dict(result="stripper_bug_confirmed", width=n, head_le=sig, leaf_kinds=kinds), indent=1))
            return 0
        tt = PT.cone_tt(D, sig, leaves)
        log.info("DJI chain head-LE truth table: tt=%x leaves=%d", tt, len(leaves))
        perm_set = TM.permutation_tts(tt, len(leaves))      # reuse the matcher's own tested permutation closure
        matched = []
        for path in ("reference/template_library.json", "reference/template_library_area.json"):
            lib = json.load(open(os.path.join(REPO, path)))
            for t in lib["templates"]:
                if t["n_leaves"] != len(leaves):
                    continue
                if int(t["tt_hex"], 16) in perm_set:
                    matched.append((path, t["tt_hex"], [s["source"] for s in t["sources"]]))
        log.info("RESULT: matched=%s", matched)
        print(json.dumps(dict(result="matched" if matched else "not_matched", width=n, head_le=sig,
                               leaf_kinds=kinds, matches=matched), indent=1))
    finally:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
