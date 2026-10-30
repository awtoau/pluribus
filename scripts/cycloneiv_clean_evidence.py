#!/usr/bin/env python3.15t
"""Record the evidence rows behind the clean-decoder inventory classes (1a, 8a-8g, 9a-9c) in the family DB (#169).

  PLURIBUS_SQLITE_PATH=databases/cycloneiv/gx150.db python3.15t scripts/cycloneiv_clean_evidence.py
Evidence rows are PRIMARY data (never wiped by claims_register.py); this script is idempotent on (kind, name, source_ref).  Tiers are not
decided here: scripts/claims_register.py links the rows to class claims, provenance/tiering.py computes the tier.
Sources (local, regenerable): gate_runs/gate_results (DB), tmp/cycloneiv_clean/{fields_pairs.json, reg_pairs/*, lut_specimens/*},
databases/cycloneiv/{io_pairs.json, io_decode.json}, tmp/logs/cycloneiv_clean_oracles.log.  Log: tmp/logs/cycloneiv_clean_evidence.log
"""
import json
import logging
import os
import re
import sys

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import db  # noqa: E402
import schema as S  # noqa: E402
from provenance import evidence_io as E  # noqa: E402
from sqlalchemy import select  # noqa: E402

FAM, DEV = "cycloneiv", "EP4CGX150"
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_evidence.log")
GATE = "scripts/cycloneiv_clean_gate.py"
log = logging.getLogger("clean_evidence")


def gate_rows(conn, commit):
    """One oracle-compare row per category of the latest full-corpus gate run (headline variant vendor, baseline False)."""
    runs = conn.execute(select(S.gate_runs).where(S.gate_runs.c.script == GATE).order_by(S.gate_runs.c.id.desc())).fetchall()
    run = next((r for r in runs if (r.params or {}).get("set") == "corpus" and not (r.params or {}).get("baseline")), None)
    if run is None:
        db.die("no non-baseline corpus gate run in gate_runs")
    n = 0
    for cat, c in run.summary["totals"].items():
        tot = sum(c.values())
        digest = dict(run_id=run.id, run_commit=run.commit, designs=run.params.get("designs"), category=cat, **c,
                      headline_pct=round(100.0 * c["matched"] / tot, 3) if tot else None, variant=run.params.get("headline_variant"),
                      oracle="Quartus routing.rcf / postfit.vo / build.pin of each design", meta={})
        E.record_decode(conn, FAM, DEV, f"clean gate run {run.id} {cat}", digest, commit, GATE, generator=GATE,
                        n_objects=tot, kind="oracle-compare")
        n += 1
    log.info("gate run %d: %d category rows", run.id, n)


def lut_specimens(conn, commit):
    """O1 on 1,023 Quartus-built LUT specimens (scripts/cycloneiv_clean_lut_specimens.py): exact set per site, no added constant."""
    text = open(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_oracles.log")).read()
    spec = re.findall(r"^O1-specimens (\{.*\})$", text, re.M)[-1]
    spec = json.loads(spec)
    hyp = [json.loads(m) for m in re.findall(r"^O1-hyp (\{.*\})$", text, re.M)]
    ok = next(h for h in hyp if h["sx"] == 1 and h["sy"] == 1 and h["frame_const"] == 0 and h["v_const"] == 0)
    if not (spec["cells"] == ok["votes"] and ok["sites_ok"] == spec["sites"] and spec["stray_cells"] == 0):
        db.die(f"O1 specimen log does not close: {spec} {ok}")
    digest = dict(sites=spec["sites"], columns=spec["columns"], rows=spec["rows"], les=spec["les"], cells=spec["cells"],
                  matched=ok["votes"], missing=0, extra=spec["stray_cells"], wrong=0,
                  oracle="Quartus post-fit lut_mask per specimen LE", law="(hi + dx) * 6154 + lo + dy, no sign flip, no constant", meta={})
    E.record_decode(conn, FAM, DEV, "LUT INIT specimens: 1,023 sites, 16,368 cells, exact per site (asmdb LE_LUT_FUNCTION)", digest, commit,
                    "scripts/cycloneiv_clean_lut_specimens.py", generator="scripts/cycloneiv_clean_lut_specimens.py",
                    n_objects=spec["cells"], kind="oracle-compare")
    log.info("LUT specimens row: %s", digest)


def field_pairs(conn, commit):
    d = json.load(open(os.path.join(REPO, "tmp", "cycloneiv_clean", "fields_pairs.json")))
    src = "scripts/cycloneiv_clean_fields_pairs.py"
    for blk, rows in d.items():
        for r in rows:
            site = r["site"]
            name = f"fields pair {blk} {r['variant']} vs {r['base']} X{site[0]}Y{site[1]}"
            E.record_decode(conn, FAM, DEV, name, dict(r, block=blk, meta={"site": site[:2], "group_key": r.get("ctl", "ram")}),
                            commit, src, generator=src, n_objects=int(r["diff"]), kind="audit")
    log.info("field pair rows: LAB %d, M9K %d", len(d["lab"]), len(d["m9k"]))


def reg_pairs(conn, commit):
    base = os.path.join(REPO, "tmp", "cycloneiv_clean", "reg_pairs")
    sites = json.load(open(os.path.join(base, "sites.json")))
    obs = json.load(open(os.path.join(base, "observed.json")))
    labs = sorted({(f[0], f[1]) for f in sites["feat"]})
    src = "scripts/cycloneiv_clean_reg_pairs.py"
    digest = dict(pairs=len(obs), feature_sites=len(sites["feat"]), labs=[list(x) for x in labs],
                  kinds={k: sum(1 for f in sites["feat"] if f[3] == k) for k in "ACD"}, meta={})
    E.record_decode(conn, FAM, DEV, "register-used pair specimens: LE state table over the specimen LABs", digest, commit, src,
                    generator=src, n_objects=len(obs), kind="audit")
    log.info("reg pair row: %s", digest)


def io_rows(conn, commit):
    """Per (field, pin) CFF pair evidence at the sites where a pair build toggled bits inside the field's asmdb group."""
    import cycloneiv_clean_classes as C
    import lifters.cycloneiv_clean.io_decode as D
    from lifters.cycloneiv_clean import cycloneiv_io as IO
    chain, pairs = D.Chain(), IO.io_pairs()
    io = C.io_sets(chain, pairs)
    src = "scripts/cycloneiv_clean_io_pairs.py"
    conn_n = 0
    for r in io["rows"]:
        meta = {"group_key": r["field"]}
        if r["rank"] is not None:
            meta["site"] = [r["rank"], 0]          # ring position (anchors increase monotonically around the IO ring, io.md Findings)
        E.record_decode(conn, FAM, DEV, f"io pair {r['field']} {r['pin']}",
                        dict(field=r["field"], pin=r["pin"], io_site=r["site"], matched_bits=r["matched"], group_bits=r["group_bits"],
                             cff_bits=r["bits"], meta=meta), commit, src, generator=src, n_objects=r["matched"], kind="audit")
        conn_n += 1
    E.record_decode(conn, FAM, DEV, "io ring: IO sites with a SET_SLEW_RATE group, ordered by anchor",
                    dict(sites=io["n_sites"], tested=len(io["tested"]), tested_ranks=sorted(io["rank"][s] for s in io["tested"] if s in io["rank"]),
                         meta={}), commit, "lifters/cycloneiv_clean/io_decode.py", generator="scripts/cycloneiv_clean_classes.py",
                    n_objects=io["n_sites"], kind="vendor-decode")
    log.info("io rows %d; ring %d sites, %d tested", conn_n, io["n_sites"], len(io["tested"]))


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG, "w")])
    commit = E.git_head()
    with db.engine().begin() as conn:
        gate_rows(conn, commit)
        lut_specimens(conn, commit)
        field_pairs(conn, commit)
        reg_pairs(conn, commit)
        io_rows(conn, commit)


if __name__ == "__main__":
    main()
