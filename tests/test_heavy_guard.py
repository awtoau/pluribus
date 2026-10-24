"""heavy_guard: lock exclusivity across processes; RAM wait returns once threshold is met."""
import logging
import os
import subprocess
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import heavy_guard  # noqa: E402

log = logging.getLogger("test_heavy_guard")

# Child: take the lock, print HELD, exit when stdin closes.
CHILD = (
    "import sys, logging; sys.path.insert(0, %r); import heavy_guard\n"
    "heavy_guard.LOCK_PATH = %r\n"
    "with heavy_guard.heavy_lock('child', logging.getLogger('c')):\n"
    "    print('HELD', flush=True); sys.stdin.read()\n"
)


def test_lock_excludes_second_process(tmp_path, monkeypatch):
    lock = str(tmp_path / "heavy.lock")
    monkeypatch.setattr(heavy_guard, "LOCK_PATH", lock)
    monkeypatch.setattr(heavy_guard, "POLL_S", 0.05)
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD % (os.path.join(REPO, "scripts"), lock)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "HELD"
        got = threading.Event()

        def parent():
            with heavy_guard.heavy_lock("parent", log):
                got.set()

        th = threading.Thread(target=parent, daemon=True)
        th.start()
        # Child holds the lock: parent must not acquire while it is alive.
        assert not got.wait(0.5)
        child.stdin.close()          # child exits, lock released
        assert got.wait(10)          # parent acquires: bounded by child exit + 1 poll
        th.join(10)
    finally:
        child.kill()
        child.wait()


def test_wait_available_returns_when_threshold_lowered(monkeypatch):
    monkeypatch.setattr(heavy_guard, "POLL_S", 0.05)
    monkeypatch.setattr(heavy_guard, "available_gb", lambda: 4.0)
    done = threading.Event()

    def waiter():
        heavy_guard.wait_available(log, "t", min_gb=1e6)   # unreachable
        done.set()

    th = threading.Thread(target=waiter, daemon=True)
    th.start()
    assert not done.wait(0.3)        # blocked while threshold unmet
    # Same call with a reachable threshold returns promptly.
    heavy_guard.wait_available(log, "t", min_gb=1.0)
    # Unblock the first waiter by making RAM look plentiful.
    monkeypatch.setattr(heavy_guard, "available_gb", lambda: 2e6)
    assert done.wait(5)
    th.join(5)
