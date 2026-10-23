#!/usr/bin/env python3
"""Diamond routing oracle for the MachXO2 fuzz corpus (#105).

Per target: `ncdread` (placement, configs, pin nets) + `ncd2nmc -r` (routing,
binary hard macro) -> parsed `oracle.json`.  Format notes:
docs/machxo2-diamond-oracle.md.

Layout (gitignored): corpus/machxo2/diamond-fuzz/<target>/
  ncdread.txt  routing.nmc  routing.ext  ncd2nmc.log  io_keep.txt  oracle.json

Usage:
  python3.15t scripts/machxo2_diamond_oracle.py [--workers N] [--only T ...]
      [--limit N] [--force] [--targets-dir D] [--out D]
Log: tmp/logs/machxo2_diamond_oracle.log
"""
import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import psutil

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
import toolchain  # noqa: E402
import diamond_oracle_parse as P  # noqa: E402


def _repo():
    """$PLURIBUS_REPO -> git toplevel -> file-relative (awto-dan#35)."""
    env = os.environ.get("PLURIBUS_REPO")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    try:
        # local .git read, ~1 ms warm; 0.25 s covers a cold exec.  Expiry: fallback.
        out = subprocess.run(["git", "-C", SCRIPTS, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=0.25)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.dirname(SCRIPTS)


REPO = _repo()
LOG_PATH = os.path.join(REPO, "tmp", "logs", "machxo2_diamond_oracle.log")
SCHEMA_VERSION = 1

# Waits for one ncdread / ncd2nmc run.  Worst observed 0.80 s (16 workers, full
# corpus, 3 runs; docs/machxo2-diamond-oracle.md); x3 backstop, rounded up.  The
# batch logs its max each run.  Expiry: target failed with tool, limit, elapsed.
TOOL_TIMEOUT_S = 2.5
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


def diamond_env():
    d = toolchain.diamond_root()
    env = dict(os.environ,
               FOUNDRY=os.path.join(d, "ispfpga"),
               LD_LIBRARY_PATH=os.pathsep.join([
                   os.path.join(d, "bin", "lin64"),
                   os.path.join(d, "ispfpga", "bin", "lin64"),
                   os.environ.get("LD_LIBRARY_PATH", "")]))
    return d, env


_DEV_CACHE = {}
_DEV_LOCK = threading.Lock()


def device_info(device, package):
    """Diamond device (LCMXO2-1200HC) -> {max_row, pins} from device-db/."""
    key = (device, package)
    with _DEV_LOCK:
        if key not in _DEV_CACHE:
            base = re.sub(r"(HC|HE|ZE)$", "", device)
            ddir = os.path.join(REPO, "device-db", "MachXO2", base)
            with open(os.path.join(REPO, "device-db", "devices.json")) as fh:
                spec = json.load(fh)["families"]["MachXO2"]["devices"][base]
            with open(os.path.join(ddir, "iodb.json")) as fh:
                pins = json.load(fh)["packages"].get(package)
            if pins is None:
                raise P.FormatError(f"iodb has no package {package} for {base}")
            _DEV_CACHE[key] = {"max_row": spec["max_row"], "pins": pins}
        return _DEV_CACHE[key]


class ToolError(Exception):
    pass


def run_tool(argv, cwd, env, log_path):
    t0 = time.monotonic()
    try:
        r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=TOOL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise ToolError(f"{os.path.basename(argv[0])} timed out: limit "
                        f"{TOOL_TIMEOUT_S}s, elapsed {time.monotonic() - t0:.2f}s")
    dt = time.monotonic() - t0
    with open(log_path, "w") as fh:
        fh.write(r.stdout)
        fh.write(r.stderr)
    if r.returncode != 0:
        raise ToolError(f"{os.path.basename(argv[0])} rc={r.returncode}: "
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


def process(target, targets_dir, out_root, env, bindir, force):
    ncd = os.path.join(targets_dir, target, "impl1", "fuzz_impl1.ncd")
    if not os.path.exists(ncd):
        return {"target": target, "status": "no_ncd"}
    od = os.path.join(out_root, target)
    oj = os.path.join(od, "oracle.json")
    if not force and oracle_up_to_date(ncd, oj):
        return {"target": target, "status": "skipped"}
    with open(ncd, "rb") as fh:
        mhdr = re.search(rb"(LCMXO2-\w+|LFE5U-\w+|LCMXO3\w*-\w+)", fh.read(512))
    if mhdr and not mhdr.group(1).startswith(b"LCMXO2-"):
        # ncdread alone takes >1 s on an 85F (device load); not this oracle's family.
        return {"target": target, "status": "skipped_family",
                "device": mhdr.group(1).decode()}
    os.makedirs(od, exist_ok=True)
    times = {}
    ncdread_txt = os.path.join(od, "ncdread.txt")
    times["ncdread"] = run_tool(
        [os.path.join(bindir, "ncdread"), "-o", ncdread_txt, ncd],
        od, env, os.path.join(od, "ncdread.log"))
    with open(os.path.join(od, "ncdread.log")) as fh:
        mdev = re.search(r"^Device:\s+(\S+)", fh.read(), re.M)
    if not mdev:
        raise P.FormatError("ncdread log names no device")
    if not mdev.group(1).startswith("LCMXO2-"):
        return {"target": target, "status": "skipped_family", "device": mdev.group(1)}
    with open(ncdread_txt) as fh:
        ncdr = P.parse_ncdread(fh.read())
    dev = device_info(mdev.group(1), ncdr["package"])
    # Keep every pad: by default ncd2nmc deletes I/O comps and unroutes any
    # net a pad drives.  -io <file> lists the I/O comps to keep.
    io_keep = os.path.join(od, "io_keep.txt")
    with open(io_keep, "w") as fh:
        for c in ncdr["comps"]:
            if c["site"] is not None and c["site"].isdigit():
                fh.write(c["name"] + "\n")
    nmc = os.path.join(od, "routing.nmc")
    times["ncd2nmc"] = run_tool(
        [os.path.join(bindir, "ncd2nmc"), "-r", "-io", io_keep, "-o", nmc, ncd],
        od, env, os.path.join(od, "ncd2nmc.log"))
    with open(os.path.join(od, "ncd2nmc.log")) as fh:
        n2n_log = fh.read()
    with open(nmc, "rb") as fh:
        macro = P.parse_nmc(fh.read())
    oracle = P.build_oracle(ncdr, macro, n2n_log, dev["max_row"], dev["pins"])
    oracle["schema_version"] = SCHEMA_VERSION
    oracle["target"] = target
    oracle["tool_seconds"] = times
    tmp = oj + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(oracle, fh, indent=1, sort_keys=True)
    os.replace(tmp, oj)
    return {"target": target, "status": "ok", "times": times,
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
    ap.add_argument("--targets-dir",
                    default=os.path.join(REPO, "diamond-fuzz", "targets"))
    ap.add_argument("--out",
                    default=os.path.join(REPO, "corpus", "machxo2", "diamond-fuzz"))
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    # Tools run with cwd = the target's out dir, so paths must be absolute.
    args.out = os.path.abspath(args.out)
    args.targets_dir = os.path.abspath(args.targets_dir)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    d, env = diamond_env()
    bindir = os.path.join(d, "ispfpga", "bin", "lin64")
    targets = args.only or sorted(os.listdir(args.targets_dir))
    if args.limit:
        targets = targets[:args.limit]
    log(f"[oracle] {len(targets)} targets, {args.workers} workers, "
        f"targets={args.targets_dir} out={args.out}")

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
                r = process(t, args.targets_dir, args.out, env, bindir, args.force)
            except (ToolError, P.FormatError) as e:
                r = {"target": t, "status": "failed", "error": str(e)}
            except Exception as e:  # noqa: BLE001 -- recorded per target, not hidden
                r = {"target": t, "status": "failed",
                     "error": f"{type(e).__name__}: {e}"}
            with res_lock:
                results.append(r)
                n = len(results)
            if r["status"] == "failed":
                log(f"[fail] {t}: {r['error']}")
            if n % 200 == 0:
                log(f"[oracle] {n}/{len(targets)}")

    ths = [threading.Thread(target=worker) for _ in range(args.workers)]
    t0 = time.monotonic()
    for th in ths:
        th.start()
    for th in ths:
        th.join()

    from collections import Counter
    st = Counter(r["status"] for r in results)
    tmax = {k: max((r["times"][k] for r in results if "times" in r), default=0.0)
            for k in ("ncdread", "ncd2nmc")}
    warn = Counter(w.split(":")[0] for r in results for w in r.get("warnings", []))
    log(f"[oracle] done in {time.monotonic() - t0:.1f}s: {dict(st)}")
    log(f"[oracle] max tool wall time this run: {tmax} (timeout {TOOL_TIMEOUT_S}s)")
    log(f"[oracle] warnings by kind: {dict(warn)}")
    fails = Counter(r["error"].split(":")[0] for r in results if r["status"] == "failed")
    for k, v in fails.most_common():
        log(f"[oracle]   failed {v}: {k}")
    with open(os.path.join(args.out, "_batch_summary.json"), "w") as fh:
        json.dump({"status": dict(st), "max_tool_seconds": tmax,
                   "warnings": dict(warn),
                   "failed": sorted((r["target"], r["error"]) for r in results
                                    if r["status"] == "failed")}, fh, indent=1)


if __name__ == "__main__":
    main()
