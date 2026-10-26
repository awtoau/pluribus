#!/usr/bin/env python3.15t
"""Find a Cyclone IV die's legal LAB sites by probing the fitter.

A shift register gets one register per candidate LAB_X<x>_Y<y> location assignment; quartus_fit
names every illegal one (error 171016).  Legal = candidates not named.  Chunks of CHUNK candidates,
built in tmp/cycloneiv/grid_work/ (no corpus writes).  Output lifters/data/cycloneiv_<die>_labs.json.

  python3.15t scripts/cycloneiv_device_grid.py --device EP4CGX150DF31C7 --xmax 120 --ymax 95
Log tmp/logs/cycloneiv_device_grid.log
"""
import argparse
import json
import logging
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_fuzz as fz  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import toolchain  # noqa: E402

log = logging.getLogger("cycloneiv_device_grid")
CHUNK = 2000
# map / fit of a 2000-register shift register on EP4CGX150, fit stopping at the location check:
# first-run backstop, cut to 3x measured once logged.
LIMITS = {"quartus_map": 300, "quartus_fit": 600}


def probe(dev, cands, work):
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    n = len(cands)
    v = ("module top(input clk, input d, output q);\n"
         f"  reg [{n - 1}:0] s;\n  always @(posedge clk) s <= {{s[{n - 2}:0], d}};\n"
         f"  assign q = s[{n - 1}];\nendmodule\n")
    (work / "top.v").write_text(v)
    qsf = [f'set_global_assignment -name FAMILY "{fz.family_of(dev)}"', f"set_global_assignment -name DEVICE {dev}",
           "set_global_assignment -name TOP_LEVEL_ENTITY top", "set_global_assignment -name VERILOG_FILE top.v",
           'set_global_assignment -name FITTER_EFFORT "FAST FIT"',
           'set_global_assignment -name AUTO_SHIFT_REGISTER_RECOGNITION OFF']
    qsf += [f"set_location_assignment LAB_X{x}_Y{y} -to s[{i}]" for i, (x, y) in enumerate(cands)]
    (work / "build.qsf").write_text("\n".join(qsf) + "\n")
    (work / "build.qpf").write_text('PROJECT_REVISION = "build"\n')
    qb = Path(toolchain.quartus_bin())
    if not fz.run("quartus_map", [qb / "quartus_map", "build"], work, work / "logs", LIMITS):
        raise SystemExit("quartus_map failed")
    fz.run("quartus_fit", [qb / "quartus_fit", "build"], work, work / "logs", LIMITS)
    txt = (work / "logs" / "quartus_fit.log").read_text(errors="replace")
    bad = {(int(x), int(y)) for x, y in re.findall(r"illegal location assignment LAB_X(\d+)_Y(\d+)", txt)}
    if not bad and "Error" in txt and "Fitter was successful" not in txt:
        raise SystemExit("fit failed without naming locations; see " + str(work / "logs" / "quartus_fit.log"))
    return [c for c in cands if c not in bad]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", required=True)
    ap.add_argument("--xmax", type=int, required=True)
    ap.add_argument("--ymax", type=int, required=True)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_device_grid.log", "w"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    fz.log.addHandler(logging.StreamHandler())
    fz.log.setLevel(logging.INFO)
    die = cg.die_of(a.device)
    cands = [(x, y) for x in range(a.xmax + 1) for y in range(a.ymax + 1)]
    legal = []
    for i in range(0, len(cands), CHUNK):
        ch = cands[i:i + CHUNK]
        ok = probe(a.device, ch, REPO / "tmp" / "cycloneiv" / "grid_work" / die)
        legal += ok
        log.info("chunk %d: %d candidates, %d legal", i // CHUNK, len(ch), len(ok))
    xs = sorted({x for x, _ in legal})
    ys = sorted({y for _, y in legal})
    log.info("%s: %d legal LABs, X %s, Y %d..%d", die, len(legal), xs, ys[0], ys[-1])
    out = REPO / "lifters" / "data" / f"cycloneiv_{die}_labs.json"
    out.write_text(json.dumps({"device": a.device, "labs": legal}) + "\n")
    log.info("wrote %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
