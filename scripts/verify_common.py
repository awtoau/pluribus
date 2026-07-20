#!/usr/bin/env python3
"""Shared verification utilities for Pluribus round-trip / LEC harnesses.

Imported by:
  scripts/machxo2_roundtrip.py  — SATBoundedSweep, default_sat_jobs
  scripts/gowin_lec.py          — is_2to1_mux, run_cmd
  scripts/gowin_fuzz.py         — is_2to1_mux, classify_fn, run_cmd
  scripts/anlogic_roundtrip.py  — run_cmd, is_2to1_mux, classify_fn

Issue #76: de-duplicate the three bespoke harnesses and provide a reusable
parallel SAT sweep (from machxo2 issue #72) so improvements transfer
automatically across families.
"""
import itertools
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from load import classify_lut  # noqa: E402


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def run_cmd(cmd, cwd, oss_bin=None, env=None, log=None, full_env=False):
    """Run a command; return ``(returncode, combined_output)``.

    If *oss_bin* is given it is prepended to PATH in the child environment.
    If *full_env* is True, *env* is used verbatim; otherwise it is merged
    over ``os.environ``.  *log* is a writable file-like object; the full
    command + output is appended there if provided.
    """
    e = env if full_env else {**os.environ, **(env or {})}
    if oss_bin and not full_env:
        e = {**e, "PATH": str(oss_bin) + os.pathsep + e.get("PATH", "")}
    r = subprocess.run(
        cmd, cwd=str(cwd), env=e,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = r.stdout or ""
    if log is not None:
        log.write(f"\n$ {' '.join(str(c) for c in cmd)}\n{out}")
    return r.returncode, out


# ---------------------------------------------------------------------------
# LUT classification helpers  (de-duped from gowin_lec + gowin_fuzz)
# ---------------------------------------------------------------------------

def is_2to1_mux(init: str) -> bool:
    """True iff the 16-bit LUT truth-table is a 2:1 mux for *some* wiring.

    ``classify_lut()`` only tries 3 of the 6 possible (sel, d0, d1) input
    orderings, so a mux with swapped data inputs falls into COMBO3 instead of
    MUX.  This exhaustively checks all six orderings — the honest answer to
    "is this a mux?" for a round-trip LEC.
    """
    v = int(init, 2)
    # active inputs: positions whose value actually affects some output bit
    act = [pos for pos in range(4)
           if any(((v >> p) & 1) != ((v >> (p ^ (1 << pos))) & 1)
                  for p in range(16))]
    if len(act) != 3:
        return False
    for sel in act:
        d = [p for p in act if p != sel]
        for i0, i1 in ((d[0], d[1]), (d[1], d[0])):
            good = True
            for bits in itertools.product((0, 1), repeat=3):
                a = dict(zip(act, bits))
                p = sum(a[pos] << pos for pos in act)
                if ((v >> p) & 1) != (a[i1] if a[sel] else a[i0]):
                    good = False
                    break
            if good:
                return True
    return False


def classify_fn(init16: str) -> str:
    """Top-level LUT function name, resolving the MUX case that
    ``classify_lut()`` under-reports as COMBO3."""
    head = re.match(r"[A-Z0-9]+", classify_lut(init16)).group(0)
    if head.startswith("COMBO") and is_2to1_mux(init16):
        return "MUX"
    return head


# ---------------------------------------------------------------------------
# Memory-aware SAT job limit
# ---------------------------------------------------------------------------

def default_sat_jobs() -> int:
    """Max concurrent SAT probes, bound by both core count and available RAM.

    A deep bounded-miter probe on the scope_top design peaks ~3–4.5 GB RSS.
    On a 32-core / 62 GB box the memory budget is the binding constraint
    (32 concurrent deep probes would want ~115 GB and swap-thrash).
    Budget 4.5 GB per slot against MemAvailable and cap at the CPU count.
    """
    cpus = os.cpu_count() or 4
    try:
        with open("/proc/meminfo") as fh:
            avail_kb = next(int(ln.split()[1]) for ln in fh
                            if ln.startswith("MemAvailable:"))
        by_mem = int(avail_kb / (4.5 * 1024 * 1024))
    except Exception:
        by_mem = cpus
    return max(1, min(cpus, by_mem))


# ---------------------------------------------------------------------------
# Parallel monotone SAT boundary search  (issue #72 / #76)
# ---------------------------------------------------------------------------

class SATBoundedSweep:
    """Parallel monotone boundary search for bounded-SAT miter depth.

    The bounded-miter predicate is *monotone* in depth n:

    * DIVERGES at n  →  diverges at every n′ > n  (CE trace is a valid prefix)
    * PROVEN at n    →  proven at every n′ < n     (proof subsumes every prefix)

    Finding the first divergence is therefore finding the step-function
    boundary — a problem that is parallelisable AND amenable to early
    cancellation.  Deepest probes run first (they claim a slot earliest so
    cheaper probes do not block them), and every completed result cancels all
    probes whose answer it implies.

    Concurrency is capped by *jobs* SAT slots, sized from available RAM (not
    the core count) so the box stays within budget even with many cores.

    Usage::

        sweep = SATBoundedSweep(oss_bin, work_dir, jobs=N, env={"TRELLIS_DBROOT": ...})
        # Full boundary search:
        lo, hi = sweep.sweep(miter_ys, max_depth=64, log=print)
        # lo = deepest PROVEN depth, hi = shallowest DIVERGING depth (None if none)

        # Single additional probe sharing the same SAT-slot semaphore:
        ok = sweep.probe(80, idle_ys, stage_prefix="diag_idle",
                         extra_set="-set in_cs_n 1")
    """

    def __init__(self, oss_bin: str, work_dir: "Path | str",
                 jobs: int, env: dict | None = None):
        self.oss_bin = str(oss_bin)
        self.work_dir = Path(work_dir)
        self.jobs = max(1, jobs)
        self.env = env or {}
        # shared semaphore so sweep + concurrent diagnostics probes
        # all draw from the same memory budget
        self._sat_slots = threading.Semaphore(self.jobs)
        self._probe_procs: dict = {}
        self._probe_cancelled: set = set()
        self._probe_lock = threading.Lock()
        # per-probe timing, accumulated across both sweep and extra probes
        self.timings: list[tuple[str, float]] = []
        self._timings_lock = threading.Lock()

    # ---- SAT command construction -----------------------------------------

    def _sat_cmd(self, n: int, miter_ys: Path, extra_set: str = "") -> list:
        extra = f"{extra_set.strip()} " if extra_set.strip() else ""
        return [f"{self.oss_bin}/yosys", "-s", str(miter_ys), "-p",
                f"sat -seq {n} -prove-asserts -set-init-zero {extra}"
                f"-set-at 1 in_rst 1 -set-at 2 in_rst 1 -set-at 3 in_rst 1"]

    # ---- single killable probe -------------------------------------------

    def probe(self, n: int, miter_ys: "Path | str",
              stage_prefix: str = "miter",
              extra_set: str = "") -> "bool | None":
        """One killable bounded-SAT probe at depth *n*.

        Blocks until a SAT slot is free (so total running probes ≤ jobs).
        Returns True (PROVEN), False (DIVERGES), or None if cancelled because
        a concurrent result already implied this probe's answer.

        Safe to call from multiple threads — all share the slot semaphore.
        """
        miter_ys = Path(miter_ys)
        e = {**os.environ,
             "PATH": self.oss_bin + os.pathsep + os.environ.get("PATH", "")}
        e.update(self.env)
        stage = f"{stage_prefix}{n}"

        with self._sat_slots:
            with self._probe_lock:
                if stage in self._probe_cancelled:
                    return None
                p = subprocess.Popen(
                    self._sat_cmd(n, miter_ys, extra_set), env=e,
                    cwd=str(REPO), stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True)
                self._probe_procs[stage] = p

            t0 = time.perf_counter()
            out, _ = p.communicate()
            dt = time.perf_counter() - t0

        with self._probe_lock:
            self._probe_procs.pop(stage, None)
            killed = stage in self._probe_cancelled

        (self.work_dir / f"stage_{stage}.log").write_text(out or "")
        with self._timings_lock:
            self.timings.append((stage, dt))

        if killed:
            return None
        if p.returncode != 0:
            sys.exit(f"stage {stage!r} FAILED (exit {p.returncode}):\n"
                     f"{(out or '')[-2000:]}")
        return "SUCCESS!" in out and "found a model" not in out

    # ---- cancellation helper -----------------------------------------------

    def _cancel_redundant(self, candidates, lo, hi, prefix="miter"):
        """Kill / skip every candidate the (lo, hi) bracket implies.

        depths ≤ lo are PROVEN by monotonicity; depths ≥ hi DIVERGE.
        """
        killed = []
        with self._probe_lock:
            for n in candidates:
                stage = f"{prefix}{n}"
                if stage in self._probe_cancelled:
                    continue
                if n <= lo or (hi is not None and n >= hi):
                    self._probe_cancelled.add(stage)
                    p = self._probe_procs.get(stage)
                    if p is not None:
                        p.kill()
                        killed.append(n)
        return killed

    # ---- spread utility ---------------------------------------------------

    @staticmethod
    def _spread(first: int, last: int, k: int) -> list:
        """Up to *k* evenly-spaced integers spanning [first, last]."""
        span = list(range(first, last + 1))
        if not span:
            return []
        k = min(max(1, k), len(span))
        if k == 1:
            return [span[len(span) // 2]]
        return sorted({span[round(i * (len(span) - 1) / (k - 1))]
                       for i in range(k)})

    # ---- one concurrent round of probes -----------------------------------

    def _probe_round(self, candidates, lo, hi, miter_ys, stage_prefix, log):
        candidates = [n for n in sorted(set(candidates))
                      if n > lo and (hi is None or n < hi)]
        if not candidates:
            return lo, hi
        # deepest first: expensive probes claim a slot before cheap ones
        order = sorted(candidates, reverse=True)
        with ThreadPoolExecutor(max_workers=len(order)) as ex:
            futs = {ex.submit(self.probe, n, miter_ys, stage_prefix): n
                    for n in order}
            for fut in as_completed(futs):
                n = futs[fut]
                ok = fut.result()
                if ok is None:
                    continue
                log(f"    depth {n:3d}: "
                    f"{'PROVEN equivalent' if ok else 'DIVERGES'}")
                if ok:
                    lo = max(lo, n)
                else:
                    hi = n if hi is None else min(hi, n)
                cut = self._cancel_redundant(candidates, lo, hi, stage_prefix)
                if cut:
                    log(f"              (bracket {lo}..{hi} -> cancelled "
                        f"redundant probes "
                        f"{', '.join(str(c) for c in sorted(cut))})")
        return lo, hi

    # ---- full monotone boundary search ------------------------------------

    def sweep(self, miter_ys: "Path | str", max_depth: int = 64,
              stage_prefix: str = "miter",
              log=None) -> tuple:
        """Full monotone boundary search from depth 1 to *max_depth*.

        Returns ``(lo, hi)``:
          * *lo* — deepest PROVEN depth (0 if nothing proven)
          * *hi* — shallowest DIVERGING depth (None if nothing diverged)
        """
        miter_ys = Path(miter_ys)
        if log is None:
            log = print

        # Round 1: jobs-wide even sweep across 1..max_depth.  Replaces the old
        # 8/16/32/48/64 sequential ladder — a dense sweep brackets far tighter
        # in the same wall time because the probe that settles the bracket is a
        # SHALLOWER (cheaper) one and it cancels the deeper probes immediately.
        lo, hi = self._probe_round(
            self._spread(1, max_depth, self.jobs), 0, None,
            miter_ys, stage_prefix, log)

        # Subsequent rounds: k-way probe across the open bracket, narrowing
        # by k+1 per round instead of the 2 a bisection manages.
        while hi is not None and hi - lo > 1:
            lo, hi = self._probe_round(
                self._spread(lo + 1, hi - 1, self.jobs), lo, hi,
                miter_ys, stage_prefix, log)

        return lo, hi
