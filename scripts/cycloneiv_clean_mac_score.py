#!/usr/bin/env python3.15t
"""Score the MAC designs only (subset of the fast gate; same score_design).  Log: tmp/logs/cycloneiv_clean_mac_score.log

  python3.15t scripts/cycloneiv_clean_mac_score.py [design ...]     # default: the 5 gxhb_mac_* fast-tier designs
"""
import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
spec = importlib.util.spec_from_file_location("gate", os.path.join(REPO, "scripts", "cycloneiv_clean_gate.py"))
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
DEF = ["gxhb_mac_dyn_signa", "gxhb_mac_in_b_reg", "gxhb_mac_null_seed", "gxhb_mac_signed_b", "gxhb_mac_two_mult_w9"]


def main():
    names = sys.argv[1:] or DEF
    cx = G.Ctx()
    out = []
    for n in names:
        r = G.score_design(cx, os.path.join(REPO, "corpus", "cycloneiv", n), 2)
        print(n, {k: dict(r[k]) for k in ("pips", "nets", "lut_init", "register_clock", "pins")}, "unres", r["gt_unresolved"])
        print("  scope", json.dumps({k: v for k, v in r["pips_scope"].items() if v}, indent=0)[:1500])
        out.append(r)
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    json.dump(out, open(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_mac_score.json"), "w"), indent=1, default=str)


main()
