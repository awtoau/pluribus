#!/usr/bin/env python3.15t
"""Peak memory of one profile_stages in-process stage, split by kind, plus top allocations (#149).

  python3.15t scripts/mem_report.py STAGE [--tracemalloc] [--top 15] [--json OUT]
  python3.15t scripts/mem_report.py --script scripts/cycloneiv_ddb_trace.py [--tracemalloc] -- score --designs 'gx150_rb*' --limit 3
  python3.15t scripts/mem_report.py --list

Reports (child process, /proc/self/status sampled every 50 ms):
  peak RSS, peak anonymous (heap + numpy: real memory pressure), peak file-backed (np.load mmap_mode='r',
  shared libs: reclaimable page cache, shared between processes), and RSS/anon/file after each phase the
  stage records.  --tracemalloc adds the top allocation sites at the anonymous peak (3-5x slower, so only
  for numpy-heavy stages).
Lease: heavy_guard.lease with JOB_GB-style estimate profile_stages.LEASE_GB[stage].  Log: tmp/logs/mem_report.log.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
LOG = os.path.join(REPO, "tmp", "logs", "mem_report.log")
SAMPLE_S = 0.05    # numpy phases last >= 0.1 s; a finer period only adds noise


def status_kb():
    d = {}
    with open("/proc/self/status") as fh:
        for ln in fh:
            k = ln.split(":")[0]
            if k in ("VmRSS", "RssAnon", "RssFile", "RssShmem", "VmHWM"):
                d[k] = int(ln.split()[1])
    return d


class Marks(dict):
    """Stage `ph` dict: every phase the stage records also snapshots memory."""

    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        s = status_kb()
        self.sink.append((k, s))


def child(stage, use_tm, top, script=None, sargs=()):
    import profile_stages as ps
    peak = {"anon": 0, "rss": 0, "file": 0}
    snap = {}
    stop = threading.Event()
    tm = None
    if use_tm:
        import tracemalloc
        tracemalloc.start(8)
        tm = tracemalloc

    def sampler():
        last_snap = 0
        while not stop.is_set():
            s = status_kb()
            peak["rss"] = max(peak["rss"], s["VmRSS"])
            peak["file"] = max(peak["file"], s.get("RssFile", 0))
            if s.get("RssAnon", 0) > peak["anon"]:
                peak["anon"] = s["RssAnon"]
                if tm is not None and peak["anon"] > last_snap * 1.1:
                    snap["s"] = tm.take_snapshot()
                    last_snap = peak["anon"]
            time.sleep(SAMPLE_S)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    marks = []
    ph = Marks(marks)
    t0 = time.perf_counter()
    if script:
        import runpy
        sys.argv = [script] + list(sargs)
        try:
            runpy.run_path(script, run_name="__main__")
        except SystemExit:
            pass
        out, stage = {}, os.path.basename(script)
    else:
        out = ps.INPROC[stage](ph)
    wall = time.perf_counter() - t0
    stop.set()
    th.join()
    gb = 1048576.0
    res = dict(stage=stage, wall_s=round(wall, 2),
               peak_rss_gb=round(peak["rss"] / gb, 3), peak_anon_gb=round(peak["anon"] / gb, 3),
               peak_file_gb=round(peak["file"] / gb, 3), hwm_gb=round(status_kb()["VmHWM"] / gb, 3),
               after_phase=[dict(phase=k, rss_gb=round(s["VmRSS"] / gb, 3), anon_gb=round(s.get("RssAnon", 0) / gb, 3),
                                 file_gb=round(s.get("RssFile", 0) / gb, 3)) for k, s in marks],
               info=out)
    if tm is not None and "s" in snap:
        res["top_alloc"] = [dict(site=str(st.traceback[0]), mb=round(st.size / 1048576, 1), n=st.count)
                            for st in snap["s"].statistics("lineno")[:top]]
    print("MEM_JSON " + json.dumps(res, default=str), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--tracemalloc", action="store_true")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json")
    ap.add_argument("--script", help="run a script's __main__ in-process instead of a named stage")
    ap.add_argument("--lease-gb", type=float, default=0.0)
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    argv = sys.argv[1:]
    sargs = []
    if "--" in argv:                       # everything after -- belongs to the --script target
        i = argv.index("--")
        argv, sargs = argv[:i], argv[i + 1:]
    a = ap.parse_args(argv)
    a.sargs = sargs
    import profile_stages as ps
    if a.list:
        print("\n".join(ps.INPROC))
        return
    if a.child:
        child(a.stage, a.tracemalloc, a.top, a.script, a.sargs)
        return
    import heavy_guard
    import logging
    lg = heavy_guard.stdout_log()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    gb = a.lease_gb or ps.LEASE_GB.get(a.stage or "", 4.0)
    cmd = [sys.executable, os.path.abspath(__file__)] + ([a.stage] if a.stage else []) + (
        ["--script", a.script] if a.script else []) + ["--child", "--top", str(a.top)]
    if a.tracemalloc:
        cmd.append("--tracemalloc")
    if a.sargs:
        cmd += ["--"] + a.sargs
    with heavy_guard.lease(gb, f"mem_report:{a.stage}", lg):
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    line = [x for x in p.stdout.splitlines() if x.startswith("MEM_JSON ")]
    if p.returncode or not line:
        print(p.stdout[-1500:], p.stderr[-1500:], file=sys.stderr)
        sys.exit(1)
    r = json.loads(line[0][9:])
    msg = (f"{r['stage']}: wall {r['wall_s']} s  peak RSS {r['peak_rss_gb']} GB = anon {r['peak_anon_gb']} "
           f"(heap+numpy) / file-backed {r['peak_file_gb']} (mmap, page cache)")
    print(msg)
    for ph in r["after_phase"]:
        print(f"  after {ph['phase']:<22} rss {ph['rss_gb']:.2f}  anon {ph['anon_gb']:.2f}  file {ph['file_gb']:.2f}")
    for t in r.get("top_alloc", []):
        print(f"  {t['mb']:>9.1f} MB  {t['n']:>9} blocks  {t['site']}")
    with open(LOG, "a") as fh:
        fh.write(time.strftime("%Y-%m-%dT%H:%M:%S%z ") + json.dumps(r, default=str) + "\n")
    if a.json:
        json.dump(r, open(a.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
