#!/usr/bin/env python3.15t
"""A/B verification of the Python perf pass (#145, docs/perf-pass.md): new path vs reference, bit-identical.

  python3.15t scripts/perf_pass_verify.py active [--rb N]     # Dec.active dense vs legacy, SparsePlane.has
  python3.15t scripts/perf_pass_verify.py prepare             # prepare() arrays vs the on-disk ones
  python3.15t scripts/perf_pass_verify.py decode [--corpus N] # decompress() / plane keys vs tests/ref_decode.py
Log tmp/logs/perf_pass_verify.log; results tmp/perf_pass_verify_<cmd>.json.  Any difference exits 1.
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
log = logging.getLogger("perf_pass_verify")
SRC = REPO / "sources" / "cycloneiv-corpus"
CORPUS = REPO / "corpus" / "cycloneiv"


def setup(cmd):
    os.makedirs(REPO / "tmp" / "logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "perf_pass_verify.log"),
                                  logging.StreamHandler()])


def cgx150_images(n_rb):
    out = [(p.parent.name + "/" + p.name, p) for p in sorted(SRC.glob("poseidon_*/*.rbf"))]
    out += [("neptuno_cgx150_mc2/mc2.rbf", SRC / "neptuno_cgx150_mc2" / "mc2.rbf")]
    out += [(f"gx150_rb_{i:03d}", CORPUS / f"gx150_rb_{i:03d}" / "bitstream.rbf") for i in range(0, 150, max(1, 150 // max(n_rb, 1)))][:n_rb]
    return out


def cmd_active(a):
    import cycloneiv_asm_decode as ad
    import cycloneiv_corpus as cc
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of("EP4CGX150"))
    dec = ad.Dec()
    res, bad = [], 0
    rng = np.random.default_rng(0)
    for name, path in cgx150_images(a.rb):
        plane = cc.cram_plane(path.read_bytes(), g)
        t = time.perf_counter(); old = dec.active(plane, method="legacy"); t_old = time.perf_counter() - t
        plane.__dict__.pop("_dense", None)
        dec.__dict__.pop("_flat_cache", None)
        t = time.perf_counter(); new = dec.active(plane, method="dense"); t_cold = time.perf_counter() - t
        t = time.perf_counter(); dec.active(plane, method="dense"); t_warm = time.perf_counter() - t
        same = all(np.array_equal(x, y) and x.dtype == y.dtype for x, y in zip(old, new))
        nf, nv = plane.shape
        f = rng.integers(-5, nf + 5, 300000)
        v = rng.integers(-5, nv + 5, 300000)
        f[:1000] = rng.choice(plane.keys // nv, 1000)
        v[:1000] = rng.choice(plane.keys % nv, 1000)
        for dt in (np.int32, np.int64):
            fd, vd = f.astype(dt), v.astype(dt)
            h_old = plane._has_searchsorted(fd, vd)
            cc.HAS_MODE = "dense"
            h_new = plane.has(fd, vd)
            cc.HAS_MODE = "auto"
            same &= bool(np.array_equal(h_old, h_new))
        bad += not same
        r = dict(image=name, groups=len(old[0]), identical=same, legacy_s=round(t_old, 3),
                 dense_cold_s=round(t_cold, 3), dense_warm_s=round(t_warm, 3))
        res.append(r)
        log.info("%s", r)
    json.dump(res, open(REPO / "tmp" / "perf_pass_verify_active.json", "w"), indent=1)
    log.info("active: %d images, %d differ", len(res), bad)
    return bad


def cmd_prepare(a):
    import cycloneiv_asm_decode as ad
    ref = {n: np.load(f"{ad.DEC}_{n}.npy", mmap_mode="r") for n in
           ("pf", "pv", "pred", "gid", "grec", "gstart", "gsize", "block", "b0", "e_ukey", "ukey_block")}
    out = REPO / "tmp" / "perf_prepare"
    out.mkdir(parents=True, exist_ok=True)
    ad.DEC = str(out / "dec")
    t = time.perf_counter()
    ad.prepare()
    log.info("prepare wall %.1f s", time.perf_counter() - t)
    bad = 0
    for n, r in ref.items():
        new = np.load(f"{ad.DEC}_{n}.npy", mmap_mode="r")
        same = new.dtype == r.dtype and new.shape == r.shape and np.array_equal(new, r)
        bad += not same
        log.info("%-12s %s", n, "identical" if same else "DIFFERENT")
    return bad


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("active"); p.add_argument("--rb", type=int, default=4)
    sp.add_parser("prepare")
    p = sp.add_parser("decode"); p.add_argument("--corpus", type=int, default=200)
    a = ap.parse_args()
    setup(a.cmd)
    if a.cmd == "decode":
        import perf_pass_decode
        bad = perf_pass_decode.run(a, log)
    else:
        bad = {"active": cmd_active, "prepare": cmd_prepare}[a.cmd](a)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
