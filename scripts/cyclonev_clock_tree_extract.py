#!/usr/bin/env python3.15t
"""Extract the Cyclone V clock-tree data the lifter needs from Project Mistral.

Usage: cyclonev_clock_tree_extract.py [die=e50f|gt150f]  (default e50f)
Writes lifters/data/cyclonev_<die>_clocks.json:
  sclk  : SCLK node -> [[slot, source node], ...]       (data/<die>-r.txt.xz, SCLK rows)
  cmux  : "xxx.yyy" -> {gclk, rclk, clkpin, nclkpin, pllg, pllr, clking, clkinr} lists (data/<die>-cmux.txt)
  link  : HG/VG/CR/HR/VR -> [instance][INPUT_SEL value] -> [kind, n]   (libmistral/cyclonev.cc)
Mistral is the bootstrap source only (docs/bluebird.md); rows are checked against the Quartus RCF
by scripts/cyclonev_postfit_compare.py (ff.clk).  Mistral checkout: $MISTRAL_DIR or /mnt/2tb/git/mistral.
Log: tmp/logs/cyclonev_clock_tree_extract.log
"""
import json
import lzma
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIES = {"e50f": "5CEBA4U19C8", "gt150f": "5CEBA7U19C8"}
DIE = sys.argv[1] if len(sys.argv) > 1 else "e50f"
OUT = REPO / "lifters" / "data" / f"cyclonev_{DIE}_clocks.json"
LOG = REPO / "tmp" / "logs" / "cyclonev_clock_tree_extract.log"
MISTRAL = Path(os.environ.get("MISTRAL_DIR", "/mnt/2tb/git/mistral"))
CMUX_KEYS = ("gclk", "rclk", "clkpin", "nclkpin", "pllg", "pllr", "clking", "clkinr")


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


def sclk_rows():
    out = {}
    with lzma.open(MISTRAL / "data" / f"{DIE}-r.txt.xz", "rt") as fh:
        for ln in fh:
            if not ln.startswith("SCLK."):
                continue
            f = ln.split()
            out[f[0]] = [[int(s.split(":", 1)[0]), s.split(":", 1)[1]] for s in f[2:]]
    return out


def cmux_rows():
    out, cur = {}, None
    for ln in (MISTRAL / "data" / f"{DIE}-cmux.txt").read_text().splitlines():
        if ln.startswith("CMUX "):
            cur = out.setdefault(ln.split()[1], {})
        elif cur is not None and ln.strip():
            f = ln.split()
            if f[0] in CMUX_KEYS:
                cur[f[0]] = [None if t == "-" else t for t in f[1:]]
    return out


def link_tables():
    txt = (MISTRAL / "libmistral" / "cyclonev.cc").read_text()
    out = {}
    for name in ("hg", "vg", "cr", "hr", "vr"):
        m = re.search(rf"cmux{name}_link_table\[\d+\]\[\d+\] = \{{(.*?)\n\}};", txt, re.S)
        rows = [[[k, int(n)] for k, n in re.findall(r"\{ CMUX_(\w+), (\d+) \}", ln)]
                for ln in m.group(1).splitlines() if ln.strip().startswith("{{")]
        out[name.upper()] = rows
    return out


def main():
    rev = subprocess.run(["git", "-C", str(MISTRAL), "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    data = dict(source=f"mistral {rev}", device=DIES[DIE], sclk=sclk_rows(), cmux=cmux_rows(),
                link=link_tables())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    log(f"wrote {OUT} ({OUT.stat().st_size} bytes): {len(data['sclk'])} SCLK, {len(data['cmux'])} CMUX, "
        f"link rows { {k: len(v) for k, v in data['link'].items()} }")


if __name__ == "__main__":
    sys.exit(main())
