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


def test_lock_is_reentrant_for_child_stages(tmp_path, monkeypatch):
    monkeypatch.setattr(heavy_guard, "LOCK_PATH", str(tmp_path / "l.lock"))
    with heavy_guard.heavy_lock("outer", LOG):
        assert os.environ.get(heavy_guard.HELD_ENV)
        with heavy_guard.heavy_lock("inner", LOG):  # would block forever without the held marker
            pass
    assert not os.environ.get(heavy_guard.HELD_ENV)


def test_overall_for_known_tools():
    f = heavy_guard.overall_for
    assert f(["/x/quartus_fit", "p"]) == heavy_guard.OVERALL_S["quartus_fit"]
    assert f(["yosys"]) == heavy_guard.OVERALL_S["yosys"]
    assert f(["/opt/mistral-cv", "decomp"]) == heavy_guard.OVERALL_S["mistral"]
    assert f(["something_else"]) == heavy_guard.OVERALL_S["other"]


def test_guarded_default_limit_and_capture():
    r = heavy_guard.guarded([sys.executable, "-c", "print('hi')"], "py")
    assert r.returncode == 0 and r.stdout.strip() == "hi" and not r.timed_out


def test_batch_runs_in_own_capped_scope(tmp_path):
    import shutil
    import subprocess
    import pytest
    if not shutil.which("systemd-run"):
        pytest.skip("no systemd-run")
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import logging, os, sys\n"
        f"sys.path.insert(0, {os.path.dirname(heavy_guard.__file__)!r})\n"
        "import heavy_guard\n"
        "with heavy_guard.heavy_lock('probe', logging.getLogger('p')):\n"
        "    cg = open('/proc/self/cgroup').read()\n"
        "    mx = open('/sys/fs/cgroup' + cg.strip().split('::')[1] + '/memory.max').read().strip()\n"
        "    print(cg.strip().split('/')[-1], mx)\n")
    env = {k: v for k, v in os.environ.items() if k not in ("PLURIBUS_SCOPE", "PLURIBUS_HEAVY_HELD", "PLURIBUS_NO_ISOLATE")}
    env["PLURIBUS_HEAVY_LOCK"] = str(tmp_path / "l.lock")
    r = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, env=env, timeout=60)
    unit, mx = r.stdout.split()
    assert unit.startswith("run-") and unit.endswith(".scope")
    assert int(mx) == int(heavy_guard.BATCH_MAX_GB * 2**30)
