#!/usr/bin/env python3
"""Pluribus rebuild script — Cynthion ECP5 (awtoau/awto-cynthion).

Run from anywhere; paths are resolved relative to the repo root.

  python3 fpga/pluribus_cynthion/rebuild.py selftest    # default — smallest bitstream
  python3 fpga/pluribus_cynthion/rebuild.py analyzer
  python3 fpga/pluribus_cynthion/rebuild.py facedancer

Requires: ecpunpack built at debris/tmp/prjtrellis/libtrellis/build/ecpunpack
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO       = Path(__file__).parent.parent.parent
PLURIBUS   = REPO / "fpga" / "pluribus"
HERE       = Path(__file__).parent
BITDIR     = Path("/home/dan/git/awtoau/awto-cynthion/cynthion/python/build")
ECPUNPACK  = REPO / "debris/tmp/prjtrellis/libtrellis/build/ecpunpack"
DBROOT     = REPO / "debris/tmp/prjtrellis/database"

BITSTREAMS = {
    "selftest":   ("selftest.bit",   "cynthion-selftest-V1"),
    "analyzer":   ("analyzer.bit",   "cynthion-analyzer-V1"),
    "facedancer": ("facedancer.bit", "cynthion-facedancer-V1"),
}

os.chdir(REPO)

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("target", nargs="?", default="selftest",
    choices=list(BITSTREAMS), help="Which bitstream to analyse")
ap.add_argument("--annotate-only", action="store_true",
    help="Skip bitstream decode and BFS — only re-import pin annotations and re-export")
args, extra = ap.parse_known_args()

bitfile, label = BITSTREAMS[args.target]
bitpath = BITDIR / bitfile
config_path = HERE / f"{args.target}.config"
out_dir = HERE / "out" / args.target

out_dir.mkdir(parents=True, exist_ok=True)

env = dict(os.environ)
env["TRELLIS_DBROOT"] = str(DBROOT)
env["PYTHONPATH"]     = str(REPO / "debris/tmp/prjtrellis/libtrellis/build")

# Unpack bitstream → .config if not present (or stale)
if not args.annotate_only and (
    not config_path.exists() or config_path.stat().st_mtime < bitpath.stat().st_mtime
):
    print(f"Unpacking {bitfile} → {config_path.name} ...")
    r = subprocess.run(
        [str(ECPUNPACK), "--db", str(DBROOT), str(bitpath), str(config_path)],
        env={"LD_LIBRARY_PATH": str(ECPUNPACK.parent), **os.environ},
    )
    if r.returncode != 0:
        sys.exit(r.returncode)

if args.annotate_only:
    cmd = [
        sys.executable, str(PLURIBUS / "build.py"), "annotate",
        "--label",   label,
        "--out-dir", str(out_dir),
    ]
else:
    cmd = [
        sys.executable, str(PLURIBUS / "build.py"), "build",
        "--label",   label,
        "--config",  str(config_path),
        "--out-dir", str(out_dir),
    ]

cmd += extra
r = subprocess.run(cmd, env=env)
sys.exit(r.returncode)
