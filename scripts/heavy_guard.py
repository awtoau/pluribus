"""Host-safety guard for heavy batch jobs (Quartus fits, Diamond oracle, ECP5 lifts).

- One heavy batch at a time across all scripts: exclusive flock on tmp/heavy.lock.
- New work starts only when AVAILABLE RAM >= min_available_gb (absolute, not a percent).
- The lock lives in the git COMMON dir, so every worktree shares it (a per-checkout tmp/ lock let
  concurrent worktrees run heavy batches together and swap the box, #122).
- Why: the box idles at ~74% used (IDE, VM, browser), so a percent gate admitted jobs that
  together exceeded RAM; systemd-oomd killed the IDE three times on 2026-10-23 (#111).

Waits: lock retry 5 s (other batches run minutes; a poll costs nothing), log every 30 s
(a silent wait looks like a hang). No expiry: waiting is the safe outcome.
"""
import contextlib
import fcntl
import logging
import os
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lock_path():
    env = os.environ.get("PLURIBUS_HEAVY_LOCK")
    if env:
        return env
    import subprocess
    r = subprocess.run(["git", "-C", REPO, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return os.path.join(r.stdout.strip(), "pluribus-heavy.lock")
    return os.path.join(REPO, "tmp", "heavy.lock")


LOCK_PATH = _lock_path()
MIN_AVAILABLE_GB = float(os.environ.get("PLURIBUS_MIN_AVAILABLE_GB", "6"))
HELD_ENV = "PLURIBUS_HEAVY_HELD"  # set while the lock is held; inherited by child stages
POLL_S = 5
LOG_S = 30


def stdout_log():
    """Logger for lock waits in scripts that build their own logger later."""
    lg = logging.getLogger("heavy_guard")
    if not lg.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
    return lg


def _wait(pred, what, log, poll=None):
    poll = POLL_S if poll is None else poll
    t0, last = time.monotonic(), 0.0
    while not pred():
        now = time.monotonic()
        if now - last >= LOG_S:
            log.info("%s (waited %.0fs)", what, now - t0)
            last = now
        threading.Event().wait(poll)


def available_gb():
    import psutil
    return psutil.virtual_memory().available / 2**30


def wait_available(log, what="", min_gb=None):
    need = MIN_AVAILABLE_GB if min_gb is None else min_gb
    _wait(lambda: available_gb() >= need,
          f"{what}: waiting for >= {need:.0f} GB available RAM (now {available_gb():.1f})", log)


# Measured peak RSS per job (GB); sources and dates in docs/performance.md.  Worker counts derive
# from these and BATCH_MAX_GB, so a RAM upgrade retunes by setting PLURIBUS_BATCH_MAX_GB (and
# PLURIBUS_MIN_AVAILABLE_GB) only.  Unmeasured jobs are absent on purpose: workers_for() refuses them.
JOB_GB = {
    "ecp5_85f_lift_process": 1.0,    # graph + one target, 85F, per process (2 procs measured 1.9 GB; was 7.5 before #149)
    "ecp5_85f_lift_threads_base": 0.8,   # 85F, threads mode, graph (no arcs, lazy bels) + first lift: 0.68 measured (#149)
    "ecp5_85f_lift_thread_extra": 0.25,  # each further concurrent 85F lift: (2.05-0.68)/7 = 0.20 measured
    "ecp5_graph_45f": 0.4,           # graph without arcs: 0.35 measured, shared across threads of one process
    "ecp5_graph_25f": 0.25,          # 0.21 measured
    "ecp5_target_extra_25f": 0.35,   # marginal RSS of one more concurrent 25F target on a shared graph
    "quartus_fit_small": 1.06,       # quartus_fit RSS, corpus-size Cyclone V design (map: 0.53)
    "cyclonev_sim_job": 0.07,        # load.py / verilog.py child of lifted_sim_check (iverilog path)
    "quartus_chain_cyc4": 1.2,       # map/fit/asm chain, Cyclone IV GX specimen (peak ~1.3, docs/rust-candidates.md)
    "cyc4_dec_active": 1.2,          # Dec.active, RSS 1.11 (anon 0.40, rest shared page cache); was 2.1 before #149
    "cyc4_tracer": 2.6,              # ddb_trace score x3: RSS 2.51 (anon 1.7); was 3.26 before #149
    "cyc4_bit_inventory": 2.6,       # bit inventory: RSS 2.3-2.6 (anon 1.0, rest mmap)
    "reach2_fnirsi": 0.7,            # reach2.py fnirsi, streamed rows: 613 MB measured (#149)
    "reach2_stage": 2.1,             # reach2.py V02, 2.65 M rows (not re-measured; fnirsi now 0.61, was 1.5)
    "lifter_equiv_target": 0.1,      # per worker thread: 8 threads + yosys children peak 0.13 GB PSS total (#149)
    "unknown_bits_census": 0.05,     # per worker thread, MachXO2 decode: 8 threads peak 0.08 GB PSS total (#149)
    "validate_fuzz_target": 0.1,     # per worker thread: 4 threads + ecpunpack/load.py children peak 0.35 GB PSS total (#149)
    "native_corpus_parity": 0.05,    # per worker thread: 8 threads peak 0.10 GB PSS total (#149)
    "cyc4_clean_gate_base": 2.6,     # static edge table + routing + resolver + asmdb walk; peak 3.4-4.05 GB at 3 workers (2026-10-30, tmp/logs/lease_telemetry.jsonl)
    "cyc4_clean_gate_worker": 0.6,   # per concurrent design (plane + fire temporaries + RCF)
    "bench_reach_sql": 3.0,          # scripts/bench_reach_sql.py: reach + reach2 children on one DB copy
}
BATCH_FILL = 0.8   # fraction of BATCH_MAX_GB planned for workers; the rest is headroom for peaks


def workers_for(job, cap, base_gb=0.0):
    """Workers that fit BATCH_MAX_GB * BATCH_FILL after a fixed base: floor((cap_gb - base) / JOB_GB[job]),
    clamped to [1, cap].  KeyError for an unmeasured job: measure it, add it to JOB_GB."""
    per = JOB_GB[job]
    return max(1, min(cap, int((BATCH_MAX_GB * BATCH_FILL - base_gb) // per)))


SCOPE_ENV = "PLURIBUS_SCOPE"  # set once the batch runs in its own capped cgroup scope
BATCH_MAX_GB = float(os.environ.get("PLURIBUS_BATCH_MAX_GB", "56"))

# Memory leases: a counting semaphore in GB across every process on the box, so concurrent jobs
# (agents, sweeps, analyses) share the budget instead of each assuming it owns the machine.
# heavy_lock stays for whole-batch exclusivity; lease() is the fine-grained path and lets
# jobs run side by side while their declared peaks fit.  Memory pressure (swap thrash) is what
# degrades speed and takes the box down, not job count.
LEASE_PATH = LOCK_PATH + ".leases"
LEASE_BUDGET_GB = float(os.environ.get("PLURIBUS_LEASE_BUDGET_GB", str(BATCH_MAX_GB)))
LEASE_RAMP_S = 0.5  # was 3.0: one admission per ramp window capped a 20 s Quartus chain pool at ~5 concurrent jobs; leases are accounted by declared GB, the RAM floor covers the lag
LEASE_POLL_S = 0.5  # lease admission re-check (was POLL_S = 5): waiting is an Event.wait, no CPU


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lease_ledger():
    """Live leases {token: {pid, gb, name, t}} (stale pids dropped); read-only snapshot for status tools."""
    import json
    try:
        with open(LEASE_PATH) as fh:
            fcntl.flock(fh, fcntl.LOCK_SH)  # writers truncate+write under LOCK_EX; unlocked read saw partial JSON
            raw = fh.read()
        data = json.loads(raw) if raw.strip() else {}
    except FileNotFoundError:
        return {}
    return {k: v for k, v in data.items() if _alive(v["pid"])}


SAMPLE_S = 1.0          # RSS sample period: a Quartus map/fit peak lasts seconds, 1 s resolution sees it
BLOCKED_AFTER_S = 60.0  # a job blocked this long (~2 job lengths) sheds cached memory while it waits
LEASE_LOG = os.path.join(REPO, "tmp", "logs", "lease_telemetry.jsonl")
_mon = {"lock": threading.Lock(), "active": {}, "thread": None}


def tree_rss_gb():
    """RSS of this process and all its children, GB."""
    import psutil
    p = psutil.Process()
    tot = 0
    for q in [p, *p.children(recursive=True)]:
        try:
            tot += q.memory_info().rss
        except psutil.Error:
            pass
    return tot / 2**30


def _sampler():
    while True:
        threading.Event().wait(SAMPLE_S)
        with _mon["lock"]:
            if not _mon["active"]:
                _mon["thread"] = None
                return
            cur = tree_rss_gb()
            n = len(_mon["active"])
            for st in _mon["active"].values():
                st["peak"] = max(st["peak"], cur)
                st["conc"] = max(st["conc"], n)


def trim_memory():
    """Hand freed heap back to the OS (glibc keeps it otherwise): what a blocked job should do."""
    import gc
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass


def _cap_override(name, default):
    """Live tuning without restarts: tmp/limits/<name>.max holds an integer cap for concurrent leases of that name."""
    try:
        with open(os.path.join(REPO, "tmp", "limits", name + ".max")) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return default


@contextlib.contextmanager
def lease(gb, name, log, budget_gb=None, on_blocked=None, max_same_name=None):
    """Hold `gb` GB of the shared memory budget while the body runs, and MEASURE what it really used.

    Admitted when sum(live leases) + gb <= budget, AVAILABLE RAM - gb >= MIN_AVAILABLE_GB, and no lease
    is younger than LEASE_RAMP_S.  A job larger than the whole budget runs alone (empty ledger).
    Acquire BEFORE loading big data.  Waiting costs no CPU (Event.wait between checks, no spinning);
    after BLOCKED_AFTER_S blocked, `on_blocked` (default trim_memory: gc + malloc_trim) runs once so a
    waiting job does not sit on memory.  Waits log every LOG_S; no expiry (waiting is the safe outcome).
    On release one JSON line goes to LEASE_LOG: declared GB, wait, hold time, observed peak tree RSS
    above the admission baseline, max concurrent leases in this process; `heavy_guard.py report` turns
    the log into corrections for JOB_GB (declared numbers are claims, the log is the measurement).
    """
    import json
    import uuid
    budget = LEASE_BUDGET_GB if budget_gb is None else budget_gb
    token = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    os.makedirs(os.path.dirname(LEASE_PATH), exist_ok=True)
    t_req = time.monotonic()
    blocked = {"done": False}

    def try_admit():
        with open(LEASE_PATH, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            raw = fh.read()
            data = json.loads(raw) if raw.strip() else {}
            data = {k: v for k, v in data.items() if _alive(v["pid"])}
            used = sum(v["gb"] for v in data.values())
            now = time.time()
            fits = (used + gb <= budget) or not data
            cap = _cap_override(name, max_same_name)
            if cap is not None and sum(1 for v in data.values() if v['name'] == name) >= cap:
                fits = False   # global concurrency cap for this kind of job (CPU headroom), across every process
            ramp_ok = all(now - v["t"] >= LEASE_RAMP_S for v in data.values())
            ram_ok = available_gb() - gb >= MIN_AVAILABLE_GB
            ok = fits and ramp_ok and ram_ok
            if ok:
                data[token] = {"pid": os.getpid(), "gb": gb, "name": name, "t": now}
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(data))
        if not ok and not blocked["done"] and time.monotonic() - t_req >= BLOCKED_AFTER_S:
            blocked["done"] = True
            log.info("%s: blocked %.0fs, shedding cached memory", name, time.monotonic() - t_req)
            (on_blocked or trim_memory)()
        return ok

    _wait(try_admit, f"{name}: waiting for {gb:g} GB of the {budget:g} GB memory budget "
                     f"(leased {sum(v['gb'] for v in lease_ledger().values()):.1f}, "
                     f"avail {available_gb():.1f})", log, poll=LEASE_POLL_S)
    t_run = time.monotonic()
    base = tree_rss_gb()
    st = {"peak": base, "conc": 1}
    with _mon["lock"]:
        _mon["active"][token] = st
        for o in _mon["active"].values():
            o["conc"] = max(o["conc"], len(_mon["active"]))
        if _mon["thread"] is None:
            _mon["thread"] = threading.Thread(target=_sampler, daemon=True)
            _mon["thread"].start()
    try:
        yield
    finally:
        with _mon["lock"]:
            _mon["active"].pop(token, None)
            st["peak"] = max(st["peak"], tree_rss_gb())
        with open(LEASE_PATH, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            raw = fh.read()
            data = json.loads(raw) if raw.strip() else {}
            data.pop(token, None)
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(data))
        try:
            os.makedirs(os.path.dirname(LEASE_LOG), exist_ok=True)
            with open(LEASE_LOG, "a") as fh:
                fh.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "name": name, "declared_gb": gb,
                                     "wait_s": round(t_run - t_req, 1), "held_s": round(time.monotonic() - t_run, 1),
                                     "peak_delta_gb": round(max(0.0, st["peak"] - base), 2),
                                     "conc": st["conc"], "pid": os.getpid()}) + "\n")
        except OSError:
            pass


def report():
    """Declared vs observed per lease name from LEASE_LOG (observed = peak tree-RSS growth / concurrent leases)."""
    import json
    import statistics
    rows = {}
    try:
        for ln in open(LEASE_LOG):
            r = json.loads(ln)
            rows.setdefault(r["name"], []).append(r)
    except FileNotFoundError:
        print("no lease telemetry yet:", LEASE_LOG)
        return
    print(f"{'name':28} {'n':>5} {'declared':>8} {'obs/job p50':>11} {'obs/job max':>11} {'wait p50 s':>10} {'held p50 s':>10}  verdict")
    for name, rs in sorted(rows.items()):
        obs = [r["peak_delta_gb"] / max(1, r["conc"]) for r in rs]
        dec = max(r["declared_gb"] for r in rs)
        v = "UNDER-declared" if max(obs) > dec * 1.2 else ("over-declared (>3x)" if max(obs) * 3 < dec else "ok")
        print(f"{name:28} {len(rs):5d} {dec:8.2f} {statistics.median(obs):11.2f} {max(obs):11.2f} "
              f"{statistics.median(r['wait_s'] for r in rs):10.1f} {statistics.median(r['held_s'] for r in rs):10.1f}  {v}")
    print("live leases:", {k: (v['name'], v['gb']) for k, v in lease_ledger().items()})


if __name__ == "__main__":
    if sys.argv[1:] == ["report"]:
        report()
    else:
        sys.exit("usage: heavy_guard.py report")

def isolate_in_scope():
    """Re-exec the running batch script in its own memory-capped systemd user scope.

    systemd-oomd kills the largest cgroup under app.slice when pressure passes 80%; batches that
    share the IDE's scope take the IDE and every agent with them (2026-10-26, #124). In their own
    scope they are the kill target, and MemoryMax with no swap OOM-kills inside the scope first.
    Skipped under pytest, when already scoped, off systemd, or with PLURIBUS_NO_ISOLATE=1.
    """
    import shutil
    if (os.environ.get(SCOPE_ENV) or os.environ.get("PLURIBUS_NO_ISOLATE") or "pytest" in sys.modules
            or not shutil.which("systemd-run") or not sys.argv or not os.path.isfile(sys.argv[0])):
        return
    cmd = ["systemd-run", "--user", "--scope", "--collect", "--quiet", "-p", f"MemoryMax={BATCH_MAX_GB:g}G",
           "-p", "MemorySwapMax=0", "-E", f"{SCOPE_ENV}=1", sys.executable, *sys.argv]
    os.execvp(cmd[0], cmd)


@contextlib.contextmanager
def heavy_lock(name, log):
    isolate_in_scope()
    if os.environ.get(HELD_ENV):  # a parent batch already holds the lock; child stages must not deadlock on it
        yield
        return
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    fh = open(LOCK_PATH, "a+")

    def try_lock():
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    _wait(try_lock, f"{name}: another heavy batch holds {LOCK_PATH}", log)
    fh.seek(0)
    fh.truncate()
    fh.write(f"{name} pid={os.getpid()}\n")
    fh.flush()
    os.environ[HELD_ENV] = str(os.getpid())
    try:
        yield
    finally:
        os.environ.pop(HELD_ENV, None)
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


# Overall backstop per external tool (#122); the stall limit (60 s no CPU progress) is the primary guard.
OVERALL_S = {
    "quartus_fit": 420,  # 3x 140 s worst quartus_fit (e50f die probe, 2026-10-23)
    "quartus_asm": 360,  # 3x 120 s cold asm (cyclonev corpus build)
    "quartus_cpf": 120,  # existing cpf limit, corpus cpf 0.3 s typical
    "quartus": 60,       # map/eda/sta/sh: 3.7 s / 0.6 s / 0.9 s in the corpus build, ~16x
    "mistral": 15,       # mistral-cv decomp 1.2 s in the corpus build, existing limit kept
    "diamondc": 180,     # whole flow 10-20 s (2026-10-24); 3x = 60 s is under the stall limit
    "other": 300,        # unlisted tool: backstop only, stall guard is primary
    "diamond_tool": 20,  # ncd/bstool/ldbanno: sub-second to 20 s (ecp5_diamond_oracle TOOL_TIMEOUT_S)
    "yosys": 300,        # startup 0.05 s; LEC runtime unmeasured, backstop only
    "iverilog": 60,      # existing cycloneiv_sim_check limit; 0.04 s on the model files
    "vvp": 120,          # existing sim_replacement default; 0.015 s per simulated us
    "nextpnr": 300,      # unmeasured here, backstop only
    "gowin": 300,        # unmeasured here, backstop only
    "ecp5_tool": 60,     # ecpunpack/ecppack/unsquashfs: sub-second on 1-4 MB images
}


def locked(name):
    """Decorator: run fn (a batch main) under heavy_lock; re-entrant across child processes."""
    import functools

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            with heavy_lock(name, stdout_log()):
                return fn(*a, **k)
        return wrapper
    return deco


def _tree_cpu_s(proc):
    """CPU seconds of a process and all its descendants; None once it is gone."""
    import psutil
    try:
        procs = [proc] + proc.children(recursive=True)
        return sum(sum(p.cpu_times()[:2]) for p in procs if p.is_running())
    except psutil.Error:
        return None


def run_stall_guarded(cmd, what, log, stall_s=60, overall_s=600, **popen_kw):
    """_run_stall_guarded with a private TMPDIR that is removed afterwards, even when the tool is killed.

    EDA tools (Quartus alt*.dir, 5.7 MB each) leak scratch when killed; per-run removal bounds the leak to zero.
    """
    import shutil
    import tempfile
    job_tmp = tempfile.mkdtemp(prefix="job-", dir=os.environ.get("TMPDIR") or None)
    env = dict(popen_kw.pop("env", None) or os.environ, TMPDIR=job_tmp)
    try:
        return _run_stall_guarded(cmd, what, log, stall_s, overall_s, env=env, **popen_kw)
    finally:
        shutil.rmtree(job_tmp, ignore_errors=True)


def _run_stall_guarded(cmd, what, log, stall_s=60, overall_s=600, **popen_kw):
    """subprocess.run replacement that cannot hang a batch.

    - Kills the whole process tree when its CPU time does not advance for stall_s (hung/blocked),
      or when overall_s elapses (busy-loop backstop; callers pass 3x their measured cold worst case).
    - On expiry logs what, the limit, elapsed and loadavg, and returns returncode=-9 with
      .timed_out set. Output is captured to temp files (no pipe deadlock).
    """
    import psutil
    import subprocess
    import tempfile
    out, err = tempfile.TemporaryFile(mode="w+"), tempfile.TemporaryFile(mode="w+")
    p = subprocess.Popen([str(c) for c in cmd], stdout=out, stderr=err, text=True, **popen_kw)
    ps = psutil.Process(p.pid)
    t0 = last_t = time.monotonic()
    last_cpu, why = -1.0, None
    while p.poll() is None:
        try:
            p.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        now = time.monotonic()
        cpu = _tree_cpu_s(ps)
        if cpu is not None and cpu != last_cpu:
            last_cpu, last_t = cpu, now
        if now - last_t > stall_s:
            why = f"no CPU progress for {now - last_t:.0f}s (stall limit {stall_s}s)"
        elif now - t0 > overall_s:
            why = f"ran {now - t0:.0f}s (overall limit {overall_s}s)"
        if why:
            for c in ps.children(recursive=True) + [ps]:
                try:
                    c.kill()
                except psutil.Error:
                    pass
            p.wait()
            log.error("%s: KILLED, %s, loadavg %.1f, cmd %s", what, why, os.getloadavg()[0], " ".join(map(str, cmd))[:200])
            break
    out.seek(0)
    err.seek(0)
    r = subprocess.CompletedProcess(cmd, -9 if why else p.returncode, out.read(), err.read())
    r.timed_out = bool(why)
    return r


def overall_for(cmd):
    """OVERALL_S entry for the tool named by cmd[0] (quartus_fit/asm/cpf, diamondc, yosys, ...)."""
    n = os.path.basename(str(cmd[0]))
    for pre, key in (("quartus_fit", "quartus_fit"), ("quartus_asm", "quartus_asm"), ("quartus_cpf", "quartus_cpf"),
                     ("quartus", "quartus"), ("mistral", "mistral"), ("diamondc", "diamondc"), ("pnmainc", "diamondc"),
                     ("yosys", "yosys"), ("iverilog", "iverilog"), ("vvp", "vvp"), ("nextpnr", "nextpnr"),
                     ("gw_sh", "gowin"), ("gowin", "gowin"), ("ecp", "ecp5_tool"), ("unsquashfs", "ecp5_tool")):
        if n.startswith(pre):
            return OVERALL_S[key]
    return OVERALL_S["other"]


def guarded(cmd, what=None, log=None, overall_s=None, stall_s=60, **popen_kw):
    """run_stall_guarded with the per-tool OVERALL_S limit and a stdout logger by default (#122)."""
    return run_stall_guarded(cmd, what or os.path.basename(str(cmd[0])), log or stdout_log(), stall_s,
                             overall_s or overall_for(cmd), **popen_kw)
