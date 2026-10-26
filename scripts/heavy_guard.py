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
MIN_AVAILABLE_GB = float(os.environ.get("PLURIBUS_MIN_AVAILABLE_GB", "12"))
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


def _wait(pred, what, log):
    t0, last = time.monotonic(), 0.0
    while not pred():
        now = time.monotonic()
        if now - last >= LOG_S:
            log.info("%s (waited %.0fs)", what, now - t0)
            last = now
        threading.Event().wait(POLL_S)


def available_gb():
    import psutil
    return psutil.virtual_memory().available / 2**30


def wait_available(log, what="", min_gb=None):
    need = MIN_AVAILABLE_GB if min_gb is None else min_gb
    _wait(lambda: available_gb() >= need,
          f"{what}: waiting for >= {need:.0f} GB available RAM (now {available_gb():.1f})", log)


SCOPE_ENV = "PLURIBUS_SCOPE"  # set once the batch runs in its own capped cgroup scope
BATCH_MAX_GB = float(os.environ.get("PLURIBUS_BATCH_MAX_GB", "28"))


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
