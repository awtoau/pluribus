"""Fails if a claim listed WRONG in docs/reversing-errata.md (```errata-banned block) reappears in a tracked file."""
import os
import re
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(REPO, "docs", "reversing-errata.md")
SUFFIXES = (".md", ".py", ".tsv", ".java")


def _block(name):
    text = open(DOC, encoding="utf-8").read()
    m = re.search(r"```" + name + r"\n(.*?)```", text, re.S)
    assert m, f"no {name} block in docs/reversing-errata.md"
    return [ln for ln in m.group(1).split("\n") if ln.strip() and not ln.startswith("#")]


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\n") if p.endswith(SUFFIXES)]


def test_banned_claims_absent():
    pats = []
    for ln in _block("errata-banned"):
        rx, _, why = ln.partition("\t")
        pats.append((re.compile(rx), why or rx))
    assert pats
    allow = set(_block("errata-allow"))
    found = []
    for p in _tracked():
        if p in allow or p.startswith(("debris/", "docs/coverage-history")):
            continue
        try:
            lines = open(os.path.join(REPO, p), encoding="utf-8", errors="replace").read().split("\n")
        except FileNotFoundError:
            continue
        for n, line in enumerate(lines, 1):
            for rx, why in pats:
                if rx.search(line):
                    found.append(f"{p}:{n}: {why}")
    assert not found, "claims declared WRONG in docs/reversing-errata.md reappear:\n" + "\n".join(found)
