#!/usr/bin/env python3
"""Make (uncompressed, compressed) .rbf oracle pairs for every Cyclone V corpus design.

Per design (corpus keeps no .sof): copy quartus/ to tmp/cvcomp/<name>, quartus_asm -> build.sof,
quartus_cpf twice (compression off / on, nothing else differs), check the uncompressed one is
byte-identical to the corpus bitstream.rbf, keep the compressed one as
corpus/cyclonev/<name>/bitstream.compressed.rbf (gitignored with the rest of the corpus).
No map/fit.  One design at a time, gated on free RAM (asm peak ~0.7 GB, cpf ~0.3 GB).

Usage: python3.15t scripts/cyclonev_compressed_pairs.py [--corpus DIR] [--only a b] [--force]
Log: tmp/logs/cyclonev_compressed_pairs.log
"""
import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

LOG = REPO / "tmp" / "logs" / "cyclonev_compressed_pairs.log"
WORK = REPO / "tmp" / "cvcomp"
OUT_NAME = "bitstream.compressed.rbf"
# Overall limit per tool: corpus build measured asm/cpf < 2 min cold; 3x backstop (agent-rules).
LIMIT_S = {"asm": 360, "cpf": 120}
MIN_GB = 3  # asm peak 0.7 GB (quartus_asm.log "Peak virtual memory"); 4x margin vs other load
log = logging.getLogger("cyclonev_compressed_pairs")


def run(step, cmd, cwd):
    with open(cwd / f"{step}.log", "w") as fh:
        r = subprocess.run([str(c) for c in cmd], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                           timeout=LIMIT_S[step.split("_")[0]])
    if r.returncode:
        log.error("%s failed rc=%d (%s)", step, r.returncode, cwd / f"{step}.log")
    return r.returncode == 0


def one(ddir, qb):
    name = ddir.name
    work = WORK / name
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(ddir / "quartus", work,
                    ignore=shutil.ignore_patterns("*.rbf", "*.sof", "simulation"))
    ok = (run("asm", [qb / "quartus_asm", "build"], work)
          and run("cpf_off", [qb / "quartus_cpf", "-c", "build.sof", "u.rbf"], work)
          and run("cpf_on", [qb / "quartus_cpf", "-c", "-o", "bitstream_compression=on",
                             "build.sof", "c.rbf"], work))
    if not ok:
        return "tool failure (work dir kept)"
    ref = (ddir / "bitstream.rbf").read_bytes()
    u = (work / "u.rbf").read_bytes()
    if u != ref:
        return f"asm re-run uncompressed differs from corpus bitstream.rbf ({len(u)} vs {len(ref)})"
    shutil.copyfile(work / "c.rbf", ddir / OUT_NAME)
    c = (ddir / OUT_NAME).stat().st_size
    shutil.rmtree(work)
    log.info("%s ok: %d -> %d bytes (%.1f%%)", name, len(u), c, 100 * c / len(u))
    return None


def sfl_pairs(qb):
    """Multi-die pairs without a fit: Quartus ships a Serial Flash Loader .sof per Cyclone V die
    (IDCODE 02bX/02dX in the name).  Vendor files -> tmp/ only, never committed."""
    src = qb.parent / "common" / "devinfo" / "programmer"
    out = WORK / "sfl"
    out.mkdir(parents=True, exist_ok=True)
    fails = 0
    for sof in sorted(src.glob("sfl_enhanced_0*_02[bd]*.sof")):
        stem = sof.stem.removeprefix("sfl_enhanced_")
        shutil.copyfile(sof, out / sof.name)
        ok = (run(f"cpf_off_{stem}", [qb / "quartus_cpf", "-c", sof.name, f"{stem}.rbf"], out)
              and run(f"cpf_on_{stem}", [qb / "quartus_cpf", "-c", "-o", "bitstream_compression=on",
                                         sof.name, f"{stem}.compressed.rbf"], out))
        (out / sof.name).unlink()
        fails += not ok
        log.info("sfl %s %s", stem, "ok" if ok else "FAILED")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(REPO / "corpus" / "cyclonev"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--sfl", action="store_true", help="pairs from Quartus' per-die SFL .sof files")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)])
    qb = Path(toolchain.quartus_bin())
    if a.sfl:
        return sfl_pairs(qb)
    dirs = sorted(d for d in Path(a.corpus).iterdir()
                  if (d / "quartus").is_dir() and (d / "bitstream.rbf").is_file())
    if a.only:
        dirs = [d for d in dirs if d.name in a.only]
    fails = {}
    for i, d in enumerate(dirs):
        if (d / OUT_NAME).exists() and not a.force:
            continue
        heavy_guard.wait_available(log, f"{d.name}", min_gb=MIN_GB)
        log.info("[%d/%d] %s", i + 1, len(dirs), d.name)
        err = one(d, qb)
        if err:
            fails[d.name] = err
            log.error("%s: %s", d.name, err)
    have = sum((d / OUT_NAME).exists() for d in dirs)
    log.info("pairs present %d/%d, failed this run %d", have, len(dirs), len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
