#!/usr/bin/env python3.15t
"""Make quartus_cpf .rbf (plain + compressed) for every vendor SFL .sof, to fingerprint an unknown
Altera/Intel bitstream by header, length and frame structure.  Vendor files stay under tmp/.

  python3.15t scripts/fpga_family_probe.py [--glob 'sfl_ep*.sof']
Out: tmp/fpga_family/rbf/<stem>.rbf, <stem>.c.rbf; log: tmp/logs/fpga_family_probe.log
"""
import argparse
import logging
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

# quartus_cpf on a small SFL .sof: ~1-2 s (corpus note: < 2 min cold worst case); 120 s backstop
LIMIT_S = 120
MIN_GB = 3
OUT = os.path.join(REPO, "tmp", "fpga_family", "rbf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="sfl_ep*.sof")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "fpga_family_probe.log"))])
    log = logging.getLogger("probe")
    qb = toolchain.quartus_bin()
    import pathlib
    src = pathlib.Path(str(qb)).parent / "common" / "devinfo" / "programmer"
    for sof in sorted(src.glob(a.glob)):
        stem = sof.stem
        shutil.copyfile(sof, os.path.join(OUT, sof.name))
        for suffix, extra in ((".rbf", []), (".c.rbf", ["-o", "bitstream_compression=on"])):
            dst = stem + suffix
            if os.path.exists(os.path.join(OUT, dst)):
                continue
            heavy_guard.wait_available(log, f"quartus_cpf {stem}", MIN_GB)
            try:
                r = subprocess.run([os.path.join(str(qb), "quartus_cpf"), "-c", *extra, sof.name, dst],
                                   cwd=OUT, capture_output=True, text=True, timeout=LIMIT_S)
            except subprocess.TimeoutExpired:
                log.error("%s: quartus_cpf exceeded %ds", dst, LIMIT_S)
                continue
            if r.returncode:
                log.error("%s: rc=%d %s", dst, r.returncode, (r.stdout + r.stderr)[-200:].replace("\n", " "))
        os.remove(os.path.join(OUT, sof.name))
        log.info("%s done", stem)


if __name__ == "__main__":
    main()
