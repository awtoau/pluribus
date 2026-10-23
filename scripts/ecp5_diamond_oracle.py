#!/usr/bin/env python3
"""Diamond routing oracle for the ECP5 corpus (#109, ECP5 twin of #105).

Per target: `ncdread` (placement, configs, pin nets) + `ncd2nmc -r -io` (routing,
binary hard macro) -> parsed `oracle.json`.  No licence needed: only the NCD
readers run, never synthesis / PAR.  Format notes: docs/ecp5-diamond-oracle.md.

Targets (Diamond 3.14 builds already on disk, read-only):
  corpus/diamond/<T>/impl1/<name>_impl1.ncd (+ .bit)       Diamond builds
  diamond-fuzz/targets/sedga_*/impl1/fuzz_impl1.ncd (+ .bit)  ECP5 fuzz
Output (gitignored): <data-root>/corpus/ecp5/diamond-oracle/<target>/
  ncdread.txt ncdread.log io_keep.txt routing.nmc routing.ext ncd2nmc.log oracle.json

Usage:
  python3.15t scripts/ecp5_diamond_oracle.py [--workers N] [--only T ...]
      [--limit N] [--force] [--data-root D] [--out D]
Log: tmp/logs/ecp5_diamond_oracle.log
"""
import argparse
import glob
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone

import psutil

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
import diamond_oracle_parse as P  # noqa: E402
from machxo2_diamond_oracle import ToolError, diamond_env, _repo  # noqa: E402

REPO = _repo()
LOG_PATH = os.path.join(REPO, "tmp", "logs", "ecp5_diamond_oracle.log")
SCHEMA_VERSION = 1
SITE_SLOTS = 20          # ECP5 placement grid slots per row (docs/ecp5-diamond-oracle.md)

# Waits for one ncdread / ncd2nmc run.  Worst observed 6.3 s (ncd2nmc, 85F,
# 12 workers; docs/ecp5-diamond-oracle.md); x3 backstop, rounded up.
# Expiry: target failed with tool, limit, elapsed.
TOOL_TIMEOUT_S = 20.0
MEM_GATE_PCT = 85.0
MEM_LOG_EVERY_S = 30.0

_log_lock = threading.Lock()


def log(msg):
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    line = f"{now}  {msg}"
    with _log_lock:
        print(line, flush=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(line + "\n")


def data_root():
    """Worktree without corpus/ -> the shared main checkout (read-only inputs)."""
    if os.path.isdir(os.path.join(REPO, "corpus", "diamond")):
        return REPO
    gf = os.path.join(REPO, ".git")
    if os.path.isfile(gf):
        gd = open(gf).read().split("gitdir:")[1].strip()
        main = os.path.dirname(gd.split("/.git/worktrees/")[0] + "/.git")
        if os.path.isdir(os.path.join(main, "corpus", "diamond")):
            return main
    return REPO


def discover(root):
    """-> [{target, ncd, bit, group}] sorted; ncd/bit may be None (counted)."""
    out = []
    for d in sorted(glob.glob(os.path.join(root, "corpus", "diamond", "*", "impl1"))):
        t = os.path.basename(os.path.dirname(d))
        ncds = [p for p in glob.glob(os.path.join(d, "*_impl1.ncd"))]
        bits = glob.glob(os.path.join(d, "*_impl1.bit"))
        out.append({"target": t, "group": "diamond", "ncd": ncds[0] if ncds else None,
                    "bit": bits[0] if bits else None})
    for d in sorted(glob.glob(os.path.join(root, "diamond-fuzz", "targets", "sedga_*"))):
        n = os.path.join(d, "impl1", "fuzz_impl1.ncd")
        b = os.path.join(d, "impl1", "fuzz_impl1.bit")
        out.append({"target": os.path.basename(d), "group": "sedga",
                    "ncd": n if os.path.exists(n) else None,
                    "bit": b if os.path.exists(b) else None})
    return out


_DEV_CACHE = {}
_DEV_LOCK = threading.Lock()


def device_info(device, package):
    """Diamond device (LFE5U-25F) -> {max_row, pins} from device-db/."""
    key = (device, package)
    with _DEV_LOCK:
        if key not in _DEV_CACHE:
            with open(os.path.join(REPO, "device-db", "devices.json")) as fh:
                spec = json.load(fh)["families"]["ECP5"]["devices"].get(device)
            if spec is None:
                raise P.FormatError(f"devices.json has no ECP5 device {device}")
            with open(os.path.join(REPO, "device-db", "ECP5", device, "iodb.json")) as fh:
                pins = json.load(fh)["packages"].get(package)
            if pins is None:
                raise P.FormatError(f"iodb has no package {package} for {device}")
            _DEV_CACHE[key] = {"max_row": spec["max_row"], "max_col": spec["max_col"],
                               "pins": pins}
        return _DEV_CACHE[key]


def run_tool(argv, cwd, env, log_path, timeout):
    t0 = time.monotonic()
    try:
        r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ToolError(f"{os.path.basename(argv[0])} timed out: limit "
                        f"{timeout}s, elapsed {time.monotonic() - t0:.2f}s")
    dt = time.monotonic() - t0
    with open(log_path, "w") as fh:
        fh.write(r.stdout)
        fh.write(r.stderr)
    if r.returncode != 0:
        raise ToolError(f"{os.path.basename(argv[0])} rc={r.returncode}: "
                        f"{(r.stdout + r.stderr).strip()[-300:]}")
    low = (r.stdout + r.stderr).lower()
    if "licen" in low and ("fail" in low or "error" in low or "expired" in low):
        raise ToolError(f"{os.path.basename(argv[0])} LICENCE message: "
                        f"{(r.stdout + r.stderr).strip()[-300:]}")
    return dt


def oracle_up_to_date(ncd, oj):
    if not os.path.exists(oj) or os.path.getmtime(oj) < os.path.getmtime(ncd):
        return False
    try:
        with open(oj) as fh:
            return json.load(fh).get("schema_version") == SCHEMA_VERSION
    except (OSError, ValueError):
        return False


def process(tg, out_root, env, bindir, force, timeout):
    t = tg["target"]
    if tg["ncd"] is None:
        return {"target": t, "status": "no_ncd"}
    od = os.path.join(out_root, t)
    oj = os.path.join(od, "oracle.json")
    if not force and oracle_up_to_date(tg["ncd"], oj):
        return {"target": t, "status": "skipped"}
    os.makedirs(od, exist_ok=True)
    times = {}
    ncdread_txt = os.path.join(od, "ncdread.txt")
    times["ncdread"] = run_tool([os.path.join(bindir, "ncdread"), "-o", ncdread_txt,
                                 tg["ncd"]], od, env,
                                os.path.join(od, "ncdread.log"), timeout)
    with open(os.path.join(od, "ncdread.log")) as fh:
        mdev = re.search(r"^Device:\s+(\S+)", fh.read(), re.M)
    if not mdev:
        raise P.FormatError("ncdread log names no device")
    with open(ncdread_txt) as fh:
        ncdr = P.parse_ncdread(fh.read())
    dev = device_info(mdev.group(1), ncdr["package"])
    # Keep every pad (ncd2nmc otherwise deletes I/O comps and unroutes their nets).
    # ECP5 pad sites are BGA balls (N3, B10), slices are R<r>C<c><A-D>, and other
    # hard IP uses other names; keep exactly the sites that are iodb package pins.
    io_keep = os.path.join(od, "io_keep.txt")
    with open(io_keep, "w") as fh:
        for c in ncdr["comps"]:
            if c["site"] is not None and c["site"] in dev["pins"]:
                fh.write(c["name"] + "\n")
    nmc = os.path.join(od, "routing.nmc")
    times["ncd2nmc"] = run_tool([os.path.join(bindir, "ncd2nmc"), "-r", "-io", io_keep,
                                 "-o", nmc, tg["ncd"]], od, env,
                                os.path.join(od, "ncd2nmc.log"), timeout)
    with open(os.path.join(od, "ncd2nmc.log")) as fh:
        n2n_log = fh.read()
    with open(nmc, "rb") as fh:
        macro = P.parse_nmc(fh.read())
    oracle = P.build_oracle(ncdr, macro, n2n_log, dev["max_row"], dev["pins"],
                            site_slots=SITE_SLOTS, unique_votes=True)
    oracle["schema_version"] = SCHEMA_VERSION
    oracle["target"] = t
    oracle["group"] = tg["group"]
    oracle["ncd"] = tg["ncd"]
    oracle["bit"] = tg["bit"]
    oracle["tool_seconds"] = times
    tmp = oj + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(oracle, fh, indent=1, sort_keys=True)
    os.replace(tmp, oj)
    return {"target": t, "status": "ok", "times": times, "device": oracle["device"],
            "has_bit": tg["bit"] is not None,
            "n_comps": len(oracle["comps"]), "n_nets": len(oracle["nets"]),
            "warnings": oracle["warnings"]}


def wait_for_memory(stop):
    last = 0.0
    while psutil.virtual_memory().percent >= MEM_GATE_PCT and not stop.is_set():
        now = time.monotonic()
        if now - last >= MEM_LOG_EVERY_S:
            log(f"[mem] {psutil.virtual_memory().percent:.0f}% >= "
                f"{MEM_GATE_PCT:.0f}%: waiting")
            last = now
        stop.wait(1.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 4))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timeout", type=float, default=TOOL_TIMEOUT_S)
    args = ap.parse_args()
    root = os.path.abspath(args.data_root or data_root())
    out = os.path.abspath(args.out or os.path.join(root, "corpus", "ecp5", "diamond-oracle"))
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    os.makedirs(out, exist_ok=True)

    d, env = diamond_env()
    bindir = os.path.join(d, "ispfpga", "bin", "lin64")
    targets = discover(root)
    if args.only:
        targets = [t for t in targets if t["target"] in set(args.only)]
    if args.limit:
        targets = targets[:args.limit]
    log(f"[oracle] {len(targets)} targets, {args.workers} workers, root={root} out={out}")

    q = queue.Queue()
    for t in targets:
        q.put(t)
    results = []
    res_lock = threading.Lock()
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            try:
                t = q.get_nowait()
            except queue.Empty:
                return
            wait_for_memory(stop)
            try:
                r = process(t, out, env, bindir, args.force, args.timeout)
            except (ToolError, P.FormatError) as e:
                r = {"target": t["target"], "status": "failed", "error": str(e)}
            except Exception as e:  # noqa: BLE001 -- recorded per target, not hidden
                r = {"target": t["target"], "status": "failed",
                     "error": f"{type(e).__name__}: {e}"}
            with res_lock:
                results.append(r)
                n = len(results)
            if r["status"] == "failed":
                log(f"[fail] {t['target']}: {r['error']}")
            if n % 50 == 0:
                log(f"[oracle] {n}/{len(targets)}")

    ths = [threading.Thread(target=worker) for _ in range(args.workers)]
    t0 = time.monotonic()
    for th in ths:
        th.start()
    for th in ths:
        th.join()

    st = Counter(r["status"] for r in results)
    tmax = {k: max((r["times"][k] for r in results if "times" in r), default=0.0)
            for k in ("ncdread", "ncd2nmc")}
    warn = Counter(w.split(":")[0] for r in results for w in r.get("warnings", []))
    nobit = sorted(r["target"] for r in results
                   if r["status"] == "ok" and not r["has_bit"])
    dev = Counter(r["device"] for r in results if r["status"] == "ok")
    log(f"[oracle] done in {time.monotonic() - t0:.1f}s: {dict(st)}")
    log(f"[oracle] devices: {dict(dev)}; ok but no .bit: {len(nobit)}")
    log(f"[oracle] max tool wall time this run: {tmax} (timeout {args.timeout}s)")
    log(f"[oracle] warnings by kind: {dict(warn)}")
    fails = Counter(r["error"].split(":")[0] for r in results if r["status"] == "failed")
    for k, v in fails.most_common():
        log(f"[oracle]   failed {v}: {k}")
    if not (st["ok"] or st["failed"]):
        return      # pure resume: keep the summary of the run that did the work
    with open(os.path.join(out, "_batch_summary.json"), "w") as fh:
        json.dump({"status": dict(st), "devices": dict(dev), "no_bit": nobit,
                   "max_tool_seconds": tmax, "warnings": dict(warn),
                   "no_ncd": sorted(r["target"] for r in results
                                    if r["status"] == "no_ncd"),
                   "failed": sorted((r["target"], r["error"]) for r in results
                                    if r["status"] == "failed")}, fh, indent=1)


if __name__ == "__main__":
    main()
