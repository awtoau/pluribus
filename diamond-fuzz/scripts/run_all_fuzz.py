#!/usr/bin/env python3
"""
run_all_fuzz.py — Run all Diamond fuzz targets and load results into pluribus.

Usage (from the repo root):
    python3 diamond-fuzz/scripts/run_all_fuzz.py [--targets GLOB] [--dry-run] [--jobs N]

What this does:
    1. Discovers all fuzz target dirs under fuzz/targets/
    2. For each target: runs diamondc to PAR + bitgen
    3. Runs ecpunpack on each .bit to get a .config file
    4. Loads each .config into pluribus with a unique label (FUZZ_<target>)
    5. Logs pass/fail per target
    6. Writes fuzz/results/summary.txt

Each target runs Diamond sequentially (Diamond is single-threaded per project).
ecpunpack and pluribus loading run after all Diamond builds complete.

Diamond is parallelised at the project level with --jobs N (default 1, safe to
raise to 4 on a machine with enough RAM; Diamond uses ~2 GB per instance).
"""

import argparse
import fnmatch
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# ── Repo layout ──────────────────────────────────────────────────────────────

# This script lives at <repo>/diamond-fuzz/scripts/.
FUZZ_DIR    = Path(__file__).resolve().parents[1]   # <repo>/diamond-fuzz
ROOT        = FUZZ_DIR.parent                        # pluribus repo root
TARGETS_DIR = FUZZ_DIR / "targets"
RESULTS_DIR = FUZZ_DIR / "results"
LOG_DIR     = ROOT / "tmp"

# Diamond install comes from the environment (set DIAMONDDIR / LM_LICENSE_FILE
# in your shell); no machine-specific paths baked in here.
DIAMOND_ROOT = Path(os.environ.get("DIAMONDDIR", ""))
DIAMONDC     = DIAMOND_ROOT / "bin" / "lin64" / "diamondc"
LICENSE      = Path(os.environ.get("LM_LICENSE_FILE",
                    str(DIAMOND_ROOT / "license" / "license.dat")))

# Tile database — resolved from the standard TRELLIS_DBROOT the rest of the
# pipeline uses (falls back to the legacy TRELLIS_ROOT/database layout).
_TRELLIS     = Path(os.environ.get("TRELLIS_ROOT", "debris/tmp/prjtrellis"))
TRELLIS_DB   = Path(os.environ.get("TRELLIS_DBROOT", str(_TRELLIS / "database")))
# Unpacking is native pure-Python (no C++ ecpunpack / pytrellis .so).
NATIVE_UNPACK = ROOT / "scripts" / "trellis_unpack.py"

PLURIBUS     = ROOT                                   # load.py at repo root post-migration
FUZZ_PINS    = ROOT / "boards" / "aw2-2d82auto" / "pins.tsv"

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg, file=None):
    print(msg, flush=True, file=file)


def check_diamond_log(log_path: Path) -> list[str]:
    """Scan Diamond log for known error patterns. Returns list of error strings."""
    errors = []
    if not log_path.exists():
        return ["log file missing"]
    text = log_path.read_text(errors="replace")
    patterns = [
        (r"VERI-\d+[^\n]*unknown module[^\n]*[\"'](\w+)[\"']", "unknown module: {}"),
        (r"VERI-\d+[^\n]*undefined module[^\n]*[\"'](\w+)[\"']", "undefined module: {}"),
        (r"ERROR[^\n]*multiple drivers",       "multiple drivers (check wire rst = 1'b0)"),
        (r"ERROR[^\n]*no matching port",        "port mismatch"),
        (r"ERROR[^\n]*unresolved reference",    "unresolved reference"),
        (r"ERROR[^\n]*can't open file",         "can't open file"),
        (r"ERROR[^\n]*license",                 "license error"),
        (r"\bPAR FAILED\b",                     "PAR failed"),
        (r"^ERROR",                             "generic ERROR"),
    ]
    seen = set()
    for pat, msg in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE | re.MULTILINE):
            detail = msg.format(*m.groups()) if m.groups() else msg
            if detail not in seen:
                errors.append(detail)
                seen.add(detail)
    return errors


def discover_targets(glob_pattern: str | None = None) -> list[Path]:
    """Return sorted list of target dirs that contain a run.tcl (2 levels deep)."""
    if not TARGETS_DIR.exists():
        return []
    dirs = []
    for d in sorted(TARGETS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if (d / "run.tcl").exists():
            dirs.append(d)
        else:
            # descend one level for grouped targets (e.g. targets/highlevel/<name>/)
            for sub in sorted(d.iterdir()):
                if sub.is_dir() and not sub.name.startswith(".") and (sub / "run.tcl").exists():
                    dirs.append(sub)
    if glob_pattern:
        dirs = [d for d in dirs if fnmatch.fnmatch(d.name, glob_pattern)]
    return dirs


# ── Diamond build ─────────────────────────────────────────────────────────────

def run_diamond(target_dir: Path, log_path: Path) -> tuple[bool, str]:
    """Run diamondc on one target. Returns (success, detail)."""
    tcl = target_dir / "run.tcl"
    if not tcl.exists():
        return False, "run.tcl missing"

    impl1 = target_dir / "impl1"
    impl1.mkdir(exist_ok=True)

    env = dict(os.environ)
    env["LM_LICENSE_FILE"] = str(LICENSE)

    with open(log_path, "w") as fh:
        proc = subprocess.run(
            [str(DIAMONDC), str(tcl)],
            stdout=fh,
            stderr=subprocess.STDOUT,
            cwd=str(target_dir),
            env=env,
        )

    if proc.returncode != 0:
        return False, f"diamondc exited {proc.returncode}"

    bit = target_dir / "impl1" / "fuzz_impl1.bit"
    if not bit.exists():
        return False, ".bit file not produced"

    errors = check_diamond_log(log_path)
    if errors:
        return False, "; ".join(errors)

    return True, "ok"


def build_target(target_dir: Path, dry_run: bool = False) -> tuple[bool, str]:
    """Build one target with Diamond. Returns (success, detail)."""
    name     = target_dir.name
    log_path = target_dir / "impl1" / "diamond.log"
    bit      = target_dir / "impl1" / "fuzz_impl1.bit"

    # Skip if already built cleanly
    if bit.exists() and log_path.exists():
        errors = check_diamond_log(log_path)
        if not errors:
            return True, "cached"

    if dry_run:
        return True, "dry-run"

    log(f"  [diamond] building {name}...")
    ok, detail = run_diamond(target_dir, log_path)
    return ok, detail


# ── ecpunpack ─────────────────────────────────────────────────────────────────

def unpack_bitstream(target_dir: Path) -> tuple[Path | None, str]:
    """Decode the target's .bit → results/<name>/<name>.config with the native
    pure-Python unpacker (scripts/trellis_unpack.py) — no C++ ecpunpack / .so.
    Returns (config_path, detail)."""
    name    = target_dir.name
    bit     = target_dir / "impl1" / "fuzz_impl1.bit"
    out_dir = RESULTS_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    config  = out_dir / f"{name}.config"

    if not bit.exists():
        return None, ".bit missing"

    env = dict(os.environ)
    env["TRELLIS_DBROOT"] = str(TRELLIS_DB)

    # Always-rebuild: drop any stale .config so the native unpacker (which
    # refuses to overwrite) regenerates it from the current .bit + database.
    config.unlink(missing_ok=True)

    result = subprocess.run(
        [sys.executable, str(NATIVE_UNPACK), str(bit), str(config)],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )
    if result.returncode != 0:
        return None, f"unpack failed: {result.stderr[-200:]}"

    if not config.exists():
        return None, "unpack produced no output"

    return config, "ok"


# ── pluribus load ─────────────────────────────────────────────────────────────

def make_minimal_pins_tsv(out_path: Path) -> None:
    """Write a minimal header-only pins TSV for fuzz configs that have no named pins."""
    out_path.write_text(
        "# device: LCMXO2-1200\n"
        "# package: TQFP100\n"
        "# label: FUZZ\n"
        "# pin\trow\tcol\tpio\tdirection\tlabel\tfunction\tconfidence\n"
    )


def load_fuzz_config(target_name: str, config_path: Path,
                     pins_tsv: Path | None = None) -> tuple[bool, str]:
    """Load a fuzz .config into pluribus with label FUZZ_<target_name>."""
    label = f"FUZZ_{target_name}"
    pins  = pins_tsv if pins_tsv and pins_tsv.exists() else FUZZ_PINS

    # Fallback: generate a minimal header-only pins TSV if FUZZ_PINS doesn't exist
    if not pins.exists():
        minimal = RESULTS_DIR / "minimal_pins.tsv"
        make_minimal_pins_tsv(minimal)
        pins = minimal

    env = dict(os.environ)
    env["TRELLIS_DBROOT"] = str(TRELLIS_DB)

    result = subprocess.run(
        [sys.executable, str(PLURIBUS / "load.py"),
         "--label",   label,
         "--config",  str(config_path),
         "--pins",    str(pins),
         "--device",  "LCMXO2-1200",
         "--package", "TQFP100",
         "--fuzz",    # skip FF/LUT/net count sanity checks for small fuzz designs
        ],
        capture_output=True, text=True,
        cwd=str(ROOT), env=env,
    )
    if result.returncode != 0:
        return False, result.stderr[-400:]
    return True, label


# ── Worker threads ────────────────────────────────────────────────────────────

class BuildResult:
    __slots__ = ("target_dir", "ok", "detail", "config_path")
    def __init__(self, target_dir, ok, detail, config_path=None):
        self.target_dir  = target_dir
        self.ok          = ok
        self.detail      = detail
        self.config_path = config_path


_SENTINEL = None


def diamond_worker(work_q: queue.Queue, done_q: queue.Queue,
                   dry_run: bool, stats: dict, stats_lock: threading.Lock) -> None:
    """Pull targets from work_q, build with Diamond, push results to done_q."""
    while True:
        item = work_q.get()
        if item is _SENTINEL:
            work_q.task_done()
            break

        target_dir = item
        name       = target_dir.name

        ok, detail = build_target(target_dir, dry_run=dry_run)

        with stats_lock:
            if ok:
                stats["built"] += 1
                if detail == "cached":
                    stats["skipped"] += 1
            else:
                stats["failed"] += 1
                stats["failures"].append((name, detail))
                log(f"  FAILED  {name}: {detail}")

        if ok and not dry_run:
            # Unpack .bit → .config
            config_path, unpack_detail = unpack_bitstream(target_dir)
            done_q.put(BuildResult(target_dir, ok, detail, config_path))
        else:
            done_q.put(BuildResult(target_dir, ok, detail, None))

        work_q.task_done()


def pluribus_worker(done_q: queue.Queue,
                    stats: dict, stats_lock: threading.Lock) -> None:
    """Pull finished build results, run pluribus load."""
    while True:
        item = done_q.get()
        if item is _SENTINEL:
            done_q.task_done()
            break

        br   = item
        name = br.target_dir.name

        if not br.ok or br.config_path is None:
            done_q.task_done()
            continue

        # Change-detection: if the freshly-unpacked .config is byte-identical
        # to what we last loaded for this target, the DB already holds the same
        # result — throw the rebuild away and skip the reload (idempotent runs).
        cfg_sha = hashlib.sha256(br.config_path.read_bytes()).hexdigest()
        with stats_lock:
            unchanged = stats["hashes"].get(name) == cfg_sha
        if unchanged:
            with stats_lock:
                stats["unchanged"] += 1
            done_q.task_done()
            continue

        ok_load, detail = load_fuzz_config(name, br.config_path)
        with stats_lock:
            if ok_load:
                stats["loaded"] += 1
                stats["hashes"][name] = cfg_sha
            else:
                stats["load_failures"].append((name, detail))
                log(f"  LOAD-FAIL  {name}: {detail[:120]}")

        done_q.task_done()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--targets",  default=None, metavar="GLOB",
                    help="Only run targets matching this glob, e.g. 'iddr*'")
    ap.add_argument("--dry-run",  action="store_true",
                    help="Print what would be run, skip Diamond execution")
    ap.add_argument("--jobs", "-j", type=int, default=1, metavar="N",
                    help="Number of parallel Diamond instances (default 1; "
                         "each uses ~2 GB RAM)")
    ap.add_argument("--no-pluribus", action="store_true",
                    help="Skip pluribus load step (useful for offline Diamond runs)")
    args = ap.parse_args()

    if not DIAMONDC.exists():
        sys.exit(f"diamondc not found at {DIAMONDC}")

    targets = discover_targets(args.targets)
    if not targets:
        sys.exit(f"No targets found under {TARGETS_DIR}")

    log(f"Found {len(targets)} fuzz targets")
    if args.targets:
        log(f"  (filtered by: {args.targets!r})")
    log(f"  Diamond parallelism: {args.jobs} job(s)")
    log(f"  Pluribus load: {'disabled' if args.no_pluribus else 'enabled'}")
    if args.dry_run:
        log("  DRY RUN — no Diamond execution")
    log("")

    # Shared state
    # Change-detection manifest: target -> sha of the .config last loaded.
    hash_manifest = RESULTS_DIR / "loaded_hashes.json"
    try:
        loaded_hashes = json.loads(hash_manifest.read_text())
    except Exception:
        loaded_hashes = {}

    stats = {
        "built":         0,
        "skipped":       0,
        "failed":        0,
        "loaded":        0,
        "unchanged":     0,
        "hashes":        loaded_hashes,
        "failures":      [],   # list of (name, detail)
        "load_failures": [],
    }
    stats_lock = threading.Lock()

    work_q = queue.Queue()
    done_q = queue.Queue()

    # Missing-first: queue targets without a built bitstream ahead of cached
    # ones, so newly-added targets get built + loaded first and are usable
    # immediately (False < True → unbuilt sorts first).
    targets.sort(key=lambda t: (t / "impl1" / "fuzz_impl1.bit").exists())

    # Fill work queue
    for t in targets:
        work_q.put(t)

    # Start workers
    diamond_threads = []
    for _ in range(args.jobs):
        work_q.put(_SENTINEL)   # one sentinel per worker
        t = threading.Thread(
            target=diamond_worker,
            args=(work_q, done_q, args.dry_run, stats, stats_lock),
            daemon=True,
        )
        t.start()
        diamond_threads.append(t)

    if not args.no_pluribus:
        pluribus_t = threading.Thread(
            target=pluribus_worker,
            args=(done_q, stats, stats_lock),
            daemon=True,
        )
        pluribus_t.start()

    # Wait for Diamond workers to finish, then signal pluribus worker
    for t in diamond_threads:
        t.join()

    if not args.no_pluribus:
        done_q.put(_SENTINEL)
        pluribus_t.join()
        # Persist the change-detection manifest for the next run.
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        hash_manifest.write_text(
            json.dumps(stats["hashes"], indent=1, sort_keys=True))

    # Write summary
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RESULTS_DIR / "summary.txt"
    n = len(targets)
    lines = [
        "=== Fuzz run summary ===",
        f"  Total targets:   {n}",
        f"  Built:           {stats['built']} ({stats['skipped']} cached)",
        f"  Failed (Diamond):{stats['failed']}",
        f"  Loaded (pluribus):{stats['loaded']}",
        f"  Unchanged (reload skipped):{stats['unchanged']}",
        "",
    ]
    if stats["failures"]:
        lines.append("Diamond failures:")
        for name, detail in stats["failures"]:
            lines.append(f"  {name:<40s}  {detail}")
        lines.append("")
    if stats["load_failures"]:
        lines.append("Pluribus load failures:")
        for name, detail in stats["load_failures"]:
            lines.append(f"  {name:<40s}  {detail[:100]}")
        lines.append("")
    if not stats["failures"] and not stats["load_failures"]:
        lines.append("All targets passed.")
    summary = "\n".join(lines)
    log("\n" + summary)
    summary_path.write_text(summary + "\n")
    log(f"\nSummary written to {summary_path}")

    if stats["failures"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
