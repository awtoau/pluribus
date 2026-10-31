#!/usr/bin/env python3
"""dev.py — canonical entry point for <PROJECT> (awto dev.py convention).

AI agents: run `./dev.py describe` for machine-readable JSON help.
Humans: run `./dev.py --help`.

All output is timestamped in LOCAL time and mirrored to ./tmp/logs/dev.log.

Scaffold usage:
    cp awto-dan/dev.py-template/dev.py  <repo>/dev.py
    cp awto-dan/dev.py-template/test_dev.py <repo>/tests/
    - set PROJECT below
    - edit the STEPS table; that is the ONLY place build/test commands live

Everything else (help, describe, gate, ci, logging, exit codes) is generic
and should not need editing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT = "pluribus"


def _repo_root() -> Path:
    """Three-tier resolution (awto-dan#35): env override, git toplevel,
    file-relative. Works at <repo>/dev.py AND <repo>/scripts/dev.py.
    Never VSCODE_CWD — that is the launch directory, not the workspace."""
    env = os.environ.get(f"{PROJECT.upper().replace('-', '_')}_REPO")
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_dir():
            return p
    here = Path(__file__).resolve().parent
    try:
        # local .git read, ~1 ms warm; 0.25 s covers a cold first exec.
        # On expiry/absence: file-relative fallback below.
        out = subprocess.run(["git", "-C", str(here), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=0.25)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return here.parent if here.name == "scripts" else here


REPO = _repo_root()
TMP = REPO / "tmp"           # scratch, pidfiles
LOGS = TMP / "logs"          # logs, per the ./tmp/logs/ rule
LOG = LOGS / "dev.log"

# --------------------------------------------------------------------------
# STEPS — the only project-specific part.
#
# Each entry: command name -> (summary, argv, accepts_extra_args)
# argv of [] means "not configured for this project"; such a step SKIPS
# rather than fails, so a fresh scaffold runs green before you fill it in.
# Swap for your build system: cargo / pytest / west / npm / make ...
# --------------------------------------------------------------------------
# Ships UNCONFIGURED ([]) so a fresh copy runs green immediately: every step
# SKIPs, `ci` reports GO with skips listed, and you fill them in one at a time
# and watch each go from SKIP to ok. Replace [] with the real argv.
#
#   Rust    build ["cargo","build"]   test ["cargo","test","--workspace"]
#           lint  ["cargo","clippy","--all-targets"]   fmt ["cargo","fmt"]
#   Python  test  [sys.executable,"-m","pytest","-q"]  lint ["ruff","check","."]
#   Zephyr  build ["west","build"]     test ["west","build","-t","run_tests"]
STEPS: dict[str, tuple[str, list[str], bool]] = {
    "build":     ("compile the project",          [], True),
    "test":      ("run the test suite",           ["python3.15t", "-m", "pytest", "-q"], True),
    "lint":      ("static analysis",              [], True),
    "fmt-check": ("formatting check (no writes)", [], False),
    "fmt":       ("reformat in place",            [], False),
    "run":       ("build + execute",              [], True),
}

# gate = fail-fast, blocks a commit. First failure wins; fix that.
GATE = ["fmt-check", "lint", "test", "build"]
# ci = run-all-collect-all. Every leg runs even after a failure, then ONE
# GO/NO-GO. On hardware a re-run costs minutes and may not reproduce.
CI = ["fmt-check", "lint", "test", "build"]

# --------------------------------------------------------------------------
# Logging — Tier A (dev tooling): local time, stderr + ./tmp/logs/dev.log,
# colour on TTY only, file copy always plain.
# --------------------------------------------------------------------------
_COLOR = {
    "FATAL": "\033[1;91m", "ERROR": "\033[31m", "WARN": "\033[33m",
    "INFO": "\033[97m", "DEBUG": "\033[94m", "ALERT": "\033[92m",
}
_RESET = "\033[0m"
_USE_COLOR = (
    sys.stderr.isatty()
    and not os.environ.get("NO_COLOR")
    and os.environ.get("CLICOLOR") != "0"
)


def _stamp() -> str:
    # Local zone incl. DST (AEST +1000 / AEDT +1100). Never hardcode the
    # offset and never use UTC here: a human reads these live.
    return datetime.now().astimezone().strftime("%H:%M:%S.%f%z")


def log(msg: str, level: str = "INFO") -> None:
    line = f"{_stamp()}  {level:<5} [dev.py] {msg}"
    if _USE_COLOR:
        sys.stderr.write(f"{_COLOR.get(level, '')}{line}{_RESET}\n")
    else:
        sys.stderr.write(line + "\n")
    sys.stderr.flush()
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")          # file copy is ALWAYS plain
    except OSError:
        pass                                # never let logging kill the run


SKIPPED = 125   # distinct from any real tool's exit code


def run_step(name: str, extra: list[str] | None = None) -> int:
    """Run one STEPS entry. Returns its exit code, or SKIPPED."""
    summary, argv, takes_extra = STEPS[name]
    if not argv:
        log(f"{name}: not configured for this project - skipped", "WARN")
        return SKIPPED
    if not shutil.which(argv[0]) and argv[0] != sys.executable:
        log(f"{name}: {argv[0]} not on PATH - skipped", "WARN")
        return SKIPPED
    cmd = argv + (list(extra) if (extra and takes_extra) else [])
    log("run: " + " ".join(cmd))
    rc = subprocess.call(cmd, cwd=REPO)
    log(f"rc={rc}: " + " ".join(cmd), "INFO" if rc == 0 else "ERROR")
    return rc


# --------------------------------------------------------------------------
# Command registry — ONE source of truth. The decorator populates the table
# that drives dispatch, --help AND describe, so they cannot drift apart.
# --------------------------------------------------------------------------
COMMANDS: dict[str, dict] = {}


def command(summary: str, *, args: str = "", kind: str = "action"):
    def deco(fn):
        COMMANDS[fn.__name__.replace("cmd_", "").replace("_", "-")] = {
            "summary": summary, "args": args, "kind": kind, "fn": fn,
        }
        return fn
    return deco


@command("machine-readable command list (JSON, for AI agents)", kind="meta")
def cmd_describe(_extra: list[str]) -> int:
    print(json.dumps({
        "project": PROJECT,
        "schema": 1,
        "entrypoint": "./dev.py",
        "log": str(LOG.relative_to(REPO)),
        "exit_codes": {"0": "success", "2": "usage error",
                       "125": "step skipped (tool absent)", "other": "failure"},
        "commands": {
            name: {k: v for k, v in meta.items() if k != "fn"}
            for name, meta in COMMANDS.items()
        },
    }, indent=2))
    return 0


@command("check the toolchain is present; run this first when stuck", kind="meta")
def cmd_doctor(_extra: list[str]) -> int:
    log(f"project    : {PROJECT}")
    log(f"python     : {sys.version.split()[0]} ({sys.executable})")
    log(f"gil        : {'disabled (free-threaded)' if not sys._is_gil_enabled() else 'enabled'}"
        if hasattr(sys, "_is_gil_enabled") else "gil        : n/a (<3.13)")
    missing = []
    for name, (_s, argv, _e) in STEPS.items():
        if not argv:
            log(f"{name:10s} : not configured", "WARN")
        elif argv[0] == sys.executable or shutil.which(argv[0]):
            log(f"{name:10s} : {argv[0]} ok")
        else:
            log(f"{name:10s} : {argv[0]} MISSING", "ERROR")
            missing.append(argv[0])
    if missing:
        log(f"missing tools: {', '.join(sorted(set(missing)))}", "ERROR")
        return 1
    log("doctor ok", "ALERT")
    return 0


@command("remove build output and logs", kind="action")
def cmd_clean(_extra: list[str]) -> int:
    for path in (TMP,):
        if path.exists():
            shutil.rmtree(path)
            log(f"removed {path.relative_to(REPO)}")
    return 0


@command("build the third-party EP4CGX150 image's flat+RTL Verilog, then ALWAYS "
         "equivalence-check RTL against flat (idle + SPI); fails if they diverge. "
         "Image: --image PATH or $PLURIBUS_DJI_IMAGE. Never skips the check: a hand-run "
         "flat/rtl.v with no verified-equivalent claim should not reach a commit or a push "
         "(#165 found 2 real RTL bugs this way; dev.py exists so that check is not optional).",
         args="[--image PATH] [--out DIR] [--no-spi]", kind="aggregate")
def cmd_lift_image(extra: list[str]) -> int:
    image = os.environ.get("PLURIBUS_DJI_IMAGE")
    out = str(TMP / "image_sim")
    spi = True
    rest = list(extra)
    i = 0
    while i < len(rest):
        if rest[i] == "--image" and i + 1 < len(rest):
            image, i = rest[i + 1], i + 2
        elif rest[i] == "--out" and i + 1 < len(rest):
            out, i = rest[i + 1], i + 2
        elif rest[i] == "--no-spi":
            spi, i = False, i + 1
        else:
            i += 1
    if not image:
        log("lift-image: image path required (--image PATH or $PLURIBUS_DJI_IMAGE)", "FATAL")
        return 2
    build_argv = [sys.executable, str(REPO / "scripts" / "cycloneiv_clean_image_build.py"),
                  image, "--out", out]
    log("run: " + " ".join(build_argv))
    rc = subprocess.call(build_argv, cwd=REPO)
    log(f"rc={rc}: image_build", "INFO" if rc == 0 else "ERROR")
    if rc != 0:
        log("lift-image FAILED at build", "FATAL")
        return rc
    # rc==0 alone is not proof of success: a transient failure (e.g. a heavy_guard
    # resource race under concurrent load) can leave the child's exit code looking
    # clean while flat.v/nl.pkl/build.json were never written - verify the actual
    # outputs exist and are non-empty before trusting the exit code.
    missing = [p for p in ("flat.v", "nl.pkl", "build.json") if not (Path(out) / p).is_file() or (Path(out) / p).stat().st_size == 0]
    if missing:
        log(f"lift-image FAILED at build: rc=0 but missing/empty output(s): {missing} in {out} "
            f"(the build subprocess likely died partway through - check tmp/logs/cycloneiv_clean_image_build.log)", "FATAL")
        return 1
    # cycloneiv_clean_image_build.py reads nl.pkl/flat.v/rtl.v from --out (`out` above);
    # cycloneiv_clean_rtl_image_compare.py must read the SAME directory, not its own
    # default (tmp/image_sim_rtl) - pass --out through to both its subcommands.
    cmp_argv = [sys.executable, str(REPO / "scripts" / "cycloneiv_clean_rtl_image_compare.py")]
    log("run: " + " ".join(cmp_argv + ["lift", "--out", out]))
    rc = subprocess.call(cmp_argv + ["lift", "--out", out], cwd=REPO)
    if rc != 0:
        log("lift-image FAILED at equivalence-lift", "FATAL")
        return rc
    run_args = ["run", "--out", out] + (["--spi"] if spi else [])
    log("run: " + " ".join(cmp_argv + run_args))
    rc = subprocess.call(cmp_argv + run_args, cwd=REPO)
    if rc != 0:
        log("lift-image FAILED at equivalence-run", "FATAL")
        return rc
    cmp_json = Path(out) / "compare.json"
    try:
        res = json.loads(cmp_json.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log(f"lift-image FAILED: could not read {cmp_json} ({e})", "FATAL")
        return 1
    if res.get("rows_differing", 1) != 0:
        log(f"lift-image FAILED: RTL and flat emit DIVERGE: {json.dumps(res)}", "FATAL")
        return 1
    if res.get("first_diff") is not None:
        log(f"lift-image FAILED: RTL and flat emit DIVERGE under SPI stimulus: {json.dumps(res)}", "FATAL")
        return 1
    log(f"lift-image: RTL == flat, {res.get('rows', '?')} rows, 0 differing. Verified equivalent.", "ALERT")
    return 0


@command("functional trace + classify report for a hard-block type (mac/m9k/pll/...) "
         "over the image's lifted netlist: operand/sink trace, chain-detection, topology "
         "classification (V/I/U tagged). Generic core (functrace.py) + a per-type plugin; "
         "re-run this after any lift improvement instead of re-deriving by hand. "
         "Image: --image PATH or $PLURIBUS_DJI_IMAGE.",
         args="--type <mac|m9k|pll|...> [--image PATH] [--out DIR]", kind="action")
def cmd_functrace(extra: list[str]) -> int:
    script = REPO / "scripts" / "cycloneiv_clean_functrace_report.py"
    if not script.exists():
        log(f"functrace: {script.relative_to(REPO)} not found - not built yet for this repo", "WARN")
        return SKIPPED
    argv = [sys.executable, str(script)] + list(extra)
    log("run: " + " ".join(argv))
    rc = subprocess.call(argv, cwd=REPO)
    log(f"rc={rc}: functrace", "INFO" if rc == 0 else "ERROR")
    return rc


@command("fail-fast pre-commit gate: " + " + ".join(GATE), kind="aggregate")
def cmd_gate(_extra: list[str]) -> int:
    for name in GATE:
        rc = run_step(name)
        if rc not in (0, SKIPPED):
            log(f"GATE FAILED at {name} (rc={rc})", "FATAL")
            return rc
    log("GATE PASSED", "ALERT")
    return 0


@command("run every leg, collect all results, one GO/NO-GO", kind="aggregate")
def cmd_ci(_extra: list[str]) -> int:
    results: dict[str, int] = {}
    for name in CI:
        results[name] = run_step(name)          # no early exit - that is the point
    failed = {k: v for k, v in results.items() if v not in (0, SKIPPED)}
    skipped = [k for k, v in results.items() if v == SKIPPED]
    log("-" * 52)
    for name, rc in results.items():
        state = "SKIP" if rc == SKIPPED else ("ok" if rc == 0 else f"FAIL rc={rc}")
        log(f"  {name:12s} {state}", "INFO" if rc in (0, SKIPPED) else "ERROR")
    if skipped:
        log(f"{len(skipped)} step(s) skipped: {', '.join(skipped)}", "WARN")
    if failed:
        log(f"NO-GO - {len(failed)} of {len(results)} failed: {', '.join(failed)}", "FATAL")
        return 1
    log("GO", "ALERT")
    return 0


@command("verify dev.py's own contract (help/describe/exit codes)", kind="meta")
def cmd_selftest(_extra: list[str]) -> int:
    failures = []

    def check(label: str, cond: bool) -> None:
        log(f"  {label}: {'ok' if cond else 'FAIL'}", "INFO" if cond else "ERROR")
        if not cond:
            failures.append(label)

    out = subprocess.run([sys.executable, __file__, "describe"],
                         capture_output=True, text=True, cwd=REPO)
    check("describe exits 0", out.returncode == 0)
    try:
        doc = json.loads(out.stdout)
        check("describe emits valid JSON", True)
        check("describe has project+commands", {"project", "commands"} <= doc.keys())
        check("every command documented", all(
            m.get("summary") for m in doc.get("commands", {}).values()))
    except json.JSONDecodeError:
        check("describe emits valid JSON", False)

    h = subprocess.run([sys.executable, __file__, "--help"],
                       capture_output=True, text=True, cwd=REPO)
    check("--help exits 2 (usage)", h.returncode == 2)
    check("--help lists commands", all(c in h.stdout for c in COMMANDS))

    u = subprocess.run([sys.executable, __file__, "no-such-command"],
                       capture_output=True, text=True, cwd=REPO)
    check("unknown command exits 2", u.returncode == 2)

    check("registry has no duplicate handlers",
          len({m["fn"] for m in COMMANDS.values()}) == len(COMMANDS))

    if failures:
        log(f"selftest FAILED: {', '.join(failures)}", "FATAL")
        return 1
    log("selftest ok", "ALERT")
    return 0


def _register_steps() -> None:
    """Expose each STEPS entry as a first-class command."""
    for name, (summary, _argv, takes_extra) in STEPS.items():
        if name in COMMANDS:
            continue
        COMMANDS[name] = {
            "summary": summary,
            "args": "[extra args passed through]" if takes_extra else "",
            "kind": "step",
            "fn": (lambda n: lambda extra: run_step(n, extra))(name),
        }


_register_steps()


def usage() -> int:
    print(__doc__.split("Scaffold usage:")[0].rstrip())
    print(f"\nUsage: ./dev.py <command> [args]\n")
    # Iterate the kinds actually present, ordered - a hardcoded list silently
    # drops any new kind from --help (selftest catches this).
    order = ["aggregate", "step", "action", "meta"]
    kinds = sorted({m["kind"] for m in COMMANDS.values()},
                   key=lambda k: (order.index(k) if k in order else len(order), k))
    for kind in kinds:
        group = {n: m for n, m in COMMANDS.items() if m["kind"] == kind}
        if not group:
            continue
        print(f"  {kind}:")
        for name, meta in sorted(group.items()):
            print(f"    {name:<12} {meta['summary']}")
        print()
    print(f"Log: {LOG.relative_to(REPO)}   JSON help: ./dev.py describe")
    return 2


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        return usage()
    name, *extra = argv
    meta = COMMANDS.get(name)
    if meta is None:
        print(f"unknown command: {name!r} — try ./dev.py describe", file=sys.stderr)
        return 2
    rc = meta["fn"](extra)
    return 0 if rc == SKIPPED else rc


if __name__ == "__main__":
    sys.exit(main())
