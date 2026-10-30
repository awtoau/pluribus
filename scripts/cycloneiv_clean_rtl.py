#!/usr/bin/env python3.15t
"""Structured RTL from a Cyclone IV GX (EP4CGX150) bitstream (lifters/cycloneiv_clean/rtl.py, #165).

  python3.15t scripts/cycloneiv_clean_rtl.py <bitstream.rbf> <out.v> [--summary out.json] [--flat flat.v]
  python3.15t scripts/cycloneiv_clean_rtl.py --image IMAGE <out.v> [--lint]     (compressed image: decompressed to tmp/, removed at exit)
--lint runs `verilator --lint-only` on the RTL (and on the flat emit when --flat is given).  Read-only on the input.
Log tmp/logs/cycloneiv_clean_rtl.log.
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("cycloneiv_clean_rtl")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_rtl.log")
PLANE = os.path.join(REPO, "tmp", "cycloneiv_clean", "rtl_image_plane.rbf")
LINT_LIMIT_S = 600          # stall backstop: verilator lint of a 100 k-line netlist (no measurement yet; logged on expiry)


def lint(path, tag):
    cmd = ["verilator", "--lint-only", "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-UNOPTFLAT", "-Wno-WIDTH", path, "--top-module", "cyc4_top"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=LINT_LIMIT_S)
    except subprocess.TimeoutExpired:
        log.error("lint %s exceeded %ds", tag, LINT_LIMIT_S)
        return dict(status="timeout")
    errs = [l for l in r.stderr.splitlines() if l.startswith("%Error")]
    warns = [l for l in r.stderr.splitlines() if l.startswith("%Warning")]
    log.info("lint %s: rc=%d errors=%d warnings=%d %s", tag, r.returncode, len(errs), len(warns), errs[:3])
    return dict(status="clean" if r.returncode == 0 and not errs else "errors", rc=r.returncode, errors=len(errs), warnings=len(warns), first=errs[:5])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("out")
    ap.add_argument("--image", action="store_true")
    ap.add_argument("--summary")
    ap.add_argument("--flat")
    ap.add_argument("--lint", action="store_true")
    ap.add_argument("--label")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    import heavy_guard
    from lifters.cycloneiv_clean import emit, rtl
    rbf, tmp = a.input, None
    if a.image:
        import cycloneiv_decompress as cd
        os.makedirs(os.path.dirname(PLANE), exist_ok=True)
        rbf = tmp = PLANE
        open(PLANE, "wb").write(cd.decompress(open(a.input, "rb").read(), {}))
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    t0 = time.time()
    try:
        with heavy_guard.lease(gb, "cyc4_clean_rtl", log):
            cx = emit.Ctx()
            nl = emit.Builder(cx, rbf, a.label or ("image" if a.image else None)).run()
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    flat = emit.verilog(nl)
    t1 = time.time()
    text, rep = rtl.lift(nl)
    rep["lift_seconds"], rep["flat_lines"] = round(time.time() - t1, 1), flat.count("\n")
    open(a.out, "w").write(text)
    if a.flat:
        open(a.flat, "w").write(flat)
    if a.lint:
        if a.flat:
            rep["lint_flat"] = lint(a.flat, "flat")
        rep["lint_rtl"] = lint(a.out, "rtl")
    log.info("%s", json.dumps(rep))
    if a.summary:
        json.dump(rep, open(a.summary, "w"), indent=1)


if __name__ == "__main__":
    main()
