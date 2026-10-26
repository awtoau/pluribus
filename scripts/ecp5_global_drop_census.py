#!/usr/bin/env python3
"""Which global-clock wire families does the ECP5 lift drop?  (#109)

Decodes every ECP5 bitstream it is pointed at (Diamond oracle builds and the
third-party corpus), and for each decoded config arc asks the lifter's own
gkey() whether it keeps each endpoint.  Endpoints it returns None for are
chip-globals prjtrellis parks at (0,0) (`G_*` other than VPTX/HPBX/HPRX).
No lift is run; this is a property of the decoded arcs.

Per family (digits collapsed): arcs dropped, designs affected, tile types the
arc lives in.  Writes <out>/global_drop_census.json, log tmp/logs/ecp5_global_drop_census.log.
Usage: python3.15t scripts/ecp5_global_drop_census.py [--workers N] [--only SUBSTR]
"""
import argparse
import glob
import json
import os
import queue
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(SCRIPTS))
import toolchain  # noqa: E402
from ecp5_diamond_oracle import REPO, data_root  # noqa: E402
import heavy_guard  # noqa: E402

os.environ.setdefault("TRELLIS_DBROOT", toolchain.trellis_dbroot())
from lifters.ecp5_lift import ECP5Lift  # noqa: E402
import native_config  # noqa: E402
import ecp5_corpus_test as CT  # noqa: E402  (identify / materialise)

LOG_PATH = os.path.join(REPO, "tmp", "logs", "ecp5_global_drop_census.log")
_lock = threading.Lock()
_tls = threading.local()


class _GuardLog:
    @staticmethod
    def info(fmt, *a):
        log("[guard] " + (fmt % a))


def log(msg):
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    with _lock:
        print(f"{now}  {msg}", flush=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(f"{now}  {msg}\n")


def pat(nm):
    return re.sub(r"\d+", "#", nm)


def lifter(dev):
    if getattr(_tls, "dev", None) != dev:
        _tls.L = ECP5Lift(dev, dbroot=os.environ["TRELLIS_DBROOT"])
        _tls.dev = dev
    return _tls.L


def one(path, label, work):
    p, _gz = CT.materialise(path)
    dev, family, _idc, how = CT.identify(p)
    if dev is None or family != "ECP5":
        return {"label": label, "status": "skipped", "why": how if dev is None else family}
    L = lifter(dev)
    text, _pb, _bram = native_config.config_from_file(
        p, device=dev, db_root=os.environ["TRELLIS_DBROOT"])
    cfg = os.path.join(work, re.sub(r"[^A-Za-z0-9_.-]", "_", label) + ".config")
    with open(cfg, "w") as fh:
        fh.write(text)
    pc = L.parse_config(cfg)
    os.remove(cfg)
    fam = defaultdict(Counter)       # family -> {arcs, ...}
    tiles = defaultdict(Counter)     # family -> tile type -> arcs
    n_g = n_kept = 0
    for (r, c, sink, src) in pc.arcs:
        tt = pc.tile_type.get((r, c), "?")
        for nm in (sink, src):
            if not nm.startswith(("G_", "R_", "L_")):
                continue
            n_g += 1
            if L.gkey(r, c, nm) is None:
                fam[pat(nm)]["endpoints_dropped"] += 1
                tiles[pat(nm)][tt] += 1
            else:
                n_kept += 1
                fam[pat(nm)]["endpoints_kept"] += 1
                tiles[pat(nm)]["kept:" + tt] += 1
    return {"label": label, "status": "ok", "device": dev, "arcs": len(pc.arcs),
            "global_endpoints": n_g, "global_endpoints_kept": n_kept,
            "families": {k: dict(v) for k, v in fam.items()},
            "tiles": {k: dict(v) for k, v in tiles.items()}}


@heavy_guard.locked("ecp5_global_drop_census")
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--only")
    ap.add_argument("--sample", type=int, help="evenly spaced subset of N bitstreams")
    ap.add_argument("--thirdparty-only", action="store_true",
                    help="skip the Diamond builds (their drops are in the oracle compare)")
    args = ap.parse_args()
    root = os.path.abspath(args.data_root or data_root())
    out = os.path.join(root, "corpus", "ecp5", "diamond-oracle")
    work = os.path.join(REPO, "tmp", "census_work")
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    items = []
    for f in sorted(glob.glob(os.path.join(root, "corpus", "ecp5", "*.bit*"))):
        items.append(("thirdparty", os.path.basename(f), f))
    for f in ([] if args.thirdparty_only else sorted(glob.glob(os.path.join(out, "*", "oracle.json")))):
        o = json.load(open(f))
        if o.get("bit"):
            items.append(("diamond", o["target"], o["bit"]))
    if args.only:
        items = [i for i in items if args.only in i[1]]
    if args.sample and args.sample < len(items):
        step = len(items) / args.sample
        items = [items[int(i * step)] for i in range(args.sample)]
    log(f"[census] {len(items)} bitstreams, {args.workers} workers")
    # group by size so 85F decodes are spread, not bunched
    q = queue.Queue()
    for it in items:
        q.put(it)
    results, lock = [], threading.Lock()
    stop = threading.Event()

    def worker():
        last = 0.0
        while True:
            try:
                grp, label, path = q.get_nowait()
            except queue.Empty:
                return
            if heavy_guard.available_gb() < heavy_guard.MIN_AVAILABLE_GB:
                _tls.__dict__.pop("L", None)    # idle workers must not hold the memory they wait on
                _tls.dev = None
            heavy_guard.wait_available(_GuardLog, f"census {label}")
            try:
                r = one(path, label, work)
            except (Exception, SystemExit) as e:  # noqa: BLE001 -- recorded per bitstream
                r = {"label": label, "status": "failed", "error": f"{type(e).__name__}: {e}"}
            r["group"] = grp
            with lock:
                results.append(r)
                if len(results) % 25 == 0:
                    log(f"[census] {len(results)}/{len(items)}")

    t0 = time.monotonic()
    ths = [threading.Thread(target=worker) for _ in range(args.workers)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    summ = {"status": {g: dict(Counter(r["status"] for r in results if r["group"] == g))
                       for g in ("thirdparty", "diamond")},
            "failed": sorted((r["label"], r["error"]) for r in results
                             if r["status"] == "failed")[:20],
            "families": {}}
    for g in ("thirdparty", "diamond"):
        agg = defaultdict(lambda: {"endpoints_dropped": 0, "designs": 0, "tiles": Counter()})
        ok = [r for r in results if r["group"] == g and r["status"] == "ok"]
        for r in ok:
            for k, v in r["families"].items():
                agg[k]["endpoints_dropped"] += v.get("endpoints_dropped", 0)
                agg[k]["endpoints_kept"] = agg[k].get("endpoints_kept", 0) + v.get("endpoints_kept", 0)
                agg[k]["designs"] += 1
                agg[k]["tiles"].update(r["tiles"][k])
        summ["families"][g] = {
            k: {"endpoints_dropped": v["endpoints_dropped"],
                "endpoints_kept": v.get("endpoints_kept", 0), "designs": v["designs"],
                "of_designs": len(ok), "tiles": dict(v["tiles"].most_common())}
            for k, v in sorted(agg.items(), key=lambda kv: -kv[1]["designs"])}
        summ[f"{g}_global_endpoints"] = sum(r["global_endpoints"] for r in ok)
        summ[f"{g}_global_endpoints_kept"] = sum(r["global_endpoints_kept"] for r in ok)
    with open(os.path.join(out, "global_drop_census.json"), "w") as fh:
        json.dump({"summary": summ, "per_design": results}, fh, indent=1)
    log(f"[census] done in {time.monotonic() - t0:.1f}s: {summ['status']}")
    for g in ("thirdparty", "diamond"):
        log(f"[census] {g}: global endpoints {summ[g + '_global_endpoints']}, kept "
            f"{summ[g + '_global_endpoints_kept']}")
        for k, v in list(summ["families"][g].items())[:40]:
            log(f"[census]   {g} {k}: dropped {v['endpoints_dropped']} in "
                f"{v['designs']}/{v['of_designs']} designs; kept {v['endpoints_kept']}; tiles {v['tiles']}")


if __name__ == "__main__":
    main()
