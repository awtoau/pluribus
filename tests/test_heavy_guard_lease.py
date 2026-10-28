"""heavy_guard.lease: shared GB budget admits jobs side by side up to the budget, never beyond."""
import logging
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import heavy_guard  # noqa: E402


def test_lease_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(heavy_guard, "LEASE_PATH", str(tmp_path / "leases"))
    monkeypatch.setattr(heavy_guard, "LEASE_LOG", str(tmp_path / "tele1.jsonl"))
    monkeypatch.setattr(heavy_guard, "available_gb", lambda: 1000.0)
    monkeypatch.setattr(heavy_guard, "POLL_S", 0.05)
    monkeypatch.setattr(heavy_guard, "LEASE_RAMP_S", 0.0)
    log = logging.getLogger("t")
    lock = threading.Lock()
    cur = [0.0]
    peak = [0.0]

    def job():
        with heavy_guard.lease(10, "t", log, budget_gb=25):
            with lock:
                cur[0] += 10
                peak[0] = max(peak[0], cur[0])
            x = sum(range(200000))  # hold the lease for a few ms of real work
            assert x >= 0
            with lock:
                cur[0] -= 10

    ts = [threading.Thread(target=job) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] <= 20.0      # budget 25 GB admits at most two 10 GB jobs
    assert peak[0] >= 10.0
    assert heavy_guard.lease_ledger() == {} or all(v["pid"] == os.getpid() for v in heavy_guard.lease_ledger().values())


def test_oversize_job_runs_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(heavy_guard, "LEASE_PATH", str(tmp_path / "leases2"))
    monkeypatch.setattr(heavy_guard, "LEASE_LOG", str(tmp_path / "tele2.jsonl"))
    monkeypatch.setattr(heavy_guard, "available_gb", lambda: 1000.0)
    monkeypatch.setattr(heavy_guard, "LEASE_RAMP_S", 0.0)
    ran = []
    with heavy_guard.lease(50, "big", logging.getLogger("t"), budget_gb=25):
        ran.append(1)
    assert ran == [1]


def test_waiting_burns_no_cpu_and_logs_telemetry(tmp_path, monkeypatch):
    monkeypatch.setattr(heavy_guard, "LEASE_PATH", str(tmp_path / "l3"))
    monkeypatch.setattr(heavy_guard, "LEASE_LOG", str(tmp_path / "tele.jsonl"))
    monkeypatch.setattr(heavy_guard, "available_gb", lambda: 1000.0)
    monkeypatch.setattr(heavy_guard, "LEASE_RAMP_S", 0.0)
    monkeypatch.setattr(heavy_guard, "POLL_S", 0.2)
    monkeypatch.setattr(heavy_guard, "BLOCKED_AFTER_S", 0.5)
    shed = []
    log = logging.getLogger("t")
    release = threading.Event()

    def holder():
        with heavy_guard.lease(20, "hold", log, budget_gb=25):
            release.wait(2.5)

    h = threading.Thread(target=holder)
    h.start()
    time.sleep(0.3)  # let the holder take the lease (test-only pacing)
    cpu0 = time.process_time()

    def waiter():
        with heavy_guard.lease(20, "wait", log, budget_gb=25, on_blocked=lambda: shed.append(1)):
            pass

    w = threading.Thread(target=waiter)
    w.start()
    time.sleep(1.5)
    cpu = time.process_time() - cpu0
    release.set()
    h.join()
    w.join()
    assert cpu < 0.5          # 1.5 s blocked: polling only, no spin
    assert shed == [1]        # shed memory once while blocked
    lines = open(tmp_path / "tele.jsonl").read().splitlines()
    assert len(lines) == 2 and '"name": "wait"' in "".join(lines)
