#!/usr/bin/env python3.15t
"""Emit flat structural Verilog from a Cyclone IV GX (EP4CGX150) bitstream with the clean pipeline (lifters/cycloneiv_clean/emit.py, #165).

  python3.15t scripts/cycloneiv_clean_emit.py <bitstream.rbf> <out.v> [--summary out.json]
  python3.15t scripts/cycloneiv_clean_emit.py --image IMAGE <out.v>        (compressed image: decompressed to tmp/, removed at exit)
Read-only on the input.  Log: tmp/logs/cycloneiv_clean_emit.log.
"""
import argparse
import json
import logging
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

log = logging.getLogger("cycloneiv_clean_emit")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_emit.log")
PLANE = os.path.join(REPO, "tmp", "cycloneiv_clean", "emit_image_plane.rbf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("out")
    ap.add_argument("--image", action="store_true", help="input is a compressed image (cycloneiv_decompress)")
    ap.add_argument("--summary")
    ap.add_argument("--label")
    ap.add_argument("--package", default="auto", choices=["auto", "F484", "F672", "F896"], help="ball table: auto = inferred from the bitstream (pkginfer)")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    rbf, tmp = a.input, None
    if a.image:
        import cycloneiv_decompress as cd
        os.makedirs(os.path.dirname(PLANE), exist_ok=True)
        rbf = tmp = PLANE
        open(PLANE, "wb").write(cd.decompress(open(a.input, "rb").read(), {}))
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    t0 = time.time()
    try:
        with heavy_guard.lease(gb, "cyc4_clean_emit", log):
            cx = emit.Ctx()
            log.info("context %.1fs", time.time() - t0)
            nl = emit.Builder(cx, rbf, a.label or ("image" if a.image else None), package=a.package).run()
            text = emit.verilog(nl)
            open(a.out, "w").write(text)
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    s = emit.summary(nl)
    s["verilog_bytes"], s["verilog_lines"], s["seconds"] = len(text), text.count("\n"), round(time.time() - t0, 1)
    log.info("%s", json.dumps(s))
    if a.summary:
        json.dump(s, open(a.summary, "w"), indent=1)


if __name__ == "__main__":
    main()
