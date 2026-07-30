#!/usr/bin/env python3.15t
"""Probe how a CCU2 slice's `.config` INIT relates to the reference INIT.

The round-trip check showed every LOGIC-mode LUT recovers correctly (exactly
or up to nextpnr input permutation), while every CCU2-mode LUT differs.  This
script exists to characterise that difference rather than guess at it: it
prints, per CCU2 site, the reference INIT, the bitstream INIT, the slice input
muxes, and the carry-related enums, so the encoding can be read off the data.

    python3.15t scripts/ecp5_ccu2_probe.py <ref-dir> [--limit N]

Logs to ./tmp/logs/ecp5_ccu2_probe.log as well as the terminal.
"""
import argparse
import collections
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain  # noqa: E402  (path set above)

DEF_DBROOT = toolchain.trellis_dbroot()
BEL_RE = re.compile(r"^X(\d+)/Y(\d+)/SLICE([A-D])\.K([01])$")


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref_dir")
    ap.add_argument("--device", default="LFE5U-12F")
    ap.add_argument("--dbroot", default=DEF_DBROOT)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    log = setup_logging("ecp5_ccu2_probe")
    from lifters.ecp5_lift import ECP5Lift

    lift = ECP5Lift(args.device, dbroot=args.dbroot)
    pc = lift.parse_config(os.path.join(args.ref_dir, "ref.config"))

    doc = json.load(open(os.path.join(args.ref_dir, "ref_placed.json")))
    mod = max(doc["modules"].values(), key=lambda m: len(m.get("cells", {})))

    rows = []
    for cname, cell in mod.get("cells", {}).items():
        if cell["type"] != "TRELLIS_COMB":
            continue
        m = BEL_RE.match(cell.get("attributes", {}).get("NEXTPNR_BEL", ""))
        if not m:
            continue
        params = cell.get("parameters", {})
        if params.get("MODE") != "CCU2":
            continue
        col, row, sl, k = (int(m.group(1)), int(m.group(2)),
                           m.group(3), m.group(4))
        rows.append({
            "site": (row, col, sl, k),
            "want": str(params.get("INITVAL", "")).strip(),
            "got": pc.lut_init.get((row, col, sl, k)),
            "inject": params.get("CCU2_INJECT1", "?"),
            "enums": dict(pc.slice_enum.get((row, col, sl), {})),
            "name": cname,
        })

    log.info("%d CCU2 LUT sites", len(rows))
    pairs = collections.Counter((r["want"], r["got"]) for r in rows)
    log.info("distinct (want, got) INIT pairs: %d", len(pairs))
    for (w, g), n in pairs.most_common(12):
        log.info("  want=%s got=%s  x%d", w, g, n)

    for r in sorted(rows, key=lambda x: x["site"])[:args.limit]:
        muxes = {k: v for k, v in r["enums"].items() if k.endswith("MUX")}
        log.info("%s want=%s got=%s inject=%s muxes=%s",
                 r["site"], r["want"], r["got"], r["inject"], muxes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
