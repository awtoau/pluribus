"""Scratch from EDA tools must not leak: per-run TMPDIR removed after the run (also when killed); toolchain reaps stale dirs."""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import heavy_guard  # noqa: E402


def test_run_gets_private_tmp_and_removes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    r = heavy_guard.run_stall_guarded(
        [sys.executable, "-c", "import os,sys;d=os.environ['TMPDIR'];open(d+'/alt0754_1.dir','w').write('x');print(d)"],
        "t", logging.getLogger("t"), stall_s=30, overall_s=30)
    d = r.stdout.strip()
    assert d.startswith(str(tmp_path)) and d != str(tmp_path)
    assert not os.path.exists(d)          # removed with the run
    assert list(tmp_path.iterdir()) == []


def test_killed_run_still_cleans(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    r = heavy_guard.run_stall_guarded(
        [sys.executable, "-c", "import os,time;open(os.environ['TMPDIR']+'/leak','w').write('x')\nwhile True: pass"],
        "t", logging.getLogger("t"), stall_s=30, overall_s=1)
    assert r.timed_out
    assert list(tmp_path.iterdir()) == []


def test_toolchain_reaps_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("PLURIBUS_JOB_TMP", str(tmp_path))
    old = tmp_path / "alt0754_9.dir"
    old.mkdir()
    t = time.time() - 7200
    os.utime(old, (t, t))
    fresh = tmp_path / "alt0754_10.dir"
    fresh.mkdir()
    import toolchain
    toolchain._redirect_job_tmp()
    assert not old.exists() and fresh.exists()
    assert os.environ["TMPDIR"] == str(tmp_path)
