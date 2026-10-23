"""Host-safety guard for heavy batch jobs (Quartus fits, Diamond oracle, ECP5 lifts).

- One heavy batch at a time across all scripts: exclusive flock on tmp/heavy.lock.
- New work starts only when AVAILABLE RAM >= min_available_gb (absolute, not a percent).
- Why: the box idles at ~74% used (IDE, VM, browser), so a percent gate admitted jobs that
  together exceeded RAM; systemd-oomd killed the IDE three times on 2026-10-23 (#111).

Waits: lock retry 5 s (other batches run minutes; a poll costs nothing), log every 30 s
(a silent wait looks like a hang). No expiry: waiting is the safe outcome.
"""
import contextlib
import fcntl
import os
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_PATH = os.path.join(REPO, "tmp", "heavy.lock")
MIN_AVAILABLE_GB = float(os.environ.get("PLURIBUS_MIN_AVAILABLE_GB", "12"))
POLL_S = 5
LOG_S = 30


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


@contextlib.contextmanager
def heavy_lock(name, log):
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
    try:
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
