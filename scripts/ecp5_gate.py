#!/usr/bin/env python3.15t
"""ECP5 gate: Diamond oracle scores vs a committed baseline (#123).

Steps (heavy lock held throughout, shared across worktrees):
  1. builds   Diamond designs x dies lacking a routed NCD + bit (reused otherwise)
  2. oracle   ecp5_diamond_oracle.py   (ncdread / ncd2nmc -> oracle.json)
  3. compare  ecp5_oracle_compare.py   (decode + lift vs oracle; cache keyed on code stamp)
  4. score    one table: pips / nets / connections / register clocks / sites
Headline per category = matched / (matched + missing + extra + wrong).
Verdict map: MATCH=matched; LIFT_MISSING, ORACLE_ONLY=missing; LIFT_ONLY=extra;
MISMATCH=wrong.  Fusion and split stay separate in compare.json, not here.

Baseline: tests/baselines/ecp5_oracle.json (per target and total).
FAIL (exit 1) when any target's missing/extra/wrong count in any category rises vs
baseline, or a baseline target is absent.  Exit 2 on a build / oracle / compare error.
New targets are listed (not failures) until --update-baseline records them.
Regression baselines are expected to move when a fault is fixed:
  python3.15t scripts/ecp5_gate.py --update-baseline   (after reviewing the table)

The nextpnr round-trip (ecp5_verify_all.py) is NOT part of this gate.

Usage: python3.15t scripts/ecp5_gate.py [--dies 25F 45F 85F] [--no-build] [--workers N]
           [--score-only] [--update-baseline] [--baseline PATH] [--out DIR]
Log:   tmp/logs/ecp5_gate.log
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, REPO)

CATS = ("pips", "nets", "connections", "register clocks", "sites")
FAULTS = ("missing", "extra", "wrong")
VERDICT_KIND = {"MATCH": "matched", "LIFT_MISSING": "missing", "ORACLE_ONLY": "missing",
                "LIFT_ONLY": "extra", "MISMATCH": "wrong"}
DEFAULT_BASELINE = os.path.join(REPO, "tests", "baselines", "ecp5_oracle.json")

# Stall = no CPU progress for 60 s (project rule for host processes).
# Overall = 3x measured cold worst: oracle batch 70 s (docs/ecp5-diamond-oracle.md),
# compare ~15 min with 85F sequential (same doc).  Expiry: step killed, logged, exit 2.
STALL_S = 60
ORACLE_OVERALL_S = 3 * 70
COMPARE_OVERALL_S = 3 * 15 * 60


def kinds(verdicts):
    """{verdict: n} -> {matched, missing, extra, wrong}."""
    out = dict.fromkeys(("matched",) + FAULTS, 0)
    for v, n in verdicts.items():
        if v not in VERDICT_KIND:
            raise ValueError(f"unknown verdict {v!r}")
        out[VERDICT_KIND[v]] += n
    return out


def target_counts(cj, headline):
    """compare.json dict -> {category: {matched, missing, extra, wrong}}."""
    h = headline(cj)
    return {cat: kinds(h[cat]["by_verdict"]) for cat in CATS}


def add(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in ("matched",) + FAULTS}


def total_of(c):
    return sum(c.values())


def pct(c):
    t = total_of(c)
    return 100.0 * c["matched"] / t if t else float("nan")


def totals(per_target):
    out = {cat: dict.fromkeys(("matched",) + FAULTS, 0) for cat in CATS}
    for counts in per_target.values():
        for cat in CATS:
            out[cat] = add(out[cat], counts[cat])
    return out


def diff(base_targets, cur_targets):
    """-> (regressions, improvements, new, missing_targets).
    regression = (target, category, kind, base, cur) with cur > base."""
    reg, imp = [], []
    for t in sorted(set(base_targets) & set(cur_targets)):
        for cat in CATS:
            for k in FAULTS:
                b, c = base_targets[t][cat][k], cur_targets[t][cat][k]
                if c > b:
                    reg.append((t, cat, k, b, c))
                elif c < b:
                    imp.append((t, cat, k, b, c))
    return (reg, imp, sorted(set(cur_targets) - set(base_targets)),
            sorted(set(base_targets) - set(cur_targets)))


def table(cur, base=None):
    rows = [f"{'category':<16}{'matched':>9}{'missing':>9}{'extra':>9}{'wrong':>9}"
            f"{'total':>9}{'headline':>10}  vs baseline"]
    for cat in CATS:
        c = cur[cat]
        note = ""
        if base is not None:
            b = base[cat]
            note = "  " + " ".join(f"{k}{c[k] - b[k]:+d}" for k in ("matched",) + FAULTS)
        rows.append(f"{cat:<16}{c['matched']:>9}{c['missing']:>9}{c['extra']:>9}"
                    f"{c['wrong']:>9}{total_of(c):>9}{pct(c):>9.1f}%{note}")
    return "\n".join(rows)


class Log:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.fh = open(path, "a")

    def _w(self, lvl, msg):
        line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {lvl} {msg}"
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()

    def info(self, fmt, *a):
        self._w("INFO", fmt % a if a else fmt)

    def error(self, fmt, *a):
        self._w("ERROR", fmt % a if a else fmt)


def git(*args):
    r = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)
    return r.stdout.strip()


def run_step(cmd, what, log, overall_s):
    import heavy_guard
    heavy_guard.wait_available(log, what)
    log.info("step %s: %s", what, " ".join(map(str, cmd[1:])))
    r = heavy_guard.run_stall_guarded(cmd, what, log, stall_s=STALL_S, overall_s=overall_s)
    for ln in (r.stdout or "").strip().splitlines()[-6:]:
        log.info("  | %s", ln)
    if r.returncode != 0:
        log.error("%s failed rc=%s %s", what, r.returncode, (r.stderr or "")[-600:])
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dies", nargs="+", default=["25F", "45F", "85F"])
    ap.add_argument("--no-build", action="store_true", help="skip step 1 (use what is on disk)")
    ap.add_argument("--score-only", action="store_true",
                    help="skip steps 1-3, score the compare.json files in --out")
    ap.add_argument("--workers", type=int, default=2, help="compare workers (RAM-bound)")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument("--out", default=os.path.join(REPO, "corpus", "ecp5", "diamond-oracle"))
    args = ap.parse_args()
    log = Log(os.path.join(REPO, "tmp", "logs", "ecp5_gate.log"))

    import heavy_guard
    import ecp5_diamond_build as B
    errors = []
    with heavy_guard.heavy_lock("ecp5_gate", log):
        if not args.score_only:
            if not args.no_build:
                failed = B.ensure_built(list(B.DESIGNS), args.dies, log)
                errors += [f"build failed: {f}" for f in failed]
            ok = run_step([sys.executable, os.path.join(SCRIPTS, "ecp5_diamond_oracle.py"),
                           "--out", args.out], "oracle", log, ORACLE_OVERALL_S)
            if not ok:
                errors.append("oracle step failed")
            ok = run_step([sys.executable, os.path.join(SCRIPTS, "ecp5_oracle_compare.py"),
                           "--out", args.out, "--workers", str(args.workers)],
                          "compare", log, COMPARE_OVERALL_S)
            if not ok:
                errors.append("compare step failed")

    import ecp5_oracle_compare as C
    stamp = C.CODE_STAMP
    for name in ("_batch_summary.json", "_compare_summary.json"):
        p = os.path.join(args.out, name)
        if os.path.exists(p):
            with open(p) as fh:
                s = json.load(fh)
            for f in s.get("failed", []):
                errors.append(f"{name}: {f[0]}: {f[1]}")

    cur = {}
    for t in sorted(os.listdir(args.out)):
        if not os.path.exists(os.path.join(args.out, t, "oracle.json")):
            continue
        p = os.path.join(args.out, t, "compare.json")
        try:
            with open(p) as fh:
                cj = json.load(fh)
        except (OSError, ValueError):
            errors.append(f"{t}: no compare.json")
            continue
        if cj.get("code_stamp") != stamp or cj.get("schema_version") != C.SCHEMA_VERSION:
            errors.append(f"{t}: compare.json is from other code (stale)")
            continue
        cur[t] = target_counts(cj, C.headline)

    cur_tot = totals(cur)
    base = None
    if os.path.exists(args.baseline):
        with open(args.baseline) as fh:
            base = json.load(fh)
    reg, imp, new, gone = ([], [], [], [])
    if base:
        reg, imp, new, gone = diff(base["targets"], cur)
        common = set(base["targets"]) & set(cur)
        log.info("targets: %d scored, %d in baseline, %d new, %d absent", len(cur),
                 len(base["targets"]), len(new), len(gone))
        log.info("TOTALS over the %d common targets (delta vs baseline)\n%s", len(common),
                 table(totals({t: cur[t] for t in common}),
                       totals({t: base["targets"][t] for t in common})))
        if new:
            log.info("NEW targets (not in baseline): %d\n%s", len(new),
                     table(totals({t: cur[t] for t in new})))
    else:
        log.info("no baseline at %s", args.baseline)
    log.info("TOTALS over all %d scored targets\n%s", len(cur), table(cur_tot))

    if args.update_baseline:
        if errors:
            log.error("not updating baseline with errors present")
        else:
            doc = {"meta": {
                "date": datetime.now().astimezone().date().isoformat(),
                "commit": git("rev-parse", "HEAD"),
                "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
                "oracle": "Diamond 3.14 NCD via ncdread + ncd2nmc (scripts/ecp5_diamond_oracle.py)",
                "conditions": "scripts/ecp5_gate.py defaults: all Diamond corpus builds "
                              "(dies 25F/45F/85F) + diamond-fuzz targets with a routed NCD; "
                              f"compare code stamp {stamp}",
                "headline": "matched / (matched + missing + extra + wrong)",
                "verdict_map": VERDICT_KIND,
                "targets": len(cur)},
                "totals": cur_tot, "targets": cur}
            os.makedirs(os.path.dirname(args.baseline), exist_ok=True)
            with open(args.baseline, "w") as fh:
                fh.write("{\n" + json.dumps("meta") + ": " + json.dumps(doc["meta"], indent=1) + ",\n"
                         + json.dumps("totals") + ": " + json.dumps(cur_tot, sort_keys=True) + ",\n"
                         + json.dumps("targets") + ": {\n"
                         + ",\n".join(f" {json.dumps(t)}: {json.dumps(cur[t], sort_keys=True)}"
                                      for t in sorted(cur)) + "\n}\n}\n")
            log.info("baseline written: %s (%d targets)", args.baseline, len(cur))
        return 2 if errors else 0

    for e in errors:
        log.error("ERROR %s", e)
    for t, cat, k, b, c in reg[:40]:
        log.error("REGRESSION %s %s %s: %d -> %d", t, cat, k, b, c)
    if len(reg) > 40:
        log.error("... %d more regressions", len(reg) - 40)
    for t in gone:
        log.error("REGRESSION %s: in baseline, absent from this run", t)
    if imp:
        log.info("improvements: %d (target, category, kind) cells fell", len(imp))
    if errors:
        log.error("GATE ERROR: %d errors", len(errors))
        return 2
    if reg or gone:
        log.error("GATE FAIL: %d fault cells rose, %d targets absent", len(reg), len(gone))
        return 1
    if base is None:
        log.error("GATE FAIL: no baseline (run --update-baseline to record one)")
        return 1
    log.info("GATE PASS: no fault category rose vs baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
