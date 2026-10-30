#!/usr/bin/env python3.15t
"""Cyclone IV GX (EP4CGX150) corpus: generate designs, build each with Quartus
(map/fit/asm/eda/cpf), keep the post-fit .vo (oracle) and the uncompressed .rbf.

Per design corpus/cycloneiv/<name>/ (only src/ + design.toml tracked):
  quartus/ (project), postfit.vo, bitstream.rbf, build.pin, fit.rpt, logs/<step>.log

  python3.15t scripts/cycloneiv_fuzz.py --generate            # write design dirs
  python3.15t scripts/cycloneiv_fuzz.py --build [--match 'gx150_ffc_*'] [--force]
Log: tmp/logs/cycloneiv_fuzz.log
"""
import argparse
import fnmatch
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor

import psutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus" / "cycloneiv"
# Quartus scratch (alt0754_* dirs) goes on disk, not /tmp tmpfs: a wide sweep's litter blew the
# /tmp user quota (2026-10-28). build_one reaps entries idle >30 min (live chains touch theirs).
QTMP = REPO / "tmp" / "quartus_tmp"
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

DEVICE = "EP4CGX150DF31C7"
FAMILY = "Cyclone IV GX"
KEEP = {"src", "design.toml"}
# Host-process guard: stall = 60 s silent; overall = 3x the worst of 300 gx150_sp builds (2026-10-26, 4 jobs, #165).
STALL_S = 60
CPU_POLL_S = 5        # CPU-progress sample interval for the stall check
OVERALL_S = {"quartus_map": 37, "quartus_fit": 95, "quartus_asm": 12, "quartus_eda": 7,
             "quartus_cpf": 3, "quartus_cdb": 6}
MAX_JOBS = 2          # Quartus processes at once (shared box; coordinator cap after the 2026-10-26 OOM, #124)
JOB_MIN_GB = 20       # available RAM before a job starts (#122)
log = logging.getLogger("cycloneiv_fuzz")
# Per-thread overrides so a rebuild can target another tree with its own scratch dir (cycloneiv_rebuild_all.py).
_tl = threading.local()


def corpus_root():
    return getattr(_tl, "corpus", CORPUS)


def qtmp_root():
    return getattr(_tl, "qtmp", QTMP)

def specs():
    """EP4CGX150 designs: random spread / race-free gate corpus, register-control, IO (cycloneiv_rnd_designs, cycloneiv_knobs)."""
    import cycloneiv_knobs
    import cycloneiv_rnd_designs
    out = {}
    out.update(cycloneiv_rnd_designs.gx_specs())
    out.update(cycloneiv_knobs.ffc_specs())
    out.update(cycloneiv_knobs.io_specs())
    return out


def toml_list(xs):
    return "[" + ", ".join('"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"' for x in xs) + "]"


def family_of(device):
    return FAMILY


def generate():
    for name, s in specs().items():
        d = CORPUS / name
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / "src" / "top.v").write_text(s["verilog"])
        (d / "design.toml").write_text(
            f'top = "{s["top"]}"\npurpose = "{s["purpose"]}"\nexercises = {toml_list(s["exercises"])}\n'
            f"qsf = {toml_list(s['qsf'])}\n"
            + (f'device = "{s["device"]}"\n' if "device" in s else ""))
    log.info("generated %d designs", len(specs()))


def run(step, cmd, cwd, logdir, limits=OVERALL_S):
    overall = limits[step]
    logdir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    qt = qtmp_root()
    qt.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace",
                            env=dict(os.environ, TMPDIR=str(qt)))
    lines = queue.Queue()

    def pump():
        for ln in proc.stdout:
            lines.put(ln)
        lines.put(None)
    threading.Thread(target=pump, daemon=True).start()
    last = ""
    ps = psutil.Process(proc.pid)
    cpu_last, progress_t = -1.0, time.monotonic()
    with open(logdir / f"{step}.log", "w") as fh:
        while True:
            now = time.monotonic()
            left = overall - (now - t0)
            try:
                ln = lines.get(timeout=max(0.1, min(CPU_POLL_S, left)))
                progress_t = time.monotonic()
            except queue.Empty:
                # stall = no output AND no CPU-time growth for STALL_S (the router runs silent)
                try:
                    c = sum(ps.cpu_times()[:2])
                except psutil.NoSuchProcess:
                    c = cpu_last
                if c > cpu_last:
                    cpu_last, progress_t = c, time.monotonic()
                stalled = time.monotonic() - progress_t >= STALL_S
                if left > 0 and not stalled:
                    continue
                proc.kill()
                proc.wait()
                why = f"OVERALL {overall}s" if left <= 0 else f"STALL {STALL_S}s without output or CPU"
                log.error("[%s] killed: %s, elapsed %.1fs, loadavg %s, last: %r", step, why,
                          time.monotonic() - t0, os.getloadavg(), last.strip())
                return False
            if ln is None:
                break
            fh.write(ln)
            last = ln
    rc = proc.wait()
    el = time.monotonic() - t0
    if rc:
        log.error("[%s] rc=%d after %.1fs, last: %r", step, rc, el, last.strip())
        return False
    log.info("[%s] ok %.1fs", step, el)
    return True


def reap_qtmp():
    """Remove Quartus scratch idle >30 min (a live chain touches its dir continuously)."""
    if not QTMP.is_dir():
        return
    cutoff = time.time() - 1800
    for p in QTMP.iterdir():
        try:
            if p.lstat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        except OSError:
            pass


def build_one(name):
    reap_qtmp()
    d = corpus_root() / name
    spec = tomllib.loads((d / "design.toml").read_text())
    for p in d.iterdir():
        if p.name not in KEEP:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    q = d / "quartus"
    q.mkdir()
    dev = spec.get("device", DEVICE)
    lines = [f'set_global_assignment -name FAMILY "{family_of(dev)}"', f"set_global_assignment -name DEVICE {dev}",
             f"set_global_assignment -name TOP_LEVEL_ENTITY {spec['top']}",
             "set_global_assignment -name VERILOG_FILE ../src/top.v",
             'set_global_assignment -name EDA_SIMULATION_TOOL "QuestaSim (Verilog)"',
             'set_global_assignment -name EDA_OUTPUT_DATA_FORMAT "VERILOG HDL" -section_id eda_simulation',
             'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
             # one thread per chain: fit spawned 32-47 threads per process (load ~100 on 30 cores, 17% sys); chains are the parallelism
             "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1",
             *spec.get("qsf", [])]
    (q / "build.qsf").write_text("\n".join(lines) + "\n")
    (q / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = Path(toolchain.quartus_bin())
    limits = OVERALL_S
    steps = [("quartus_map", [qb / "quartus_map", "build"]), ("quartus_fit", [qb / "quartus_fit", "build"]),
             ("quartus_asm", [qb / "quartus_asm", "build"]),
             ("quartus_eda", [qb / "quartus_eda", "build", "--simulation", "--tool=modelsim", "--format=verilog"]),
             ("quartus_cpf", [qb / "quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    for step, cmd in steps:
        if not run(step, cmd, q, d / "logs", limits):
            return step
    if not rcf_export(q, d, qb, limits):
        return "quartus_cdb"
    vo = next((q / "simulation").rglob("*.vo"))
    for src, dst in ((vo, "postfit.vo"), (q / "build.rbf", "bitstream.rbf"), (q / "build.pin", "build.pin"),
                     (q / "build.fit.rpt", "fit.rpt")):
        shutil.copyfile(src, d / dst)
    (q / "build.sof").unlink()
    return None


def rcf_export(q, d, qb, limits):
    """Full routing of every net -> <design>/routing.rcf.  quartus_cdb rewrites build.qsf even with
    --write_settings_files=off, so the .qsf is restored afterwards."""
    keep = (q / "build.qsf").read_bytes()
    ok = run("quartus_cdb", [qb / "quartus_cdb", "build", "-c", "build", "--back_annotate=routing",
                             "--write_settings_files=off"], q, d / "logs", limits)
    (q / "build.qsf").write_bytes(keep)
    if ok:
        shutil.copyfile(q / "build.rcf", d / "routing.rcf")
    return ok


def rcf_only(name):
    """RCF for a design built before the RCF step existed: export from a scratch copy of its
    project (the build may be a symlink into another checkout; nothing is written there)."""
    d = CORPUS / name
    work = REPO / "tmp" / "cycloneiv" / "rcf_work" / name
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree((d / "quartus").resolve(), work, ignore=shutil.ignore_patterns("*.rbf", "*.sof"))
    try:
        ok = rcf_export(work, d, Path(toolchain.quartus_bin()), OVERALL_S)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return None if ok else "quartus_cdb"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--match", default="*")
    ap.add_argument("--force", action="store_true", help="rebuild designs that already have bitstream.rbf")
    ap.add_argument("--rcf-only", action="store_true", help="export routing.rcf for built designs lacking it")
    ap.add_argument("--jobs", type=int, default=1, help=f"parallel Quartus builds (max {MAX_JOBS})")
    a = ap.parse_args()
    a.jobs = max(1, min(a.jobs, MAX_JOBS))
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_fuzz.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    if a.generate:
        generate()
    if a.build or a.rcf_only:
        if a.rcf_only:
            names = sorted(p.name for p in CORPUS.iterdir() if (p / "bitstream.rbf").exists()
                           and fnmatch.fnmatch(p.name, a.match) and not (p / "routing.rcf").exists())
            fn = rcf_only
        else:
            names = sorted(p.name for p in CORPUS.iterdir() if (p / "design.toml").exists()
                           and fnmatch.fnmatch(p.name, a.match)
                           and (a.force or not (p / "bitstream.rbf").exists()))
            fn = build_one
        log.info("%d designs to process, %d jobs", len(names), a.jobs)
        bad = {}

        def one(n):
            heavy_guard.wait_available(log, n, JOB_MIN_GB)
            t0 = time.monotonic()
            f = fn(n)
            log.info("%s: %s (%.1fs)", n, "ok" if f is None else f"FAIL at {f}", time.monotonic() - t0)
            if f:
                bad[n] = f
        with heavy_guard.heavy_lock("cycloneiv_fuzz", log):
            with ThreadPoolExecutor(a.jobs) as ex:
                list(ex.map(one, names))
        log.info("done %d, failed %d %s", len(names) - len(bad), len(bad), bad)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
