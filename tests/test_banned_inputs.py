"""Banned inputs of the clean Cyclone IV pipeline (docs/cycloneiv-clean-pipeline.md).

1. The clean tree (lifters/cycloneiv_clean, tests/cycloneiv_clean, scripts/cycloneiv_clean_*.py) must not mention any banned identifier.
2. Repo-wide: tracked .py files must not mention them either, except under LEGACY_PATHS (retirement P4 done; old code: tag pre-clean-cycloneiv).
"""
import glob
import os
import re
import subprocess


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANNED = ["afx_map", "asm_to_plane_afx", "lab_vx", "Ddb.cm", "HOP_OVERRIDE", "R4_COLTABLE", "COORD_V2", "RELAX_ACTIVE",
          "asm_names", "li_map", "phys_map", "coltable", "EXC4", "cycloneiv_asm_decode", "cycloneiv_phys_trace",
          "cycloneiv_ddb_trace"]
# repo-relative prefixes allowed to keep banned identifiers (archived code only)
LEGACY_PATHS = ("debris/",)
THIS = os.path.join("tests", "test_banned_inputs.py")


def tracked_py():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\n") if p]


def clean_tree():
    pats = ["lifters/cycloneiv_clean/**/*.py", "tests/cycloneiv_clean/**/*.py", "scripts/cycloneiv_clean_*.py"]
    files = set()
    for pat in pats:
        files.update(os.path.relpath(p, REPO) for p in glob.glob(os.path.join(REPO, pat), recursive=True))
    return sorted(files)


def hits(paths):
    rx = re.compile("|".join(re.escape(b) for b in BANNED))
    out = []
    for p in paths:
        try:
            text = open(os.path.join(REPO, p), encoding="utf-8", errors="replace").read()
        except FileNotFoundError:       # tracked but deleted in the working tree
            continue
        for n, line in enumerate(text.split("\n"), 1):
            m = rx.search(line)
            if m:
                out.append(f"{p}:{n}: {m.group(0)}")
    return out


def test_clean_tree_has_no_banned_identifiers():
    files = clean_tree()
    assert files, "clean tree is empty"
    found = hits(files)
    assert not found, "banned identifiers in the clean tree:\n" + "\n".join(found)


def test_repo_wide_outside_legacy():
    files = [p for p in tracked_py() if p != THIS and not p.startswith(tuple(LEGACY_PATHS))]
    found = hits(files)
    assert not found, "banned identifiers outside the legacy paths:\n" + "\n".join(found)
