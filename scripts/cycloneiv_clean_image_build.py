#!/usr/bin/env python3.15t
"""Build the simulation inputs of the third-party EP4CGX150 image from HEAD (#165): pickled emit Netlist + flat Verilog + RTL Verilog.

  PLURIBUS_DJI_IMAGE=<image> python3.15t scripts/cycloneiv_clean_image_build.py [--out tmp/image_sim] [--no-rtl]
Outputs (tmp/, never committed): nl.pkl, flat.v, rtl.v, build.json (counts only).  Image is read only; the decompressed plane is removed at exit.
Log tmp/logs/cycloneiv_clean_image_build.log.
"""
import argparse
import json
import logging
import os
import pickle
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("image_build")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_image_build.log")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default=os.environ.get("PLURIBUS_DJI_IMAGE"))
    ap.add_argument("--out", default=os.path.join(REPO, "tmp", "image_sim"))
    ap.add_argument("--no-rtl", action="store_true")
    a = ap.parse_args()
    if not a.image:
        raise SystemExit("image path: argument or PLURIBUS_DJI_IMAGE")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    import cycloneiv_decompress as cd
    import heavy_guard
    from lifters.cycloneiv_clean import emit, rtl
    # per-process name: two concurrent builds (even with different --out) must not race on
    # a shared plane.rbf; the old fixed name let one process's `finally: os.remove` delete
    # a sibling process's still-open plane mid-run (FileNotFoundError in pkginfer.infer).
    plane = os.path.join(a.out, f"plane.{os.getpid()}.rbf")
    open(plane, "wb").write(cd.decompress(open(a.image, "rb").read(), {}))
    t0 = time.time()
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + 4 * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    res = {}
    try:
        with heavy_guard.lease(gb, "cyc4_image_build", log):
            nl = emit.Builder(emit.Ctx(), plane, "image").run()
            res["emit_seconds"] = round(time.time() - t0, 1)
            open(os.path.join(a.out, "flat.v"), "w").write(emit.verilog(nl))
            res["summary"] = emit.summary(nl)
            pickle.dump(nl, open(os.path.join(a.out, "nl.pkl"), "wb"))
            if not a.no_rtl:
                t1 = time.time()
                text, rep = rtl.lift(nl)
                open(os.path.join(a.out, "rtl.v"), "w").write(text)
                res["rtl_seconds"] = round(time.time() - t1, 1)
    finally:
        if os.path.exists(plane):
            os.remove(plane)
    log.info("%s", json.dumps({k: v for k, v in res.items() if k != "summary"}))
    json.dump(res, open(os.path.join(a.out, "build.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
