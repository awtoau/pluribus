#!/usr/bin/env python3.15t
"""Catalogue of the EP4CGX150 corpus: one row per design family (name prefix) -> reference/corpus_catalog.tsv.

  python3.15t scripts/cycloneiv_corpus_catalog.py      # log: tmp/logs/cycloneiv_corpus_catalog.log
Columns: family, designs, purpose (first design.toml purpose), exercises, generator (scripts naming the prefix),
built_ok, dup_extra (designs whose bitstream equals another design's), ignored_assign (fitter ignored a placement: node missing),
unplaced_pins (critical warning 169085: pins without a location), in_evidence (used as a specimen-pair base/spec), in_gate (gate run 26 members).
Sources: design.toml, rebuild.json (rbf_sha256), logs/quartus_fit.log warnings, databases/cycloneiv/gx150.db.rebuild evidence build ids, gate_results run 26.
"""
import collections
import json
import logging
import os
import re
import sqlite3
import tomllib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(REPO, "corpus", "cycloneiv")
OUT = os.path.join(REPO, "reference", "corpus_catalog.tsv")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_corpus_catalog.log")
RUN = 26        # gate run on run 14's member set (docs/cycloneiv-clean-pipeline.md, gate regression hygiene)


def family(d):
    return d.split("_")[0]


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
    sha = collections.defaultdict(list)
    info = {}
    for d in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, d)
        if not os.path.isdir(p):
            continue
        rec = {"purpose": "", "exercises": [], "ok": False, "sha": None, "ignored": False, "unplaced": False}
        try:
            t = tomllib.loads(open(os.path.join(p, "design.toml")).read())
            rec["purpose"], rec["exercises"] = t.get("purpose", ""), t.get("exercises", [])
        except Exception:
            pass
        try:
            j = json.load(open(os.path.join(p, "rebuild.json")))
            rec["ok"], rec["sha"] = j.get("status") == "ok", j.get("rbf_sha256")
        except Exception:
            rec["ok"] = os.path.exists(os.path.join(p, "bitstream.rbf"))
        try:
            fit = open(os.path.join(p, "logs", "quartus_fit.log"), errors="replace").read()
            rec["ignored"], rec["unplaced"] = "(15706)" in fit, "(169085)" in fit
        except Exception:
            pass
        if rec["sha"]:
            sha[rec["sha"]].append(d)
        info[d] = rec
    extra = {d for v in sha.values() if len(v) > 1 for d in sorted(v)[1:]}
    ev, gate = set(), set()
    snap = os.path.join(REPO, "databases", "cycloneiv", "gx150.db.rebuild")
    if os.path.exists(snap):
        c = sqlite3.connect(snap)
        names = dict(c.execute("select id, design from corpus_builds"))
        for b, s in c.execute("select build_base, build_spec from evidence where kind='specimen-pair'"):
            ev.update(names[x] for x in (b, s) if x in names)
    c = sqlite3.connect(os.path.join(REPO, "databases", "cycloneiv", "gx150.db"))
    gate = {r[0].split("@")[0] for r in c.execute(
        "select cm.name from gate_results g join corpus_members cm on cm.id = g.member_id where g.run_id = ?", (RUN,))}
    scripts = {f: open(os.path.join(REPO, "scripts", f), errors="replace").read() for f in os.listdir(os.path.join(REPO, "scripts")) if f.endswith(".py")}
    fam = collections.defaultdict(list)
    for d in info:
        fam[family(d)].append(d)
    rows = []
    for f, ds in sorted(fam.items(), key=lambda kv: -len(kv[1])):
        gen = sorted(s for s, txt in scripts.items() if re.search(r"['\"]%s_" % re.escape(f), txt) or re.search(r"['\"]%s['\"]" % re.escape(f), txt))
        ex = sorted({e for d in ds for e in info[d]["exercises"]})
        purpose = next((info[d]["purpose"] for d in ds if info[d]["purpose"]), "")
        rows.append([f, len(ds), purpose.replace("\t", " ")[:110], ",".join(ex), ",".join(gen[:3]), sum(info[d]["ok"] for d in ds),
                     sum(d in extra for d in ds), sum(info[d]["ignored"] for d in ds), sum(info[d]["unplaced"] for d in ds),
                     sum(d in ev for d in ds), sum(d in gate for d in ds)])
    with open(OUT, "w") as f:
        f.write("\t".join(["family", "designs", "purpose", "exercises", "generator", "built_ok", "dup_extra", "ignored_assign",
                           "unplaced_pins", "in_evidence", "in_gate"]) + "\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")
    logging.info("%d designs, %d families -> %s", len(info), len(rows), OUT)


if __name__ == "__main__":
    main()
