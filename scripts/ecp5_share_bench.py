#!/usr/bin/env python3.15t
"""Memory/wall benchmark + output-identity check for concurrent ECP5 lifts (#146).

Runs N concurrent decode+lift jobs (one design each) in a child process (threads) or a
process pool, samples the process tree's PSS, and records a digest of every lifted netlist so
two code paths can be compared bit for bit.

  run   --n 4 --device 85F --mode threads [--tag before]   one measured configuration
  digest --paths a.bit b.bit ... --out tmp/x.json            serial digests only (no sampling)
  compare a.json b.json                                      exit 1 if any digest differs

Guards: heavy_guard.lease (declared GB) + >=20 GB available before start; child killed if tree PSS > --cap-gb
(default 22) or if its CPU time stops advancing for 60 s (stall = hung).
Logs: tmp/logs/ecp5_share_bench.log; results: tmp/share-bench/<tag>.json
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import multiprocessing as mp
import os
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

OUT = os.path.join(REPO, "tmp", "share-bench")
LOG = os.path.join(REPO, "tmp", "logs", "ecp5_share_bench.log")
STALL_S = 60          # no CPU advance for this long = hung (host-process stall rule)
SAMPLE_S = 0.25       # PSS sample period: a lift phase lasts seconds


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as fh:
        fh.write(line + "\n")


# ---------------------------------------------------------------- one job
def _h(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=repr).encode()).hexdigest()


def lift_job(path):
    """Decode + lift one bitstream; return timings and content digests."""
    import ecp5_corpus_test as ct
    import native_config
    from lifters.machxo2_lift import write_netlist_verilog
    t = {}
    t0 = time.perf_counter()
    raw, _ = ct.materialise(os.path.join(REPO, path))
    dev, fam, idc, _how = ct.identify(raw)
    text, pb, _bram = native_config.config_from_file(raw, device=dev, db_root=ct.DBROOT)
    t["decode_s"] = round(time.perf_counter() - t0, 2)
    os.makedirs(OUT, exist_ok=True)
    stem = hashlib.sha256(path.encode()).hexdigest()[:12]
    cfg_p = os.path.join(OUT, f"{stem}.config")
    with open(cfg_p, "w") as fh:
        fh.write(text)
    t1 = time.perf_counter()
    lift = ct.make_lifter("ecp5", dev)
    t["init_s"] = round(time.perf_counter() - t1, 2)
    t2 = time.perf_counter()
    pc = lift.parse_config(cfg_p)
    d = lift.recover_netlist(pc)
    t["lift_s"] = round(time.perf_counter() - t2, 2)
    cens = {}
    cens.update(ct.census_config(text))
    metrics, findings = ct.check_netlist(d, cens)
    v_p = os.path.join(OUT, f"{stem}.v")
    write_netlist_verilog(d, v_p, dev, "bench")
    with open(v_p, "rb") as fh:
        vsha = hashlib.sha256(fh.read()).hexdigest()
    os.unlink(v_p)
    os.unlink(cfg_p)
    return dict(path=path, device=dev, t=t,
                cfg=hashlib.sha256(text.encode()).hexdigest(),
                luts=_h(d.luts), ffs=_h(d.ffs), nets=_h(d.all_nets),
                net_name=_h(sorted(map(repr, d.net_name.items()))),
                n_arcs=d.n_arcs, skipped=d.skipped_arcs,
                metrics=_h(metrics), findings=_h(findings), verilog=vsha,
                n_luts=len(d.luts), n_ffs=len(d.ffs), n_nets=len(d.all_nets))


# ---------------------------------------------------------------- selection
def scan_devices():
    cache = os.path.join(REPO, "tmp", "ecp5_devscan.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    import ecp5_corpus_test as ct
    res = {}
    for root in ("corpus/ecp5", "corpus/diamond"):
        for r, _d, fs in os.walk(os.path.join(REPO, root)):
            for f in sorted(fs):
                if f.endswith(".bit"):
                    p = os.path.join(r, f)
                    m, _ = ct.materialise(p)
                    dev = ct.identify(m)[0]
                    res.setdefault(str(dev), []).append((os.path.getsize(p), os.path.relpath(p, REPO)))
    json.dump(res, open(cache, "w"))
    return res


def pick(devsub, n, skip_smallest=0):
    """n designs whose device contains devsub, evenly spread over the size-sorted list."""
    items = []
    for dev, lst in scan_devices().items():
        if devsub in dev:
            items += [tuple(x) for x in lst]
    items.sort()
    items = items[skip_smallest:]
    if n >= len(items):
        return [p for _s, p in items]
    step = len(items) / n
    return [items[int(i * step)][1] for i in range(n)]


# ---------------------------------------------------------------- child
def child(args):
    paths = json.loads(args.paths)
    if args.mode == "threads":
        ex = cf.ThreadPoolExecutor(len(paths))
    else:
        ex = cf.ProcessPoolExecutor(len(paths), mp_context=mp.get_context("spawn"))
    t0 = time.perf_counter()
    with ex:
        futs = [ex.submit(lift_job, p) for p in paths]
        res = []
        for f in cf.as_completed(futs):
            r = f.result()
            res.append(r)
            print(f"done {r['path']} {r['t']}", flush=True)
    wall = time.perf_counter() - t0
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    res.sort(key=lambda r: r["path"])
    print("RESULT " + json.dumps(dict(wall_s=round(wall, 2), gil_enabled=gil, jobs=res)), flush=True)


# ---------------------------------------------------------------- parent
def _tree(pid):
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        try:
            with open(f"/proc/{p}/task/{p}/children") as fh:
                todo += [int(x) for x in fh.read().split()]
        except OSError:
            pass
    return out


def _pss_kb(pid):
    try:
        with open(f"/proc/{pid}/smaps_rollup") as fh:
            for ln in fh:
                if ln.startswith("Pss:"):
                    return int(ln.split()[1])
    except OSError:
        pass
    return 0


def _cpu_ticks(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            f = fh.read().rsplit(")", 1)[1].split()
        return int(f[11]) + int(f[12]) + int(f[13]) + int(f[14])   # utime stime cutime cstime
    except OSError:
        return 0


def avail_gb():
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable"):
            return int(ln.split()[1]) / 1048576
    return 0.0


def default_lease_gb(args):
    """Declared peak: processes hold one graph each (JOB_GB), threads share one graph + extras."""
    import heavy_guard
    if args.mode == "procs":
        return 1.5 * args.n          # graph without arcs, one per process (before_p2: 1.85 GB for 2)
    return (heavy_guard.JOB_GB["ecp5_85f_lift_threads_base"]
            + heavy_guard.JOB_GB["ecp5_85f_lift_thread_extra"] * (args.n - 1))


def run(args):
    import heavy_guard
    paths = pick(args.device, args.n, args.skip)
    log(f"run tag={args.tag} mode={args.mode} n={args.n} device~{args.device} paths={len(paths)}")
    for p in paths:
        log(f"  {p}")
    cmd = [sys.executable, os.path.abspath(__file__), "_child", "--mode", args.mode,
           "--paths", json.dumps(paths)]
    env = dict(os.environ)
    env.update(kv.split("=", 1) for kv in args.env)
    lease_gb = args.lease_gb or default_lease_gb(args)
    log(f"lease {lease_gb:g} GB of the {heavy_guard.LEASE_BUDGET_GB:g} GB budget")
    if lease_gb > heavy_guard.LEASE_BUDGET_GB:
        log(f"SKIP: lease {lease_gb:g} GB exceeds the budget; extrapolate instead of running")
        return 3
    with heavy_guard.lease(lease_gb, f"ecp5_share_bench:{args.tag}", heavy_guard.stdout_log()):
        if avail_gb() < args.min_avail_gb:
            log(f"ABORT only {avail_gb():.1f} GB available (< {args.min_avail_gb})")
            return 2
        t0 = time.perf_counter()
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        lines = []
        threading.Thread(target=lambda: [lines.append(x.rstrip("\n")) for x in pr.stdout],
                         daemon=True).start()
        peak_kb, last_cpu, last_adv, killed = 0, -1, time.monotonic(), None
        while pr.poll() is None:
            kb = sum(_pss_kb(p) for p in _tree(pr.pid))
            peak_kb = max(peak_kb, kb)
            cpu = sum(_cpu_ticks(p) for p in _tree(pr.pid))
            now = time.monotonic()
            if cpu != last_cpu:
                last_cpu, last_adv = cpu, now
            if kb / 1048576 > args.cap_gb:
                killed = f"PSS {kb / 1048576:.1f} GB > cap {args.cap_gb}"
            elif now - last_adv > STALL_S:
                killed = f"no CPU progress for {STALL_S}s; loadavg {os.getloadavg()}"
            if killed:
                for p in _tree(pr.pid):
                    try:
                        os.kill(p, 9)
                    except OSError:
                        pass
                break
            time.sleep(SAMPLE_S)
        pr.wait()
        wall = time.perf_counter() - t0
    rec = dict(tag=args.tag, mode=args.mode, n=args.n, device=args.device, env=args.env,
               wall_total_s=round(wall, 2), peak_pss_gb=round(peak_kb / 1048576, 2), killed=killed)
    res = [x for x in lines if x.startswith("RESULT ")]
    if res and not killed:
        rec.update(json.loads(res[0][7:]))
    else:
        rec["tail"] = lines[-15:]
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"{args.tag}.json")
    json.dump(rec, open(out, "w"), indent=1)
    log(f"RESULT tag={args.tag} wall={rec['wall_total_s']}s peak_pss={rec['peak_pss_gb']}GB "
        f"killed={killed} gil_enabled={rec.get('gil_enabled')} -> {out}")
    return 1 if killed else 0


def digest(args):
    import heavy_guard
    with heavy_guard.lease(heavy_guard.JOB_GB["ecp5_85f_lift_process"], "ecp5_share_bench:digest",
                           heavy_guard.stdout_log()):
        res = [lift_job(p) for p in args.paths]
    for r in res:
        r.pop("t")
    json.dump(res, open(args.out, "w"), indent=1)
    log(f"digest {len(res)} designs -> {args.out}")


def compare(args):
    def load(p):
        d = json.load(open(p))
        jobs = d["jobs"] if isinstance(d, dict) else d
        out = {}
        for j in jobs:
            j.pop("t", None)
            out[j["path"]] = j
        return out
    a, b = load(args.a), load(args.b)
    bad = 0
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            bad += 1
            diff = [f for f in (a.get(k) or {}) if (a.get(k) or {}).get(f) != (b.get(k) or {}).get(f)]
            log(f"DIFFERS {k}: {diff}")
    log(f"compare: {len(set(a) & set(b))} common designs, {bad} differ")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--n", type=int, required=True)
    r.add_argument("--device", default="85F", help="substring of the device name")
    r.add_argument("--skip", type=int, default=0, help="skip the K smallest designs")
    r.add_argument("--mode", choices=["threads", "procs"], default="threads")
    r.add_argument("--tag", required=True)
    r.add_argument("--env", action="append", default=[], help="KEY=VAL for the child")
    r.add_argument("--cap-gb", type=float, default=22.0)
    r.add_argument("--lease-gb", type=float, default=0.0, help="override the declared peak")
    r.add_argument("--min-avail-gb", type=float, default=20.0)
    c = sub.add_parser("_child")
    c.add_argument("--mode", default="threads")
    c.add_argument("--paths", required=True)
    d = sub.add_parser("digest")
    d.add_argument("--paths", nargs="+", required=True)
    d.add_argument("--out", required=True)
    k = sub.add_parser("compare")
    k.add_argument("a")
    k.add_argument("b")
    args = ap.parse_args()
    sys.exit({"run": run, "_child": child, "digest": digest, "compare": compare}[args.cmd](args) or 0)


if __name__ == "__main__":
    main()
