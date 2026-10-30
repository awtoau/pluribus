#!/usr/bin/env python3.15t
"""PLL / clock subset of the clean gate (#165, #175): score_design on the gxhb_pll* builds, per-design scope of pips / nets / register_clock.

  python3.15t scripts/cycloneiv_clean_pll_gate.py [design ...]      default: every corpus/cycloneiv/gxhb_pll* with the four ground-truth files
Log tmp/logs/cycloneiv_clean_pll_gate.log, json tmp/cycloneiv_clean/pll_gate.json.  Same scoring code as cycloneiv_clean_gate.py (imported).
"""
import glob
import json
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_gate as G  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_pll_gate.log")


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    log = logging.getLogger("pll_gate")
    ds = [os.path.join(REPO, "corpus", "cycloneiv", n) for n in sys.argv[1:]] or sorted(glob.glob(os.path.join(REPO, "corpus", "cycloneiv", "gxhb_pll*")))
    ds = [d for d in ds if all(os.path.exists(os.path.join(d, f)) for f in G.FILES)]
    import heavy_guard
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    res = {}
    with heavy_guard.lease(gb, "cyc4_clean_pll_gate", log):
        cx = G.Ctx()
        for d in ds:
            r = G.score_design(cx, d, 2)
            n = os.path.basename(d)
            res[n] = {k: r[k] for k in ("gt_edges", "gt_unresolved", "unresolved", "pips", "nets", "register_clock", "pips_scope") if k in r}
            log.info("%s pips %s nets %s clk %s unresolved %s", n, r.get("pips"), r.get("nets"), r.get("register_clock"), r["unresolved"])
            for kind, c in r["pips_scope"].items():
                if c:
                    log.info("   %s: %s", kind, dict(sorted(c.items(), key=lambda kv: -kv[1])[:12]))
    json.dump(res, open(os.path.join(REPO, "tmp", "cycloneiv_clean", "pll_gate.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
