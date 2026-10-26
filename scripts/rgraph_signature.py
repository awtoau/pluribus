#!/usr/bin/env python3
"""SHA-256 signature + build time + peak RSS of a NativeRoutingGraph per device.

Equivalence check for routing-graph build changes: same signature before/after.
Signature covers wires (sorted), arcs (in stored order), bels (sorted by key).
Usage: python3.15t scripts/rgraph_signature.py LFE5U-25F LCMXO2-1200HC [--json OUT]
Log:   tmp/logs/rgraph_signature.log
"""
import argparse
import hashlib
import json
import os
import resource
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
for _i, _a in enumerate(sys.argv):      # --nt-root DIR: build with another native_trellis checkout
    if _a == "--nt-root":
        sys.path.insert(0, sys.argv[_i + 1])
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402
from native_trellis.rgraph import NativeRoutingGraph  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "rgraph_signature.log")


def signature(rg):
    h = hashlib.sha256()
    for loc in sorted(rg.wires):
        h.update(repr((loc, sorted(rg.wires[loc]))).encode())
    for loc in sorted(rg.arcs):
        h.update(repr((loc, [tuple(a) for a in rg.arcs[loc]])).encode())
    for loc in sorted(rg.bels):
        b = rg.bels[loc]
        h.update(repr((loc, [(k, tuple(b[k].pins.items()) if hasattr(b[k], "pins") else b[k])
                             for k in sorted(b)])).encode())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("devices", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--nt-root", help="directory whose native_trellis/ is used instead of the repo's")
    ap.add_argument("--lock", action="store_true", help="hold the heavy lock (85F-size builds)")
    a = ap.parse_args()
    lg = heavy_guard.stdout_log()
    if a.lock:
        with heavy_guard.heavy_lock("rgraph_signature", lg):
            heavy_guard.wait_available(lg, "rgraph_signature", min_gb=16)
            run(a)
    else:
        heavy_guard.wait_available(lg, "rgraph_signature", min_gb=16)
        run(a)


def run(a):
    import native_trellis
    print("native_trellis from", native_trellis.__file__, "threads", os.environ.get("PLURIBUS_RGRAPH_THREADS", "auto"))
    db = toolchain.trellis_dbroot()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    out = {}
    for dev in a.devices:
        t0 = time.monotonic()
        rg = NativeRoutingGraph(dev, db)
        build_s = time.monotonic() - t0
        sig = signature(rg)
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20
        out[dev] = {"sha256": sig, "build_s": round(build_s, 2), "peak_rss_gb": round(rss, 2),
                    "wires": sum(len(v) for v in rg.wires.values()),
                    "arcs": sum(len(v) for v in rg.arcs.values())}
        line = f"{dev} {out[dev]}"
        print(line, flush=True)
        with open(LOG, "a") as fh:
            fh.write(line + "\n")
        del rg
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=1)


if __name__ == "__main__":
    main()
