#!/usr/bin/env python3.15t
"""PLL specimen pairs gxhb_pllmp_* (#175): enabled PLL path per build, and the value of every PLL_*_INPUT / PLL_FEEDBACK_SELECT group per build.

  python3.15t scripts/cycloneiv_clean_pll_ports.py     # log tmp/logs/cycloneiv_clean_pll_ports.log, json tmp/cycloneiv_clean/pll_ports.json
Value = pattern match of the group's CRAM cells (io_line.Line); -1 = no pattern equals the plane, -2 = ambiguous.
"""
import glob
import json
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_dirt as D  # noqa: E402
from lifters.cycloneiv_clean import asmdb_walk as W, io_line, pll, plane as P, tracer as T  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_pll_ports.log")
GROUPS = ("PLL_PFD_ENA_INPUT", "PLL_ARESET_INPUT", "PLL_CLOCK_SWITCH_INPUT", "PLL_SCAN_DATA_INPUT", "PLL_SCAN_CLOCK_INPUT", "PLL_PHASE_UP_DOWN_INPUT",
          "PLL_PHASE_CLK_INPUT", "PLL_CONFIG_UPDATE_INPUT", "PLL_SCAN_CLOCK_ENABLE_INPUT", "PLL_EXTCLK_ENABLE_INPUT", "PLL_FEEDBACK_SELECT")


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    log = logging.getLogger("pll_ports")
    w, allnames, tab = W.Walk(), D.enum_tables(), P.load_tables()
    nm = allnames["arch_group_type"]
    pm = pll.load(w, allnames)
    sites = pll.pll_tiles()
    lines = {}
    for g in GROUPS:
        for bt in (43, 45):
            lines[(g, bt)] = io_line.Line(w, nm, bt, g, -1, tab, n_inputs=None if g != "PLL_FEEDBACK_SELECT" else 8)
    names = sys.argv[1:] or [os.path.basename(d) for d in sorted(glob.glob(os.path.join(REPO, "corpus", "cycloneiv", "gxhb_pllmp_*")))]
    res = {}
    cff = pll.IO.Cff()
    for n in names:
        rbf = os.path.join(REPO, "corpus", "cycloneiv", n, "bitstream.rbf")
        if not os.path.exists(rbf):
            continue
        bits = T.plane_bits(rbf)
        c = cff.read(rbf)[0]
        used = [(k, bt, p) for k, bt, p in pm.used(c)]
        row = {"enabled_icd": [u[0] for u in used], "groups": {}}
        for k, bt, p in used:
            row["groups"][f"PLL_{k}"] = {}
            for g in GROUPS:
                ln = lines[(g, bt)]
                row["groups"][f"PLL_{k}"][g] = (ln.select(bits, p) if len(ln.cells[p]) else None, "".join(str(int(b)) for b in bits[ln.cells[p]]))
        res[n] = row
        log.info("%s enabled %s", n, row["enabled_icd"])
        for pk, gv in row["groups"].items():
            log.info("   %s %s", pk, {g: v for g, v in gv.items()})
    json.dump(res, open(os.path.join(REPO, "tmp", "cycloneiv_clean", "pll_ports.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
