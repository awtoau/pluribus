#!/usr/bin/env python3.15t
"""Benchmark + variance harness for the open ECP5 flow (yosys / nextpnr / ecppack).

Two jobs, and the second is the one that matters:

* time each stage of a build, so a speed change is attributable to a stage;
* run N nextpnr seeds CONCURRENTLY and report the Fmax/utilisation
  DISTRIBUTION, so "did my change help?" is answerable from one wall-clock
  interval instead of N sequential builds.

Seed sweep is the point.  nextpnr placement is stochastic: on this design the
same input yields Fmax 56.21-67.27 MHz against a 60 MHz constraint, so a single
build cannot distinguish a real improvement from placement luck.  Seeds are
independent processes with no shared state, so they scale across cores.

Usage:
    python3.15t scripts/fpga_build_bench.py --pkg <dir> --stages
    python3.15t scripts/fpga_build_bench.py --pkg <dir> --seeds 16 --workers 8

Logs to ./tmp/logs/fpga_build_bench.log per the repo rule.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import logging
import re
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "tmp" / "logs"
LOG = logging.getLogger("fpga_build_bench")

# nextpnr prints "Max frequency for clock '<name>': <f> MHz (PASS|FAIL at <t> MHz)",
# prefixed "Info:" during iteration and "ERROR:" for the final failing verdict.
# Keep the prefix: on a failing seed the ERROR line is the authoritative result and
# does NOT match the last Info line (observed 58.06 ERROR vs 55.69 Info on one seed).
RE_FMAX = re.compile(
    r"^(Info|ERROR):\s+Max frequency for clock\s+'([^']+)':\s+([0-9.]+)\s+MHz\s+\((PASS|FAIL)",
    re.M,
)
RE_UTIL = re.compile(r"^\s*(\w+):\s+(\d+)/\s*(\d+)\s+(\d+)%", re.M)


def setup_logging(verbose: bool) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "fpga_build_bench.log", mode="a")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    LOG.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOG.addHandler(fh)
    LOG.addHandler(sh)


@dataclass
class SeedResult:
    seed: int
    seconds: float
    ok: bool
    fmax: dict[str, float] = field(default_factory=dict)
    verdict: dict[str, str] = field(default_factory=dict)
    util: dict[str, int] = field(default_factory=dict)


def parse_nextpnr_log(text: str) -> tuple[dict, dict, dict]:
    fmax: dict[str, float] = {}
    verdict: dict[str, str] = {}
    errored: set[str] = set()
    for prefix, clk, mhz, res in RE_FMAX.findall(text):
        # An ERROR line is the final verdict and wins outright; otherwise the last
        # Info line for that clock is the routed result.
        if clk in errored and prefix != "ERROR":
            continue
        if prefix == "ERROR":
            errored.add(clk)
        fmax[clk] = float(mhz)
        verdict[clk] = res
    util = {m.group(1): int(m.group(2)) for m in RE_UTIL.finditer(text)}
    return fmax, verdict, util


def run_stage(name: str, cmd: list[str], cwd: Path) -> float:
    """Run one stage, return wall-clock seconds. Any non-zero exit is fatal."""
    LOG.info("stage %-9s starting: %s", name, " ".join(cmd))
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    dt = time.monotonic() - t0
    if proc.returncode != 0:
        LOG.error("stage %s FAILED rc=%d\n%s", name, proc.returncode, proc.stderr[-4000:])
        raise SystemExit(f"stage {name} failed")
    LOG.info("stage %-9s done in %7.2f s", name, dt)
    return dt


def nextpnr_cmd(pkg: Path, seed: int | None, threads: int, out_prefix: str,
                json_in: str = "top.json") -> list[str]:
    cmd = [
        "nextpnr-ecp5", "--quiet", "--parallel-refine", "--threads", str(threads),
        "--router", "router2", "--12k", "--package", "CABGA256", "--speed", "8",
        "--json", json_in, "--lpf", "top.lpf",
        "--log", f"{out_prefix}.tim", "--textcfg", f"{out_prefix}.config",
    ]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    return cmd


def stage_bench(pkg: Path, yosys: str, threads: int) -> dict[str, float]:
    """Time yosys / nextpnr / ecppack individually."""
    times: dict[str, float] = {}
    times["yosys"] = run_stage("yosys", [yosys, "-q", "-l", "top.rpt", "top.ys"], pkg)
    times["nextpnr"] = run_stage("nextpnr", nextpnr_cmd(pkg, None, threads, "top"), pkg)
    times["ecppack"] = run_stage(
        "ecppack",
        ["ecppack", "--compress", "--freq", "38.8", "--input", "top.config",
         "--bit", "top.bit", "--svf", "top.svf"],
        pkg,
    )
    times["total"] = sum(times.values())
    return times


def one_seed(pkg: Path, seed: int, threads: int, workdir: Path) -> SeedResult:
    """One nextpnr run in its own directory so concurrent seeds cannot collide."""
    d = workdir / f"seed{seed}"
    d.mkdir(parents=True, exist_ok=True)
    for f in ("top.json", "top.lpf"):
        src = pkg / f
        if not src.exists():
            raise SystemExit(f"missing {src} -- run --stages first to produce top.json")
        shutil.copy2(src, d / f)

    t0 = time.monotonic()
    proc = subprocess.run(nextpnr_cmd(d, seed, threads, "out"),
                          cwd=d, capture_output=True, text=True)
    dt = time.monotonic() - t0
    log_text = (d / "out.tim").read_text() if (d / "out.tim").exists() else ""
    log_text += proc.stderr
    fmax, verdict, util = parse_nextpnr_log(log_text)
    ok = proc.returncode == 0
    LOG.info("seed %-3d %6.1f s  rc=%d  %s", seed, dt, proc.returncode,
             " ".join(f"{k}={v:.2f}MHz/{verdict.get(k, '?')}" for k, v in sorted(fmax.items())))
    return SeedResult(seed=seed, seconds=dt, ok=ok, fmax=fmax, verdict=verdict, util=util)


def seed_sweep(pkg: Path, seeds: int, workers: int, threads: int, workdir: Path) -> list[SeedResult]:
    LOG.info("seed sweep: %d seeds, %d concurrent, %d threads each", seeds, workers, threads)
    results: list[SeedResult] = []
    t0 = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one_seed, pkg, s, threads, workdir): s for s in range(1, seeds + 1)}
        for fut in cf.as_completed(futs):
            results.append(fut.result())
    LOG.info("sweep wall clock %.1f s for %d seeds", time.monotonic() - t0, seeds)
    return sorted(results, key=lambda r: r.seed)


def report(results: list[SeedResult]) -> dict:
    clocks: dict[str, list[float]] = {}
    for r in results:
        for clk, f in r.fmax.items():
            clocks.setdefault(clk, []).append(f)

    summary: dict = {"seeds": len(results), "clocks": {}}
    LOG.info("=" * 68)
    for clk, vals in sorted(clocks.items()):
        if not vals:
            continue
        fails = sum(1 for r in results if r.verdict.get(clk) == "FAIL")
        st = {
            "min": min(vals), "max": max(vals),
            "mean": statistics.fmean(vals),
            "median": statistics.median(vals),
            "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
            "fail_count": fails, "n": len(vals),
        }
        summary["clocks"][clk] = st
        LOG.info("clock %-10s n=%-3d min=%6.2f median=%6.2f max=%6.2f stdev=%5.2f FAIL=%d/%d",
                 clk, st["n"], st["min"], st["median"], st["max"], st["stdev"], fails, st["n"])
    LOG.info("=" * 68)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pkg", type=Path, required=True, help="directory with top.ys/top.il/top.lpf")
    ap.add_argument("--yosys", default="yosys", help="yosys binary to time (compare builds)")
    ap.add_argument("--stages", action="store_true", help="time yosys/nextpnr/ecppack separately")
    ap.add_argument("--seeds", type=int, default=0, help="run N nextpnr seeds for a variance report")
    ap.add_argument("--workers", type=int, default=8, help="concurrent seeds")
    ap.add_argument("--threads", type=int, default=4, help="--threads per nextpnr process")
    ap.add_argument("--workdir", type=Path, default=REPO / "tmp" / "buildperf" / "sweep")
    ap.add_argument("--json", type=Path, help="write results as JSON")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)
    pkg = args.pkg.resolve()
    if not pkg.is_dir():
        raise SystemExit(f"not a directory: {pkg}")

    out: dict = {"pkg": str(pkg), "yosys": args.yosys}
    if args.stages:
        out["stage_seconds"] = stage_bench(pkg, args.yosys, max(args.threads, 31))
        LOG.info("stage totals: %s", json.dumps(out["stage_seconds"], indent=2))
    if args.seeds:
        res = seed_sweep(pkg, args.seeds, args.workers, args.threads, args.workdir.resolve())
        out["variance"] = report(res)
        out["seed_seconds"] = {r.seed: round(r.seconds, 2) for r in res}
    if not args.stages and not args.seeds:
        raise SystemExit("nothing to do: pass --stages and/or --seeds N")

    if args.json:
        args.json.write_text(json.dumps(out, indent=2))
        LOG.info("wrote %s", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
