#!/usr/bin/env python3.15t
"""Run the MachXO2 Diamond-oracle comparison over every corpus set, serially, and print one headline.

    python3.15t scripts/machxo2_gate.py --tag base [--workers 4] [--sets old constructs coverage globals]
    python3.15t scripts/machxo2_gate.py --diff base after

Sets: old = diamond-fuzz (2779), constructs, coverage, globals (multi-clock / secondary-control designs).
Per-set summaries land in tmp/ocmp/<tag>/<set>.json. Headline counts every non-MATCH as a fault.
Each set is one machxo2_oracle_compare.py run (it holds the heavy lock and the RAM gate itself).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = {
    "old": ("diamond-fuzz/targets", "corpus/machxo2/diamond-fuzz"),
    "constructs": ("corpus/machxo2/constructs",) * 2,
    "coverage": ("corpus/machxo2/coverage",) * 2,
    "globals": ("corpus/machxo2/globals",) * 2,
}


def _field(s, name):
    r = {}
    for k, v in s["site_field_verdicts"].items():
        if k.startswith(name + ":"):
            r[k.split(":")[1]] = v
    return r


def headline(s):
    pips, nets = s["pips"], s["net_verdicts"]
    out = {"pips": (pips.get("MATCH", 0), sum(pips.values())),
           "nets": (nets.get("MATCH", 0), sum(nets.values()))}
    for key, fld in (("reg_clock", "FF#.lift.clk"), ("reg_ce", "FF#.lift.ce"),
                     ("reg_lsr", "FF#.lift.lsr"), ("reg_d", "FF#.lift.d")):
        f = _field(s, fld)
        out[key] = (f.get("MATCH", 0), sum(f.values()))
    return out


def load(tag):
    d = os.path.join(REPO, "tmp", "ocmp", tag)
    return {n: json.load(open(os.path.join(d, n + ".json")))
            for n in DIRS if os.path.exists(os.path.join(d, n + ".json"))}


def gate_results(S):
    """{set: {category: {matched, missing, extra, wrong}}} for provenance.corpus.record_gate_run."""
    results = {}
    for name, s in S.items():
        h = headline(s)
        r = results[name] = {k: {"matched": a, "missing": b - a, "extra": 0, "wrong": 0} for k, (a, b) in h.items()}
        # pips/nets verdict split (MISMATCH -> wrong)
        for sec, cat in (("pips", "pips"), ("net_verdicts", "nets")):
            v = s.get(sec, {})
            r[cat] = {"matched": v.get("MATCH", 0), "wrong": v.get("MISMATCH", 0),
                      "missing": sum(n for k, n in v.items() if k not in ("MATCH", "MISMATCH") and "ONLY" not in k and "EXTRA" not in k),
                      "extra": sum(n for k, n in v.items() if "LIFT_ONLY" in k or "EXTRA" in k)}
    return results


def record(tag):
    """Write this tag's results to the machxo2 provenance DB (databases/machxo2/provenance.db unless
    PLURIBUS_SQLITE_PATH is set). Needs the sets declared as corpus members: claims_register.py --family machxo2."""
    os.environ.setdefault("PLURIBUS_SQLITE_PATH", os.path.join(REPO, "databases", "machxo2", "provenance.db"))
    sys.path.insert(0, REPO)
    import db
    import schema
    from provenance import corpus as C
    from provenance import evidence_io as E
    S = load(tag)
    if not S:
        return None
    schema.init()
    with db.engine().begin() as conn:
        E.ensure_family(conn, "machxo2")
        return C.record_gate_run(conn, "machxo2", "scripts/machxo2_gate.py", E.git_head(REPO), gate_results(S),
                                 params={"tag": tag}, summary={"note": "per-set aggregate; per-design results in corpus/machxo2/*/_compare_summary.json"})


def show(tag):
    S = load(tag)
    tot = {}
    print(f"== {tag}")
    for n, s in S.items():
        h = headline(s)
        print(f"  {n:11s} failed={len(s['failed'])} " + "  ".join(f"{k} {a}/{b}" for k, (a, b) in h.items()))
        for k, (a, b) in h.items():
            t = tot.setdefault(k, [0, 0])
            t[0] += a
            t[1] += b
    print("  ALL         " + "  ".join(f"{k} {a}/{b} = {100.0 * a / b if b else 0:.2f}%"
                                      for k, (a, b) in tot.items()))
    return S


def diff(a, b):
    A, B = load(a), load(b)
    for n in A:
        if n not in B:
            continue
        for sec in ("pips", "net_verdicts", "site_field_verdicts", "gkey_verdicts"):
            ka, kb = A[n][sec], B[n][sec]
            for k in sorted(set(ka) | set(kb)):
                if ka.get(k, 0) != kb.get(k, 0):
                    print(f"  {n:11s} {sec}.{k}: {ka.get(k, 0)} -> {kb.get(k, 0)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sets", nargs="*", default=list(DIRS))
    ap.add_argument("--old-targets", help="dir holding the old fuzz targets' impl1/*.bit (untracked; "
                    "a worktree lacks them: point at the main checkout)")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"))
    a = ap.parse_args()
    if a.diff:
        show(a.diff[0])
        show(a.diff[1])
        diff(*a.diff)
        return 0
    od = os.path.join(REPO, "tmp", "ocmp", a.tag)
    os.makedirs(od, exist_ok=True)
    for n in a.sets:
        tdir, out = DIRS[n]
        if n == "old" and a.old_targets:
            tdir = a.old_targets
        cmd = [sys.executable, os.path.join(REPO, "scripts", "machxo2_oracle_compare.py"),
               "--targets-dir", os.path.join(REPO, tdir), "--out", os.path.join(REPO, out),
               "--workers", str(a.workers)]
        with open(os.path.join(od, n + ".log"), "w") as fh:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT).returncode
        if rc:
            print(f"compare {n} exit {rc}; see {od}/{n}.log")
            return 1
        shutil.copy(os.path.join(REPO, out, "_compare_summary.json"), os.path.join(od, n + ".json"))
    show(a.tag)
    try:
        print(f"provenance gate_run {record(a.tag)}")
    except SystemExit as e:   # stale/missing provenance DB must not lose a finished gate; results stay in tmp/ocmp/<tag>
        print(f"provenance NOT recorded ({e}); fix the DB, then: claims_register.py --family machxo2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
