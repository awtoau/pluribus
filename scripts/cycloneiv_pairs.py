#!/usr/bin/env python3.15t
"""Plain + compressed quartus_cpf .rbf pairs for every Cyclone III / IV vendor .sof in the
Quartus install (sfl_, sfl_enhanced_, pfl_*).  No device support package needed (cpf only).
Vendor files are third-party binaries: they stay under tmp/, never committed.

  python3.15t scripts/cycloneiv_pairs.py [--glob '*ep4cgx*']
Out: tmp/cycloneiv/pairs/<stem>.rbf, <stem>.c.rbf; log: tmp/logs/cycloneiv_pairs.log
"""
import argparse
import fnmatch
import logging
import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

# quartus_cpf on a vendor .sof: 0.3-2.6 s each (tmp/logs/fpga_family_probe.log, 2026-10-24);
# stall-style backstop for a host tool: 3x a cold worst case of ~20 s.
LIMIT_S = 60
MIN_GB = 3
OUT = REPO / "tmp" / "cycloneiv" / "pairs"
FAMILY_GLOBS = ("*_ep3c*.sof", "*_ep4ce*.sof", "*_ep4cgx*.sof")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="*")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_pairs.log")])
    log = logging.getLogger("pairs")
    qb = pathlib.Path(str(toolchain.quartus_bin()))
    src = qb.parent / "common" / "devinfo" / "programmer"
    sofs = sorted(p for p in src.iterdir()
                  if any(fnmatch.fnmatch(p.name, g) for g in FAMILY_GLOBS)
                  and fnmatch.fnmatch(p.name, a.glob))
    log.info("%d .sof files", len(sofs))
    bad = 0
    with heavy_guard.heavy_lock("cycloneiv_pairs", log):
        for sof in sofs:
            stem = sof.stem
            todo = [(sfx, extra) for sfx, extra in
                    ((".rbf", ["-o", "bitstream_compression=off"]),
                     (".c.rbf", ["-o", "bitstream_compression=on"]))
                    if not (OUT / (stem + sfx)).exists()]
            if not todo:
                continue
            shutil.copyfile(sof, OUT / sof.name)
            for sfx, extra in todo:
                heavy_guard.wait_available(log, f"quartus_cpf {stem}", MIN_GB)
                try:
                    r = subprocess.run([str(qb / "quartus_cpf"), "-c", *extra, sof.name, stem + sfx],
                                       cwd=OUT, capture_output=True, text=True, timeout=LIMIT_S)
                except subprocess.TimeoutExpired:
                    log.error("%s%s: quartus_cpf exceeded %ds", stem, sfx, LIMIT_S)
                    bad += 1
                    continue
                if r.returncode:
                    bad += 1
                    log.error("%s%s: rc=%d %s", stem, sfx, r.returncode,
                              (r.stdout + r.stderr)[-300:].replace("\n", " "))
            (OUT / sof.name).unlink()
            log.info("%s done", stem)
    log.info("finished, %d failures", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
