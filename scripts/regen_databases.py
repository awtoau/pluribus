#!/usr/bin/env python3.15t
"""Regenerate the kept databases into the per-family layout (databases/<family>/<name>.db).

  python3.15t scripts/regen_databases.py --list              # jobs, inputs present?, estimates
  python3.15t scripts/regen_databases.py --dry-run --all     # commands only
  python3.15t scripts/regen_databases.py --run fnirsi cyclonev-padmap
  python3.15t scripts/regen_databases.py --all               # every runnable job, cheap first (overnight)

Per job: inputs checked, MemAvailable >= 20 GB (project rule), heavy_guard.lease(est_gb) held for the
build, child stages stall-guarded (no output/CPU for STALL_S = hung) with an overall limit of 3x the
estimate, stdout+stderr to tmp/logs/regen_<job>.log, progress JSON in tmp/regen_databases/<job>.json.
The whole batch holds heavy_guard.heavy_lock (+ cgroup scope) like the other batch drivers. On success
the superseded flat file (+ -shm/-wal) moves to /mnt/2tb/wastebasket/pluribus-regen-<ts>/ (never rm).
Private-project inputs are READ only (paths come from the board.toml / --input, never from here).
Not regenerated: the parked private lift (archive, imported instead: docs/legacy-import.md) and dji_g.db
(producer unknown). Log: tmp/logs/regen_databases.log
"""
import argparse
import datetime
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard   # noqa: E402

log = logging.getLogger("regen_databases")
PY = sys.executable
DBS = REPO / "databases"
STATE = REPO / "tmp" / "regen_databases"
STALL_S = 300          # longest silent child phase ~60 s (reach2 ff_cones on 2.6 M rows), 5x
MIN_FREE_GB = 20       # project rule for heavy steps
WASTE = Path("/mnt/2tb/wastebasket")


def board_bin(board, label):
    import tomllib
    t = tomllib.loads((REPO / "boards" / board / "board.toml").read_text())
    rel = t.get("bitstreams", {}).get(label, {}).get("bin")
    return (REPO / "boards" / board / rel).resolve() if rel else None


# job -> how to rebuild it. est_min/est_gb: measured walls (docs/rust-candidates.md: reach+reach2 on
# V02 ~65 s, fnirsi ~40 s; load.py per fuzz target ~2 s; MachXO2 lift ~1 s) with the rest of the
# pipeline (reach3/4, report, verilog, verify) folded in; est_gb = reach2 peak 2.1 GB + margin.
JOBS = {
    "cyclonev-padmap": dict(
        family="cyclonev", target="cyclonev/verify_all_padmap.db", old=["cyclonev_verify_all_padmap.db", "cyclonev_merge_verify.db"],
        cmd=[PY, "scripts/cyclonev_verify_all.py", "--skip-die-probe", "--skip-dsp-fuzz", "--skip-lifted-sim"],
        produces=REPO / "tmp" / "cyclonev_verify_all_padmap.db", inputs=[], est_min=15, est_gb=3,
        note="lifter selftest + pad_map into a fresh DB (no Quartus stages); cyclonev_merge_verify.db had identical counts"),
    "fnirsi": dict(
        family="gowin", target="gowin/fnirsi.db", old=["fnirsi.db"],
        cmd=[PY, "scripts/run_pipeline.py", "--board", "boards/fnirsi-gw1n2", "--label", "FNIRSI", "--workers", "8"],
        env_target=True, inputs=[board_bin("fnirsi-gw1n2", "FNIRSI")], est_min=20, est_gb=3,
        note="Gowin unpack + load + reach..reach4 + report/verilog"),
    "fuzz_rebuild": dict(
        family="machxo2", target="machxo2/fuzz_rebuild.db", old=["fuzz_rebuild.db"],
        python="fuzz_loads", inputs=[REPO / "corpus/machxo2/diamond-fuzz"], est_min=120, est_gb=2,
        note="load.py per corpus/machxo2/diamond-fuzz/<t>/decoded.config (2,779 targets, label FUZZ_<t>); no Diamond"),
    "aw2-v02": dict(
        family="machxo2", target="machxo2/aw2-v02.db", old=["aw2.db"],
        cmd=[PY, "scripts/run_pipeline.py", "--board", "boards/aw2-2d82auto", "--label", "V02", "--workers", "8"],
        env_target=True, inputs=[board_bin("aw2-2d82auto", "V02")], est_min=180, est_gb=3,
        note="private-project V02 lift; bitstream read-only from the board.toml path"),
    "repl": dict(
        family="machxo2", target="machxo2/repl.db", old=["repl.db"],
        cmd=[PY, "scripts/machxo2_roundtrip.py"], produces=REPO / "tmp" / "repl.db", inputs=[], est_min=40, est_gb=3,
        note="known-source replacement scope: nextpnr-machxo2 + native unpack + load (needs the open flow + the private RTL)"),
    "dji_g": dict(family="cyclonev", target=None, old=["dji_g.db"], manual="producer unknown (bitstreams.device = 5CEBA4U19C8; not the EP4CGX150 image the old README claimed)",
                  inputs=[], est_min=0, est_gb=0),
}


def mem_available_gb():
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1]) / 1e6
    return 0.0


def inputs_ok(job):
    missing = [str(p) for p in job["inputs"] if p is None or not Path(p).exists()]
    return missing


def write_state(name, **kw):
    STATE.mkdir(parents=True, exist_ok=True)
    p = STATE / f"{name}.json"
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur.update(kw)
    p.write_text(json.dumps(cur, indent=1, default=str))


def fuzz_loads(target_db, jlog):
    """Load every diamond-fuzz target's decoded.config into target_db (label FUZZ_<t>)."""
    sys.path.insert(0, str(REPO / "diamond-fuzz" / "scripts"))
    import run_all_fuzz as RAF
    os.environ["PLURIBUS_SQLITE_PATH"] = str(target_db)
    root = REPO / "corpus/machxo2/diamond-fuzz"
    targets = sorted(p for p in root.iterdir() if (p / "decoded.config").exists())
    ok = fail = 0
    t0 = time.time()
    for i, t in enumerate(targets, 1):
        good, msg = RAF.load_fuzz_config(t.name, t / "decoded.config")
        ok += bool(good)
        fail += not good
        if not good:
            jlog.write(f"FAIL {t.name}: {msg[-300:]}\n")
        if i % 50 == 0 or i == len(targets):
            line = f"{i}/{len(targets)} loaded ok={ok} fail={fail} {time.time() - t0:.0f}s"
            jlog.write(line + "\n")
            jlog.flush()
            log.info("fuzz_rebuild: %s", line)
    return 0 if fail == 0 else 1


def run_job(name, dry):
    job = JOBS[name]
    if job.get("manual"):
        log.info("%s: MANUAL — %s", name, job["manual"])
        return "manual"
    missing = inputs_ok(job)
    if missing:
        log.error("%s: inputs missing: %s", name, missing)
        write_state(name, status="inputs-missing", missing=missing)
        return "inputs-missing"
    target = DBS / job["target"]
    cmd = job.get("cmd")
    if dry:
        log.info("%s: would run %s -> %s (est %d min, lease %d GB)", name, " ".join(map(str, cmd)) if cmd else job["python"],
                 target, job["est_min"], job["est_gb"])
        return "dry"
    free = mem_available_gb()
    if free < MIN_FREE_GB:
        log.error("%s: MemAvailable %.1f GB < %d GB: not starting", name, free, MIN_FREE_GB)
        write_state(name, status="low-memory", free_gb=free)
        return "low-memory"
    target.parent.mkdir(parents=True, exist_ok=True)
    work = target.with_suffix(".db.building")
    for suf in ("", "-shm", "-wal"):
        p = Path(str(work) + suf)
        if p.exists():
            p.unlink()
    jlog_path = REPO / "tmp" / "logs" / f"regen_{name}.log"
    write_state(name, status="running", started=datetime.datetime.now().astimezone().isoformat(timespec="seconds"), target=str(target))
    t0 = time.time()
    rc = -1
    with heavy_guard.lease(job["est_gb"], f"regen_{name}", log), open(jlog_path, "a") as jlog:
        jlog.write(f"=== {datetime.datetime.now().astimezone().isoformat(timespec='seconds')} {name} -> {target}\n")
        if job.get("python") == "fuzz_loads":
            rc = fuzz_loads(work, jlog)
        else:
            env = dict(os.environ)
            if job.get("env_target"):
                env["PLURIBUS_SQLITE_PATH"] = str(work)
            r = heavy_guard.run_stall_guarded(cmd, f"regen_{name}", log, stall_s=STALL_S, overall_s=3 * job["est_min"] * 60,
                                              env=env, cwd=str(REPO))
            jlog.write((r.stdout or "") + "\n--- stderr ---\n" + (r.stderr or "") + "\n")
            rc = r.returncode
            if rc == 0 and job.get("produces"):
                shutil.copy2(job["produces"], work)
    wall = time.time() - t0
    if rc != 0 or not work.exists():
        log.error("%s: FAILED rc=%s after %.0f s — see %s", name, rc, wall, jlog_path)
        write_state(name, status="failed", rc=rc, wall_s=wall, log=str(jlog_path))
        return "failed"
    for suf in ("", "-shm", "-wal"):
        p = Path(str(target) + suf)
        if p.exists():
            p.unlink()
    os.replace(work, target)
    for suf in ("-shm", "-wal"):
        p = Path(str(work) + suf)
        if p.exists():
            p.unlink()
    moved = retire_old(job["old"])
    log.info("%s: OK %.0f s -> %s (%.1f MB); old files -> %s", name, wall, target, target.stat().st_size / 1e6, moved)
    write_state(name, status="ok", rc=0, wall_s=wall, size_mb=target.stat().st_size / 1e6, old_moved=moved)
    return "ok"


def retire_old(names):
    """Superseded flat files -> the machine-wide wastebasket (never rm)."""
    moved = []
    dest = None
    for n in names:
        for suf in ("", "-shm", "-wal"):
            p = DBS / (n + suf)
            if p.exists():
                if dest is None:
                    dest = WASTE / f"pluribus-regen-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
                    dest.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dest / p.name))
                moved.append(str(dest / p.name))
    return moved


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/regen_databases.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run", nargs="*", default=None)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    order = sorted(JOBS, key=lambda n: JOBS[n]["est_min"])
    if a.list or not (a.run or a.all):
        print(f"{'job':16s} {'family':9s} {'target':34s} {'est min':>7s} {'GB':>3s}  inputs / note")
        for n in order:
            j = JOBS[n]
            miss = inputs_ok(j) if not j.get("manual") else []
            st = (STATE / f"{n}.json")
            last = json.loads(st.read_text()).get("status") if st.exists() else "-"
            print(f"{n:16s} {j['family']:9s} {str(j['target']):34s} {j['est_min']:7d} {j['est_gb']:3d}  "
                  f"{'MANUAL: ' + j['manual'] if j.get('manual') else ('inputs ok' if not miss else 'MISSING ' + str(miss))}  [last: {last}]")
        return 0
    names = order if a.all else a.run
    results = {}
    if a.dry_run:
        for n in names:
            results[n] = run_job(n, True)
        return 0
    with heavy_guard.heavy_lock("regen_databases", log):
        for n in names:
            results[n] = run_job(n, False)
    log.info("regen summary: %s", results)
    return 0 if all(v in ("ok", "manual") for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
