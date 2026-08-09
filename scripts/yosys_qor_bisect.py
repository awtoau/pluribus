#!/usr/bin/env python3.15t
"""Bisect a yosys commit range against synthesis QoR (quality of results).

`git bisect` wants a pass/fail; a QoR regression is a NUMBER that drifts, so
this walks the range explicitly and records LUT4 / cell counts per commit.

Motivation: yosys 0.68+40 emits a netlist that fails timing on 5/8 nextpnr
seeds where 0.65+57's passes 0/8.  nextpnr is exonerated (same old netlist
through the new placer is unchanged), so the regression is in synthesis.
Cell count is the cheap proxy -- one synth run per commit, no place-and-route.

Builds are the expensive part (~2-4 min each), so:
  * only non-merge commits are tried, newest-first by default;
  * ccache is used if present;
  * results append to a JSON file so an interrupted run resumes.

Usage:
    python3.15t scripts/yosys_qor_bisect.py --repo <yosys-git> --pkg <design> \
        --good 9d0cdb855 --bad 0f2bcb94b --out tmp/buildperf/qor_bisect.json

Logs to ./tmp/logs/yosys_qor_bisect.log.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp" / "logs"
LOG = logging.getLogger("yosys_qor_bisect")


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "yosys_qor_bisect.log", mode="a")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    LOG.setLevel(logging.INFO)
    LOG.addHandler(fh)
    LOG.addHandler(sh)


def run(cmd: list[str], cwd: Path, timeout: float, what: str) -> subprocess.CompletedProcess:
    """Run a command, logging failures. Timeout is per-caller with a stated basis."""
    t0 = time.monotonic()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    LOG.debug("%s took %.1f s rc=%d", what, time.monotonic() - t0, p.returncode)
    return p


def commits(repo: Path, good: str, bad: str) -> list[tuple[str, str]]:
    p = run(["git", "log", "--format=%H\t%s", "--no-merges", f"{good}..{bad}"],
            repo, 60, "git log")
    if p.returncode != 0:
        raise SystemExit(f"git log failed: {p.stderr}")
    out = []
    for line in p.stdout.strip().splitlines():
        h, _, subj = line.partition("\t")
        out.append((h, subj))
    return out


def build(worktree: Path, jobs: int) -> bool:
    """Configure + build yosys in worktree. Returns True on success."""
    bd = worktree / "build"
    # cmake configure is ~5 s; 300 s is 60x -- generous because a cold ccache
    # and submodule checkout land here. Expiry means the tree is broken.
    p = run(["cmake", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"], worktree, 300, "cmake")
    if p.returncode != 0:
        LOG.error("cmake configure failed:\n%s", p.stderr[-2000:])
        return False
    # Full build measured at ~110 s with 31 jobs and warm ccache; 900 s is ~8x
    # to cover a cold cache. Expiry = build wedged, not slow.
    p = run(["cmake", "--build", "build", f"-j{jobs}"], worktree, 900, "build")
    if p.returncode != 0:
        LOG.error("build failed:\n%s", p.stderr[-3000:])
        return False
    return (bd / "yosys").is_file()


def synth_counts(yosys: Path, pkg: Path, workdir: Path) -> dict | None:
    """Run the design's own top.ys and count cells by type."""
    workdir.mkdir(parents=True, exist_ok=True)
    for f in ("top.il", "top.ys", "top.lpf", "VexiiRiscv.v"):
        src = pkg / f
        if src.exists():
            shutil.copy2(src, workdir / f)
    t0 = time.monotonic()
    # Synthesis measured 31-75 s across versions; 600 s is ~8x the slowest.
    # Expiry means this commit hangs -- recorded as a failure, not retried.
    try:
        p = run([str(yosys), "-q", "-l", "synth.log", "top.ys"], workdir, 600, "synth")
    except subprocess.TimeoutExpired:
        LOG.error("synthesis TIMED OUT")
        return None
    dt = time.monotonic() - t0
    if p.returncode != 0:
        LOG.error("synth failed rc=%d:\n%s", p.returncode, p.stderr[-2000:])
        return None
    jf = workdir / "top.json"
    if not jf.is_file():
        return None
    j = json.loads(jf.read_text())
    top = j["modules"].get("top")
    if top is None:
        return None
    c = Counter(v["type"] for v in top["cells"].values())
    return {
        "seconds": round(dt, 2),
        "total_cells": sum(c.values()),
        "LUT4": c.get("LUT4", 0),
        "TRELLIS_FF": c.get("TRELLIS_FF", 0),
        "PFUMX": c.get("PFUMX", 0),
        "L6MUX21": c.get("L6MUX21", 0),
        "CCU2C": c.get("CCU2C", 0),
        "DP16KD": c.get("DP16KD", 0),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, required=True, help="yosys git repo (a mirror; not modified)")
    ap.add_argument("--pkg", type=Path, required=True, help="design dir with top.ys/top.il")
    ap.add_argument("--good", required=True, help="known-good commit (exclusive)")
    ap.add_argument("--bad", required=True, help="known-bad commit (inclusive)")
    ap.add_argument("--out", type=Path, required=True, help="JSON results (appended/resumed)")
    ap.add_argument("--jobs", type=int, default=31)
    ap.add_argument("--workroot", type=Path, default=REPO / "tmp" / "buildperf" / "bisect")
    ap.add_argument("--limit", type=int, default=0, help="only try the newest N commits")
    args = ap.parse_args()

    setup_logging()
    repo = args.repo.resolve()
    pkg = args.pkg.resolve()
    args.workroot.mkdir(parents=True, exist_ok=True)

    results: dict = {}
    if args.out.exists():
        results = json.loads(args.out.read_text())
        LOG.info("resuming: %d commits already measured", len(results))

    todo = commits(repo, args.good, args.bad)
    if args.limit:
        todo = todo[: args.limit]
    LOG.info("bisect range: %d non-merge commits", len(todo))

    for i, (sha, subj) in enumerate(todo, 1):
        if sha in results:
            LOG.info("[%d/%d] %s SKIP (cached)", i, len(todo), sha[:9])
            continue
        LOG.info("[%d/%d] %s %s", i, len(todo), sha[:9], subj[:70])
        wt = args.workroot / sha[:9]
        if not wt.exists():
            p = run(["git", "worktree", "add", "--detach", str(wt), sha], repo, 180, "worktree")
            if p.returncode != 0:
                LOG.error("worktree failed: %s", p.stderr[-500:])
                results[sha] = {"subject": subj, "error": "worktree"}
                args.out.write_text(json.dumps(results, indent=2))
                continue
        run(["git", "submodule", "update", "--init", "--recursive"], wt, 600, "submodules")

        rec: dict = {"subject": subj}
        if not build(wt, args.jobs):
            rec["error"] = "build"
        else:
            counts = synth_counts(wt / "build" / "yosys", pkg, wt / "synth")
            if counts is None:
                rec["error"] = "synth"
            else:
                rec.update(counts)
                LOG.info("    LUT4=%-6d total=%-6d %.1f s",
                         counts["LUT4"], counts["total_cells"], counts["seconds"])
        results[sha] = rec
        args.out.write_text(json.dumps(results, indent=2))
        # Build trees are ~2 GB each; drop the object dir once measured.
        shutil.rmtree(wt / "build", ignore_errors=True)

    LOG.info("=" * 70)
    for sha, r in results.items():
        if "LUT4" in r:
            LOG.info("%s LUT4=%-6d total=%-6d  %s", sha[:9], r["LUT4"],
                     r["total_cells"], r["subject"][:50])
        else:
            LOG.info("%s ERROR=%-10s %s", sha[:9], r.get("error", "?"), r["subject"][:50])
    return 0


if __name__ == "__main__":
    sys.exit(main())
