"""Provenance rule (#165): every module-level dict/list/tuple/set constant with more than 3 entries in
lifters/cycloneiv_clean/ has a `source:` tag within 2 lines above it (vendor file/function, or the oracle test that
validated it).  Data files: every names_table.json entry carries a non-empty `source`."""
import ast
import glob
import json
import os

from conftest import REPO

PKG = os.path.join(REPO, "lifters", "cycloneiv_clean")
MAX_UNTAGGED = 3


def untagged(path):
    text = open(path).read()
    lines = text.splitlines()
    out = []
    for node in ast.parse(text).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            v = node.value
            n = len(v.keys) if isinstance(v, ast.Dict) else len(v.elts) if isinstance(v, (ast.List, ast.Tuple, ast.Set)) else 0
            if n > MAX_UNTAGGED:
                above = lines[max(0, node.lineno - 3):node.lineno - 1]
                if not any("source:" in l for l in above):
                    out.append((os.path.basename(path), node.lineno))
    return out


def test_constants_have_source_tags():
    bad = [b for f in sorted(glob.glob(os.path.join(PKG, "*.py"))) for b in untagged(f)]
    assert not bad, f"constant tables without a 'source:' tag within 2 lines above: {bad}"


def test_names_table_entries_have_source():
    path = os.path.join(PKG, "names_table.json")
    d = json.load(open(path))
    assert d["types"] and d["hdr_names"]
    assert all(e.get("source") for e in d["types"]) and all(e.get("source") for e in d["hdr_names"])
