import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import heavy_guard  # noqa: E402

LOG = logging.getLogger("test_heavy_guard")


def test_lock_is_shared_across_worktrees():
    # the git common dir is identical for every worktree of one repo
    assert os.path.basename(heavy_guard.LOCK_PATH) == "pluribus-heavy.lock"
    assert os.path.basename(os.path.dirname(heavy_guard.LOCK_PATH)) == ".git"


def test_stall_guard_kills_idle_process():
    r = heavy_guard.run_stall_guarded(
        [sys.executable, "-c", "import time\nwhile True: time.sleep(5)"], "idle", LOG, stall_s=2, overall_s=30)
    assert r.timed_out and r.returncode == -9


def test_stall_guard_passes_normal_exit():
    r = heavy_guard.run_stall_guarded([sys.executable, "-c", "print('ok')"], "ok", LOG)
    assert not r.timed_out and r.returncode == 0 and r.stdout.strip() == "ok"
