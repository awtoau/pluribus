"""Rules ledger (reference/rules.tsv): every Cyclone IV clean decoder rule/table has a row with a vendor-code status (#165)."""
import ast
import csv
import glob
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(REPO, "reference", "rules.tsv")
TREE = os.path.join(REPO, "lifters", "cycloneiv_clean")
STATUSES = {"CONFIRMED_BY_CODE", "SPECIMEN_ONLY", "CODE_CONTRADICTS", "UNKNOWN"}
DERIVATIONS = {"CODE", "SPECIMEN", "MIXED"}
COLUMNS = ["id", "module", "rule", "derivation", "source", "corpus_check", "status", "notes"]


def _rows():
    with open(LEDGER, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def test_ledger_parses():
    rows = _rows()
    assert rows and list(rows[0].keys()) == COLUMNS
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for r in rows:
        assert None not in r and None not in r.values(), r["id"]
        assert r["rule"] and r["source"], r["id"]


def test_every_row_has_status():
    for r in _rows():
        assert r["status"] in STATUSES, (r["id"], r["status"])
        assert r["derivation"] in DERIVATIONS, (r["id"], r["derivation"])


def test_code_contradicts_has_errata_row():
    errata = open(os.path.join(REPO, "docs", "reversing-errata.md")).read()
    for r in _rows():
        if r["status"] == "CODE_CONTRADICTS":
            assert r["id"] in errata, f"{r['id']}: CODE_CONTRADICTS needs an errata row naming the ledger id"


def test_every_module_and_table_file_in_ledger():
    mods = {r["module"] for r in _rows()}
    want = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(TREE, "*.py"))} - {"__init__"}
    want |= {os.path.basename(p) for p in glob.glob(os.path.join(TREE, "*.json"))}
    assert not (want - mods), f"modules/tables without a ledger row: {sorted(want - mods)}"


def _rule_tables():
    """Module-level UPPERCASE names bound to a dict/tuple/list/set literal: the rule tables."""
    out = {}
    for p in sorted(glob.glob(os.path.join(TREE, "*.py"))):
        for n in ast.parse(open(p).read()).body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                nm = n.targets[0].id
                if nm.isupper() and isinstance(n.value, (ast.Dict, ast.Tuple, ast.List, ast.Set)):
                    out.setdefault(nm, []).append(os.path.basename(p))
    return out


def test_every_rule_table_in_ledger():
    text = open(LEDGER).read()
    missing = {k: v for k, v in _rule_tables().items() if k not in text}
    assert not missing, f"module-level rule tables not named in reference/rules.tsv: {missing}"


def test_source_tags_name_a_ledger_module():
    # every module that carries `# source:` tags must be a ledger module (tag -> ledger pointer)
    mods = {r["module"] for r in _rows()}
    for p in glob.glob(os.path.join(TREE, "*.py")):
        if "source:" in open(p).read():
            assert os.path.splitext(os.path.basename(p))[0] in mods, p


def test_specimen_only_queue():
    """Visible queue: SPECIMEN_ONLY rows still lack a code reading (xfail with the count, never a hard fail)."""
    rows = _rows()
    q = [r for r in rows if r["status"] == "SPECIMEN_ONLY"]
    counts = {s: sum(r["status"] == s for r in rows) for s in sorted(STATUSES)}
    if q:
        pytest.xfail(f"{len(q)} SPECIMEN_ONLY rules without a code reading; ledger {counts}; ids: " + " ".join(r["id"] for r in q))
