#!/usr/bin/env python3.15t
"""Run machxo2_oracle_compare.py over the old fuzz corpus + construct + coverage
corpora (one at a time) and print the combined fault headline.

Each set: <work>/<set>/<target>/oracle.json (copies); bitstreams read from the
set's targets dir.  Results kept per tag in <work>/results/<tag>/.

Usage: python3.15t scripts/machxo2_oracle_all.py --tag after --work tmp/ocmp \
           --set old=/path/targets --set constructs=/path --set coverage=/path
       python3.15t scripts/machxo2_oracle_all.py --tag after --work tmp/ocmp --report-only
Log:   tmp/logs/machxo2_oracle_all.log
"""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import heavy_guard  # noqa: E402

LOG_PATH = os.path.join(REPO, "tmp", "logs", "machxo2_oracle_all.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler(LOG_PATH)])
log = logging.getLogger("oracle_all")

SETS = ("old", "constructs", "coverage")
RULES = ("h06e_right_mirror", "right_stub_drop", "h06w_left_mirror",
         "h_right_flip", "h_left_flip", "left_stub_drop", "walkback_hstub")


def run(tag, work, sets, workers):
    res_dir = os.path.join(work, "results", tag)
    os.makedirs(res_dir, exist_ok=True)
    for name, tdir in sets.items():
        heavy_guard.wait_available(log, f"compare {name}")
        out = os.path.join(work, name)
        cmd = [sys.executable, os.path.join(HERE, "machxo2_oracle_compare.py"),
               "--targets-dir", tdir, "--out", out, "--workers", str(workers)]
        log.info("run %s", " ".join(cmd))
        with open(os.path.join(res_dir, f"{name}.log"), "w") as fh:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT).returncode
        if rc != 0:
            log.error("compare %s exited %d (see %s.log)", name, rc, name)
            sys.exit(1)
        shutil.copy(os.path.join(out, "_compare_summary.json"),
                    os.path.join(res_dir, f"{name}.json"))


def report(tag, work):
    res_dir = os.path.join(work, "results", tag)
    S = {n: json.load(open(os.path.join(res_dir, f"{n}.json"))) for n in SETS
         if os.path.exists(os.path.join(res_dir, f"{n}.json"))}
    out = {"tag": tag, "sets": {}}

    def sums(sel):
        pips, nets, clk, gk, failed = {}, {}, {}, {}, 0
        for n in sel:
            s = S[n]
            failed += len(s["failed"])
            for k, v in s["pips"].items():
                pips[k] = pips.get(k, 0) + v
            for k, v in s["net_verdicts"].items():
                nets[k] = nets.get(k, 0) + v
            for k, v in s["site_field_verdicts"].items():
                if k.startswith("FF#.lift.clk:"):
                    c = k.split(":")[1]
                    clk[c] = clk.get(c, 0) + v
                elif k == "FF#.lift:LIFT_MISSING":   # register absent from the lift
                    clk["LIFT_MISSING_FF"] = clk.get("LIFT_MISSING_FF", 0) + v
            for k, v in s["gkey_verdicts"].items():
                gk[k] = gk.get(k, 0) + v
        return {"pips": pips, "nets": nets, "reg_clock": clk, "gkey": gk,
                "failed_targets": failed}

    for label, sel in [("ALL", list(S))] + [(n, [n]) for n in S]:
        out["sets"][label] = sums(sel)
    with open(os.path.join(res_dir, "headline.json"), "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    for label, d in out["sets"].items():
        print(f"== {tag} / {label}  (failed targets: {d['failed_targets']})")
        for cat in ("pips", "nets", "reg_clock"):
            c = d[cat]
            tot, ok = sum(c.values()), c.get("MATCH", 0)
            pct = 100.0 * ok / tot if tot else 0.0
            print(f"  {cat:10s} {ok}/{tot} = {pct:.2f}%  {dict(sorted(c.items()))}")
    print(f"== {tag} per-rule (ALL sets)")
    gk = out["sets"]["ALL"]["gkey"]
    for r in RULES:
        print(f"  {r:20s} " + "  ".join(
            f"{v}={gk.get(f'{r}:{v}', 0)}" for v in ("AGREE", "DISAGREE", "INCONCLUSIVE")))


@heavy_guard.locked("machxo2_oracle_all")
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--work", default=os.path.join(REPO, "tmp", "ocmp"))
    ap.add_argument("--set", action="append", default=[], metavar="NAME=TARGETS_DIR")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    a.work = os.path.abspath(a.work)
    if not a.report_only:
        run(a.tag, a.work, dict(s.split("=", 1) for s in a.set), a.workers)
    report(a.tag, a.work)


if __name__ == "__main__":
    main()
