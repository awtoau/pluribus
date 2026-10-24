#!/usr/bin/env python3
"""Consolidated Cyclone V / Mistral verification harness.

Re-derives every Mistral-dependent claim this project makes about Cyclone V
from scratch, against whatever Quartus install is on this machine RIGHT NOW,
and checks the result against the numbers already documented in
docs/cyclonev-lifter-status.md / docs/cyclonev-dsp-fuzz-status.md -- not just
"did it run", but "does it still say what we published". Re-run this after a
Quartus upgrade (or with $PLURIBUS_QUARTUS_BIN pointed at an older install) to
confirm nothing drifted. See docs/cyclonev-verification.md.

Stages
------
1. Die probe   -- compile a trivial design for each of the 7 Mistral-covered
                  Cyclone V dies, record real .rbf sizes (reuses
                  cyclonev_die_probe.compile_die(), does not copy it).
2. DSP fuzz    -- compile + decompile the 4 known-operation DSP designs,
                  compare the recovered DSP.MODE string against the
                  documented expected value for each (reuses
                  cyclonev_dsp_fuzz.quartus_compile_design() /
                  decompile_and_extract_design(), split so Quartus compiles
                  and Mistral decompiles run in separate thread pools).
3. Lifter selftest -- parse_config()/recover_netlist() against the real
                  reference .bt sample, check LUT/FF/net/arc/pad counts
                  against the documented baseline (reuses
                  lifters.cyclonev_lift.CycloneVLift directly, same calls
                  scripts/cyclonev_lift_selftest.py makes).
4. pad_map DB insert -- load.py's load_cyclonev() into a throwaway SQLite
                  DB, check the real pad_map row count / direction
                  breakdown / duplicate-pin count against the selftest's own
                  ground truth (Part 1 of this session's task).
5. Lifted sim   -- BLOCKING functional gate: re-lift every corpus design, simulate
                  lifted Verilog vs Quartus build.vo (scripts/cyclonev_lifted_sim_check.py);
                  prints wrong/missing per design; any failing design fails the run.

Threading (stages 1-2 only; 3-4 are single-shot, not Quartus-bound)
--------------------------------------------------------------------
Producer/consumer, not a flat worker pool -- deliberately NOT "N threads
each doing compile-then-decompile for its own slice of work". The slow,
CPU-bound part is the Quartus compile sequence (quartus_map -> fit -> asm
-> cpf); the Mistral decompile + comparison step is much cheaper per item.
Collapsing them into one pool means a thread sits idle decompiling while
other cores could already be compiling the next design -- wasting the
parallelism Quartus compiles should get.

  - PRODUCER pool: min(20, os.cpu_count()) threads by default (this machine
    has 30 cores, but a prior run at the uncapped os.cpu_count() default
    crashed the IDE -- 30 concurrent Quartus processes with no memory
    awareness), each running one full Quartus compile sequence per work
    item (one die for stage 1, one DSP design for stage 2), pulling the
    next item off a shared queue.Queue the moment it finishes. A memory
    gate (--max-ram-pct, default 85%) additionally pauses new work being
    claimed whenever psutil.virtual_memory().percent is at or above that
    threshold, independent of thread count -- the real fix for the crash,
    since the worker-count cap alone doesn't bound actual RAM use (that
    varies per design/die).
  - CONSUMER pool: a small fixed pool (4 threads -- decompile + compare is
    seconds, not minutes, and gains nothing from wide parallelism),
    draining a second queue.Queue of completed compiles as they land.
  - Same threading.Thread + queue.Queue primitives reach.py already uses
    for its BFS workers (CountedLock is reach.py's own contention-counting
    lock wrapper; stage 1/2 have no shared mutable state between threads
    besides the two queues and a results list under a plain lock, so no
    lock contention worth instrumenting -- CountedLock is reused anyway for
    uniformity with the one other place this project threads work out).

Usage
-----
    python3.15t scripts/cyclonev_verify_all.py
    python3.15t scripts/cyclonev_verify_all.py --compile-workers 20 --max-ram-pct 85
    python3.15t scripts/cyclonev_verify_all.py --skip-die-probe --skip-dsp-fuzz  # fast re-check
    PLURIBUS_QUARTUS_BIN=/opt/altera/quartus-24.1/quartus/bin python3.15t scripts/cyclonev_verify_all.py
"""

import argparse
import logging
import os
import queue
import sys
import threading
import time
from pathlib import Path

import psutil

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import toolchain

import cyclonev_die_probe as die_probe
import cyclonev_dsp_fuzz as dsp_fuzz
from lifters.cyclonev_lift import CycloneVLift

LOG_PATH = REPO / "tmp" / "logs" / "cyclonev_verify_all.log"

# ── documented ground truth (docs/cyclonev-lifter-status.md,
#    docs/cyclonev-dsp-fuzz-status.md) -- a mismatch against these is the
#    actual point of this script, not just "did Quartus/Mistral crash". ──
EXPECTED_LIFTER = {
    "device": "5CEBA4U19C8", "die": "e50f",
    # Counts for REFERENCE_BT (corpus regbank16); lifter correctness is judged by the
    # Quartus oracle (docs/cyclonev-postfit-oracle.md), these only catch drift.
    "n_luts": 61, "n_ffs": 64, "n_nets": 139, "n_arcs": 608,
    "n_unparsed_lines": 0,
}
EXPECTED_PADMAP = {
    "n_pads_annotated": 19, "n_pads_unannotated": 0,
    "n_dup_pins": 0,
    "direction_breakdown": {"in": 15, "out": 4},
}
# DSP mode mapping (docs/cyclonev-dsp-fuzz-status.md): a design either gets
# an explicit MODE string, or (mult18x18/multacc18x18) NO MODE line at all
# because the chip's all-zero default IS that mode -- "none" is itself the
# documented, confirmed result for those two, not a missing measurement.
EXPECTED_DSP_MODE = {
    "mult9x9": "M9X9",
    "mult18x18": None,       # default encoding, no explicit MODE line (confirmed)
    "mult27x27": "M27X27",
    "multacc18x18": None,    # negative result: behaves identically to mult18x18
}
# Quartus-built corpus design (corpus/README.md); `cyclonev_corpus_build.py --only regbank16` makes it.
REFERENCE_BT = REPO / "corpus" / "cyclonev" / "regbank16" / "decomp.bt"


def setup_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cyclonev_verify_all")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_PATH)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


class CountedLock:
    """threading.Lock wrapper that counts acquisitions/contentions -- same
    class reach.py uses for its BFS worker pool, reused here rather than
    redefined for the one shared results list each pool appends to."""
    def __init__(self, name):
        self.name = name
        self._lock = threading.Lock()
        self.acquires = 0
        self.contentions = 0

    def __enter__(self):
        if not self._lock.acquire(blocking=False):
            self.contentions += 1
            self._lock.acquire()
        self.acquires += 1
        return self

    def __exit__(self, *_):
        self._lock.release()

    def stats(self):
        pct = (self.contentions / self.acquires * 100) if self.acquires else 0
        return f"{self.name}: {self.acquires} acq, {self.contentions} contended ({pct:.1f}%)"


# ── generic producer/consumer runner for stages 1 and 2 ────────────────────

_SENTINEL = object()  # marks "no more items will ever arrive" on produced_q


def run_producer_consumer(work_items, produce_fn, consume_fn,
                           n_producers, n_consumers, logger, stage_name,
                           max_ram_pct=85.0):
    """Run `produce_fn(item)` across a wide thread pool (the slow Quartus
    compile), feed whatever it returns into `consume_fn(result)` on a
    separate, smaller thread pool (the fast Mistral decompile + compare).

    MEMORY GATE (max_ram_pct, default 85%): a prior run with
    --compile-workers defaulted to os.cpu_count() (30 on this machine)
    crashed the IDE -- 30 concurrent quartus_map/fit/asm processes with no
    memory awareness, only a worker-COUNT cap, which doesn't bound actual
    RAM use (that varies per design). Each producer checks real system
    memory (psutil.virtual_memory().percent) before claiming its next work
    item and blocks (polling, not busy-waiting -- see the sleep below) while
    usage is above max_ram_pct, so the thread COUNT can stay high (good for
    CPU-bound Quartus compiles) while actual concurrent RAM use is capped
    independent of how many threads exist. This only throttles NEW work
    being claimed; an in-flight compile is never killed mid-run.

    Default is 85%, not 50% -- this host runs a permanently-resident ~16GB
    QEMU VM plus VSCode/Chrome, holding a ~50-58% RAM baseline before this
    script does anything. A 50% default is unreachable in steady state and
    stalls every producer indefinitely (confirmed: this exact bug, same
    gate pattern, hung scripts/cyclonev_db_import_routes.py for 20+ minutes
    with zero log output -- see that script's _wait_for_ram). The gate
    should bound THIS script's own usage, not reserve half the machine for
    processes that were never going to free it.

    A producer thread pulls its next item the moment it finishes its own --
    it never waits on that item's own decompile, which is the whole point:
    all `n_producers` threads should stay on Quartus continuously while the
    (fewer) consumer threads drain whatever has piled up. Mirrors reach.py's
    threading.Thread + queue.Queue worker-pool shape (that file's own
    docstring: "Workers pull nets from a shared queue").

    Termination: once `work_q` is fully drained, the LAST producer to finish
    pushes one _SENTINEL per consumer thread onto `produced_q` (a classic
    poison-pill shutdown) -- a consumer-side "stop once I've personally seen
    `total` items" counter is wrong here, since `total` only ever arrives
    once in aggregate across however many consumer threads are draining the
    SAME queue; earlier versions of this function hung for exactly that
    reason, each consumer waiting forever for items the other consumers had
    already taken.
    """
    if not work_items:
        logger.info("[%s] no work items, skipping", stage_name)
        return [], 0.0

    work_q = queue.Queue()
    for item in work_items:
        work_q.put(item)
    produced_q = queue.Queue()
    results = []
    results_lock = CountedLock(f"{stage_name}_results")
    error_event = threading.Event()
    n_done_produce = [0]
    n_done_consume = [0]
    total = len(work_items)
    work_q_lock = threading.Lock()
    remaining = [total]  # items not yet pulled off work_q by any producer

    def producer_worker():
        wait_start = None
        last_wait_log = 0.0
        while True:
            # Memory gate: poll every 2s while over budget rather than claim
            # work and risk the OOM/crash this gate exists to prevent. 2s is
            # ~1/10th of the fastest observed single quartus_map step this
            # session (~20s) -- frequent enough not to stall a ready slot for
            # long once RAM frees up, infrequent enough not to burn CPU on
            # psutil calls across up to `n_producers` polling threads at once.
            # Re-logs every 30s while waiting (not just silently polling) --
            # a gate stuck at an unreachable threshold must be visible in the
            # log as a stall, not indistinguishable from normal progress.
            while psutil.virtual_memory().percent >= max_ram_pct:
                if error_event.is_set():
                    return  # another thread already failed -- stop waiting
                now = time.time()
                if wait_start is None:
                    wait_start = now
                    logger.info("[%s] RAM at %.0f%% >= %.0f%% -- pausing new work",
                                stage_name, psutil.virtual_memory().percent, max_ram_pct)
                    last_wait_log = now
                elif now - last_wait_log >= 30.0:
                    logger.info("[%s] still waiting on RAM (%.0f%% >= %.0f%%) for %.0fs",
                                stage_name, psutil.virtual_memory().percent, max_ram_pct,
                                now - wait_start)
                    last_wait_log = now
                time.sleep(2)
            wait_start = None
            try:
                item = work_q.get(block=False)
            except queue.Empty:
                return
            try:
                t0 = time.time()
                produced = produce_fn(item)
                dt = time.time() - t0
                with results_lock:
                    n_done_produce[0] += 1
                    logger.info("[%s] compile %d/%d done in %.1fs",
                                stage_name, n_done_produce[0], total, dt)
                produced_q.put(produced)  # may be None -- consumer skips it
            except Exception as exc:
                error_event.set()
                logger.error("[%s] producer FATAL on %r: %s", stage_name, item, exc)
                produced_q.put(None)
            finally:
                work_q.task_done()
                with work_q_lock:
                    remaining[0] -= 1
                    if remaining[0] == 0:
                        # Every item has been produced (or failed) -- no more
                        # will ever land on produced_q. Wake every consumer.
                        for _ in range(n_consumers):
                            produced_q.put(_SENTINEL)

    def consumer_worker():
        while True:
            produced = produced_q.get(block=True)
            if produced is _SENTINEL:
                return
            if produced is None:
                continue
            try:
                result = consume_fn(produced)
                with results_lock:
                    n_done_consume[0] += 1
                    if result is not None:
                        results.append(result)
            except Exception as exc:
                error_event.set()
                logger.error("[%s] consumer FATAL on %r: %s", stage_name, produced, exc)

    producers = [threading.Thread(target=producer_worker, name=f"{stage_name}-p{i}",
                                   daemon=True)
                 for i in range(n_producers)]
    consumers = [threading.Thread(target=consumer_worker, name=f"{stage_name}-c{i}",
                                   daemon=True)
                 for i in range(n_consumers)]
    t0 = time.time()
    for t in producers + consumers:
        t.start()
    for t in producers:
        t.join()
    for t in consumers:
        t.join()
    dt = time.time() - t0
    logger.info("[%s] %s  (%d items, %d compile-workers, %d decompile-workers, %.1fs wall)",
                stage_name, results_lock.stats(), total, n_producers, n_consumers, dt)
    if error_event.is_set():
        logger.warning("[%s] one or more worker threads hit an exception -- see FATAL lines above",
                        stage_name)
    return results, dt


# ── stage 1: die probe ──────────────────────────────────────────────────────

def stage_die_probe(work_dir, n_producers, n_consumers, logger, max_ram_pct=85.0):
    items = list(die_probe.DIES.items())  # [(die_name, part), ...]

    def produce(item):
        die_name, part = item
        sigs = die_probe.compile_die(die_name, part, work_dir, logger)
        return (die_name, part, sigs)

    def consume(produced):
        die_name, part, sigs = produced
        return {"die": die_name, "part": part, "ok": bool(sigs), "sigs": sigs or []}

    results, dt = run_producer_consumer(items, produce, consume,
                                         n_producers, n_consumers, logger, "die_probe",
                                         max_ram_pct=max_ram_pct)
    n_ok = sum(1 for r in results if r["ok"])
    summary_line = f"Die probe: {n_ok}/{len(items)} dies compiled OK ({dt:.1f}s)"
    logger.info(summary_line)
    return {"pass": n_ok == len(items), "summary": summary_line, "results": results,
            "wall_s": dt}


# ── stage 2: DSP fuzz ────────────────────────────────────────────────────────

def stage_dsp_fuzz(work_dir, n_producers, n_consumers, logger, max_ram_pct=85.0):
    items = list(dsp_fuzz.DESIGNS.items())  # [(name, spec), ...]

    def produce(item):
        name, spec = item
        return dsp_fuzz.quartus_compile_design(name, spec, work_dir, logger)

    def consume(produced):
        return dsp_fuzz.decompile_and_extract_design(produced, logger)

    results, dt = run_producer_consumer(items, produce, consume,
                                         n_producers, n_consumers, logger, "dsp_fuzz",
                                         max_ram_pct=max_ram_pct)

    checks = []
    for name, expected_mode in EXPECTED_DSP_MODE.items():
        res = next((r for r in results if r["name"] == name), None)
        if res is None:
            checks.append((name, expected_mode, None, False))
            continue
        modes = dsp_fuzz.mode_values(res["dsp_settings"])
        got_mode = modes[0][2] if modes else None
        ok = (got_mode == expected_mode)
        checks.append((name, expected_mode, got_mode, ok))
        if ok:
            logger.info("DSP mode %s: previously %s, now: %s — OK",
                        name, expected_mode, got_mode)
        else:
            logger.error("DSP mode %s: previously %s, now: %s — MISMATCH, investigate",
                         name, expected_mode, got_mode)

    n_confirmed = sum(1 for *_, ok in checks if ok)
    n_designs_compiled = sum(1 for r in results if r and r.get("dsp_settings") is not None)
    summary_line = (f"DSP fuzz: {n_confirmed}/{len(checks)} modes confirmed "
                     f"({len(checks) - n_confirmed} mismatch/missing, "
                     f"{n_designs_compiled}/{len(items)} designs compiled) ({dt:.1f}s)")
    logger.info(summary_line)
    return {"pass": n_confirmed == len(checks), "summary": summary_line,
            "checks": checks, "wall_s": dt}


# ── stage 3: lifter selftest ────────────────────────────────────────────────

def stage_lifter_selftest(bt_path, logger):
    t0 = time.time()
    if not bt_path.is_file():
        summary_line = f"Lifter selftest: SKIPPED — reference .bt not found at {bt_path}"
        logger.warning(summary_line)
        return {"pass": False, "summary": summary_line}

    lift = CycloneVLift(EXPECTED_LIFTER["device"])
    pc = lift.parse_config(str(bt_path))
    d = lift.recover_netlist(pc)
    dt = time.time() - t0

    checks = {
        "n_luts": (len(d.luts), EXPECTED_LIFTER["n_luts"]),
        "n_ffs": (len(d.ffs), EXPECTED_LIFTER["n_ffs"]),
        "n_nets": (len(d.all_nets), EXPECTED_LIFTER["n_nets"]),
        "n_arcs": (d.n_arcs, EXPECTED_LIFTER["n_arcs"]),
        "n_unparsed_lines": (pc.n_unparsed_lines, EXPECTED_LIFTER["n_unparsed_lines"]),
    }
    mismatches = {k: v for k, v in checks.items() if v[0] != v[1]}
    for k, (got, exp) in checks.items():
        if got == exp:
            logger.info("Lifter selftest %s: previously %d, now: %d — OK", k, exp, got)
        else:
            logger.error("Lifter selftest %s: previously %d, now: %d — MISMATCH, investigate",
                         k, exp, got)

    ok = not mismatches
    summary_line = (f"Lifter selftest: {'PASS' if ok else 'FAIL'} "
                     f"({len(d.luts)} LUTs, {len(d.ffs)} FFs, {len(d.all_nets)} nets, "
                     f"{d.n_arcs} arcs, {len(mismatches)} mismatches) ({dt:.1f}s)")
    logger.info(summary_line)
    return {"pass": ok, "summary": summary_line, "design": d, "mismatches": mismatches,
            "wall_s": dt}


# ── stage 4: pad_map DB insert check (Part 1 of this session's task) ───────

def stage_padmap_check(bt_path, logger):
    """Load the reference .bt through load.py's load_cyclonev() path (as a
    real subprocess, same way the pipeline is always invoked -- see
    CLAUDE.md's stage list -- rather than importing load.py/db.py into this
    process, which already imported `db` with whatever PLURIBUS_SQLITE_PATH
    was set at process start; db.py caches its engine the first time it's
    touched, so an in-process env var change after that point would not
    take effect), then check the real pad_map rows against the selftest's
    own documented ground truth (Part 1 of this session's task). Only
    depends on the .bt file, not on stage 3's in-memory Design object --
    runs independently of whether the lifter-selftest stage ran.
    """
    import json
    import sqlite3
    import subprocess as sp
    from collections import Counter

    t0 = time.time()
    if not bt_path.is_file():
        summary_line = f"Pad map: SKIPPED — reference .bt not found at {bt_path}"
        logger.warning(summary_line)
        return {"pass": False, "summary": summary_line}

    db_path = REPO / "tmp" / "cyclonev_verify_all_padmap.db"
    if db_path.exists():
        db_path.unlink()  # always-rebuild convention; start clean each run
    env = dict(os.environ, PLURIBUS_SQLITE_PATH=str(db_path))
    proc = sp.run(
        [sys.executable, str(REPO / "load.py"), "--lifter", "cyclonev",
         "--label", "CYCLONEV_VERIFY_ALL", "--config", str(bt_path),
         "--device", EXPECTED_LIFTER["device"]],
        cwd=str(REPO), env=env, capture_output=True, text=True,
    )
    for line in proc.stdout.splitlines():
        logger.info("[load.py] %s", line)
    if proc.returncode != 0:
        for line in proc.stderr.splitlines()[-20:]:
            logger.error("[load.py] %s", line)
        summary_line = f"Pad map: FAIL — load.py exited {proc.returncode}"
        logger.error(summary_line)
        return {"pass": False, "summary": summary_line}

    conn = sqlite3.connect(str(db_path))
    bs_id = conn.execute(
        "SELECT id FROM bitstreams WHERE label=?", ("CYCLONEV_VERIFY_ALL",)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT pin, direction FROM pad_map WHERE bitstream=?", (bs_id,)
    ).fetchall()
    conn.close()
    n_pads = len(rows)
    pins = [r[0] for r in rows]
    n_dup = len(pins) - len(set(pins))
    dir_breakdown = dict(Counter(r[1] for r in rows))
    dt = time.time() - t0

    checks = {
        "n_pads_annotated": (n_pads, EXPECTED_PADMAP["n_pads_annotated"]),
        "n_dup_pins": (n_dup, EXPECTED_PADMAP["n_dup_pins"]),
    }
    mismatches = {k: v for k, v in checks.items() if v[0] != v[1]}
    for k, (got, exp) in checks.items():
        if got == exp:
            logger.info("Pad map %s: previously %d, now: %d — OK", k, exp, got)
        else:
            logger.error("Pad map %s: previously %d, now: %d — MISMATCH, investigate",
                         k, exp, got)
    logger.info("Pad map direction breakdown (annotated subset): %s", dir_breakdown)

    ok = not mismatches
    summary_line = (f"Pad map: {n_pads}/{EXPECTED_PADMAP['n_pads_annotated']} pins, "
                     f"{n_dup} duplicates ({'PASS' if ok else 'FAIL'}) ({dt:.1f}s)")
    logger.info(summary_line)
    return {"pass": ok, "summary": summary_line, "mismatches": mismatches, "wall_s": dt}


# ── stage 5: lifted Verilog functional sim (blocking) ──────────────────────

def stage_lifted_sim(logger, jobs):
    """Re-lift every corpus design and simulate it against Quartus build.vo
    (scripts/cyclonev_lifted_sim_check.py).  Any covered design with a wrong or
    missing output sample, or a failed model check, fails the run."""
    import cyclonev_lifted_sim_check as simcheck
    t0 = time.time()
    results = simcheck.run_guarded(simcheck.all_designs(), jobs=jobs, logf=logger.info)
    ok = simcheck.summary(results, logf=logger.info)
    for r in results:
        if r["status"] in ("FAIL", "ERROR"):
            logger.error("lifted sim %s %s: wrong=%d missing=%d %s", r["status"], r["design"],
                         r["wrong"], r["missing"], r["reason"])
    n = {s: sum(1 for r in results if r["status"] == s)
         for s in ("PASS", "FAIL", "ERROR", "NOT_COVERED", "NOT_BUILT")}
    summary_line = (f"Lifted sim: {'PASS' if ok else 'FAIL'} — {n['PASS']} pass, {n['FAIL']} fail, "
                    f"{n['ERROR']} error, {n['NOT_COVERED']} not covered, {n['NOT_BUILT']} not built "
                    f"({time.time() - t0:.1f}s)")
    logger.info(summary_line)
    return {"pass": ok, "summary": summary_line, "results": results}


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    # Default capped below os.cpu_count() (30 on this machine): a prior run
    # at the uncapped default crashed the IDE. The real safety net is
    # --max-ram-pct (the memory gate in run_producer_consumer), but a lower
    # worker-count default also means fewer Quartus processes launched
    # before that gate has data to act on, so both matter.
    ap.add_argument("--compile-workers", type=int,
                     default=min(20, os.cpu_count() or 20),
                     help="producer pool size for Quartus compiles "
                          "(default: min(20, os.cpu_count()))")
    ap.add_argument("--decompile-workers", type=int, default=4,
                     help="consumer pool size for mistral-cv decompile + compare (default: 4)")
    ap.add_argument("--max-ram-pct", type=float, default=85.0,
                     help="pause claiming new compile work while system RAM use is at or "
                          "above this percent (psutil.virtual_memory().percent); does not "
                          "kill in-flight work (default: 85.0 -- see run_producer_consumer's "
                          "docstring for why 50 stalls indefinitely on this host)")
    ap.add_argument("--reference-bt", type=Path, default=REFERENCE_BT,
                     help="pre-decompiled reference .bt for stages 3/4 "
                          "(default: %(default)s)")
    ap.add_argument("--skip-die-probe", action="store_true")
    ap.add_argument("--skip-dsp-fuzz", action="store_true")
    ap.add_argument("--skip-lifter-selftest", action="store_true")
    ap.add_argument("--skip-padmap", action="store_true")
    ap.add_argument("--skip-lifted-sim", action="store_true",
                     help="skip the blocking lifted-vs-Quartus functional sim (stage 5)")
    ap.add_argument("--sim-jobs", type=int, default=4)
    ap.add_argument("--work-dir", type=Path, default=REPO / "tmp" / "cyclonev_verify_all")
    args = ap.parse_args()

    logger = setup_logging()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    nogil = not sys._is_gil_enabled()
    logger.info("NoGIL: %s  (compile_workers=%d, decompile_workers=%d, max_ram_pct=%.1f, "
                "system RAM now=%.1f%%)",
                nogil, args.compile_workers, args.decompile_workers, args.max_ram_pct,
                psutil.virtual_memory().percent)
    if not nogil:
        logger.warning("GIL is ENABLED — this interpreter is not the free-threaded "
                        "build (python3.15t); the producer/consumer pools will still "
                        "run but without the NoGIL throughput this harness assumes.")

    logger.info("Quartus: %s  (toolchain=%s)", die_probe.QUARTUS_BIN, die_probe.TOOLCHAIN)
    logger.info("mistral-cv: %s", toolchain.mistral_cv(required=False))

    stage_results = {}

    if not args.skip_die_probe:
        stage_results["die_probe"] = stage_die_probe(
            args.work_dir / "die_probe", args.compile_workers, args.decompile_workers,
            logger, max_ram_pct=args.max_ram_pct)
    else:
        logger.info("Die probe: SKIPPED (--skip-die-probe)")

    if not args.skip_dsp_fuzz:
        stage_results["dsp_fuzz"] = stage_dsp_fuzz(
            args.work_dir / "dsp_fuzz", args.compile_workers, args.decompile_workers,
            logger, max_ram_pct=args.max_ram_pct)
    else:
        logger.info("DSP fuzz: SKIPPED (--skip-dsp-fuzz)")

    if not args.skip_lifter_selftest:
        stage_results["lifter_selftest"] = stage_lifter_selftest(args.reference_bt, logger)
    else:
        logger.info("Lifter selftest: SKIPPED (--skip-lifter-selftest)")

    if not args.skip_padmap:
        stage_results["padmap"] = stage_padmap_check(args.reference_bt, logger)
    else:
        logger.info("Pad map: SKIPPED (--skip-padmap)")

    if not args.skip_lifted_sim:
        stage_results["lifted_sim"] = stage_lifted_sim(logger, args.sim_jobs)
    else:
        logger.info("Lifted sim: SKIPPED (--skip-lifted-sim)")

    logger.info("=" * 72)
    logger.info("COMBINED SUMMARY")
    all_pass = True
    for name, res in stage_results.items():
        logger.info("  %s", res["summary"])
        all_pass = all_pass and res["pass"]
    logger.info("OVERALL %s", "PASS" if all_pass else "FAIL")
    logger.info("Log: %s", LOG_PATH)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
