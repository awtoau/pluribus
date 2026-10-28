"""Pluribus code parallelises with threads (python3.15t), never processes (#149).

Fails if a tracked .py file imports multiprocessing / a ProcessPoolExecutor / forks.
External EDA tools run as subprocesses; that is not a process pool and is not matched here.
"""
import ast
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# path -> reason; every entry is a documented exception
ALLOW = {}
SKIP_PREFIX = ("debris/",)  # retired code, never run
BANNED_MODULES = {"multiprocessing", "concurrent.futures.process"}
BANNED_NAMES = {"ProcessPoolExecutor"}
BANNED_CALLS = {("os", "fork"), ("os", "forkpty")}


def tracked_py():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True, check=True)
    return [p for p in out.stdout.splitlines()
            if p != "tests/test_threads_only.py" and not p.startswith(SKIP_PREFIX) and (REPO / p).exists()]


def violations(path):
    try:
        tree = ast.parse((REPO / path).read_text(), filename=path)
    except SyntaxError:
        return []
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            found += [f"import {a.name}" for a in n.names if a.name.split(".")[0] == "multiprocessing"
                      or a.name in BANNED_MODULES]
        elif isinstance(n, ast.ImportFrom):
            m = n.module or ""
            if m.split(".")[0] == "multiprocessing" or m in BANNED_MODULES:
                found.append(f"from {m} import ...")
            found += [f"from {m} import {a.name}" for a in n.names if a.name in BANNED_NAMES]
        elif isinstance(n, ast.Attribute) and n.attr in BANNED_NAMES:
            found.append(f".{n.attr}")
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and isinstance(n.func.value, ast.Name) and (n.func.value.id, n.func.attr) in BANNED_CALLS):
            found.append(f"{n.func.value.id}.{n.func.attr}()")
    return found


def test_no_process_parallelism():
    bad = {p: v for p in tracked_py() if p not in ALLOW and (v := violations(p))}
    assert not bad, f"process-based parallelism (use threads, docs/memory-budget.md): {bad}"


def test_allow_list_entries_are_still_needed():
    stale = [p for p in ALLOW if not violations(p)]
    assert not stale, f"allow-list entries with no violation left: {stale}"
