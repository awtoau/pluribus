#!/usr/bin/env python3.15t
"""Wide-mux census over the ECP5 corpus, split into real wide muxes and CCU2 aliases (#116).

`F# <- F5x_SLICE / FXx_SLICE` arcs in a MODE=CCU2 slice are bit aliasing with
CCU2.INJECT1 (bits.db: same bit), not wide muxes; the rest are real.  Decode-only.
Usage: python3.15t scripts/ecp5_widemux_census.py [--workers 3] [--oracle-dir DIR]
Out:   tmp/ecp5_widemux_census.json   Log: tmp/logs/ecp5_widemux_census.log
"""
import argparse
import glob
import json
import os
import queue
import sys
import threading
import time

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, REPO)
import toolchain  # noqa: E402
import heavy_guard  # noqa: E402
import ecp5_corpus_test as T  # noqa: E402
from ecp5_diamond_oracle import data_root  # noqa: E402
import native_config  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "ecp5_widemux_census.log")
_lock = threading.Lock()


class _G:
    @staticmethod
    def info(fmt, *a):
        log("[guard] " + (fmt % a))


def log(msg):
    with _lock:
        print(msg, flush=True)
        with open(LOG, "a") as fh:
            fh.write(msg + "\n")


def one(rec, root):
    rec = dict(rec, label=rec.get("label") or os.path.basename(rec["local"]))
    path = os.path.join(root, rec["local"])
    if not os.path.exists(path):
        return dict(label=rec.get("label"), status="missing")
    path, _gz = T.materialise(path)
    dev, family, _idc, how = T.identify(path)
    if dev is None or family != "ECP5":
        return dict(label=rec.get("label"), status=f"skip ({family or how})")
    heavy_guard.wait_available(_G, f"decode {rec.get('label')}")
    text, _pb, _bram = native_config.config_from_file(
        path, device=dev, db_root=toolchain.trellis_dbroot())
    return dict(label=rec.get("label"), status="ok", device=dev, **T.census_widemux(text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--oracle-dir", default=None,
                    help="dir of <target>/decoded.config (the Diamond builds)")
    args = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    root = data_root()
    with open(os.path.join(root, "corpus", "manifest.json")) as fh:
        man = json.load(fh)
    recs = man if isinstance(man, list) else man.get("entries") or man.get("files") or []
    q = queue.Queue()
    for r in recs:
        if r.get("local"):
            q.put(r)
    out, t0 = [], time.monotonic()

    def worker():
        while True:
            try:
                r = q.get_nowait()
            except queue.Empty:
                return
            try:
                res = one(r, root)
            except Exception as e:      # noqa: BLE001 -- recorded per file
                res = dict(label=r.get("label"), status=f"error {type(e).__name__}: {e}")
            with _lock:
                out.append(res)

    ths = [threading.Thread(target=worker) for _ in range(args.workers)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    if args.oracle_dir:
        for f in sorted(glob.glob(os.path.join(args.oracle_dir, "*_dm_*", "decoded.config"))):
            with open(f) as fh:
                out.append(dict(label=os.path.basename(os.path.dirname(f)), status="ok",
                                diamond=True, **T.census_widemux(fh.read())))
    ok = [r for r in out if r["status"] == "ok"]
    real = [r for r in ok if r["widemux_arcs"] > 0]
    alias = [r for r in ok if r["widemux_ccu2_alias_arcs"] > 0]
    summ = dict(designs=len(ok), real_designs=len(real), alias_designs=len(alias),
                real_arcs=sum(r["widemux_arcs"] for r in ok),
                alias_arcs=sum(r["widemux_ccu2_alias_arcs"] for r in ok),
                skipped=len(out) - len(ok))
    with open(os.path.join(REPO, "tmp", "ecp5_widemux_census.json"), "w") as fh:
        json.dump(dict(summary=summ, results=out), fh, indent=1)
    log(f"[census] {summ} in {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    main()
