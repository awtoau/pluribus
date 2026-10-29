#!/usr/bin/env python3.15t
"""Cyclone IV: is the LB -> R4 group frame displacement df a function of the SOURCE, the R4 NAME/record, or the tile? (#162/#161/#160)

QUESTION: decode, from forced specimens + raw config-bit diffs, what df (asm-group cell frame shift, seen as 0, +4, -35, -70)
depends on.  ONE variable per comparison: (a) fixed R4 name (type, I, tile), vary the LB source (same LAB first, then
adjacent LAB); (b) fixed source, vary the R4 name (already in tmp/hop_specimens/results_r4map_*.json, re-read, 0 builds).

PREDICTION (written before any run): df is determined by the (source LAB column, destination column class) pair and NOT by
the R4 index or the record.  So for one fixed R4 name (type, I, tile T) with k different LB sources, df is constant; for
different R4 names at the same source, df is constant too.
REFUTED by: any fixed-(name, tile) group where df differs between sources, or any fixed-source group where df differs
between R4 names of the same direction.  (A difference confined to sources in different LAB columns still refutes the
literal prediction: it is then reported as a source-column effect.)
Evidence level: SET (a pair of vendor builds; df fits are rigid-shift fits of a 2-5 cell group, weak, not attributed).

  scripts/cycloneiv_r4_df_source.py plan --tile 47,45 --names 10,15,0,19 --ksrc 3
  scripts/cycloneiv_r4_df_source.py build --plan <plan> [--nulls]
  scripts/cycloneiv_r4_df_source.py analyse --plan <plan> / table / record
Log tmp/logs/cycloneiv_r4_df_source.log.
"""
import argparse
import collections
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_hop_specimens as H  # noqa: E402
import cycloneiv_r4_name_map as N  # noqa: E402

TMP = REPO / "tmp" / "hop_specimens"
N.PFX = "gxr4df"
log = logging.getLogger("cycloneiv_r4_df_source")


def spec_name(a):
    lb = a["lb"]
    return f"gxr4df_s_i{a['I']}_X{a['tile'][0]}Y{a['tile'][1]}_from{lb[1]}_{lb[2]}_{lb[3]}"


N.spec_name = spec_name


def cmd_plan(a):
    ch = N.chains_observed()
    X, Y = (int(v) for v in a.tile.split(","))
    arcs = []
    for i in (int(v) for v in a.names.split(",")):
        lbs, lis = ch[("R4", X, Y, i)]
        li = sorted((n for n in lis if n[3] in H.LI_PORT), key=lambda n: (abs(n[1] - X) + abs(n[2] - Y), n))[0]
        bylab = collections.defaultdict(list)
        for l in sorted(lbs):
            bylab[(l[1], l[2])].append(l)
        # same-LAB sources first (largest LAB group), then the nearest other LABs
        order = sorted(bylab, key=lambda k: (-len(bylab[k]), abs(k[0] - X) + abs(k[1] - Y)))
        picks = [bylab[k][0] for k in order][:a.ksrc] if a.spread else [l for k in order for l in bylab[k]][:a.ksrc]
        for lb in picks:
            u0 = (lb[1], lb[2], H.n_of_i(lb[3]))
            same = (u0[0], u0[1]) == (li[1], li[2])
            u1 = (li[1], li[2], 6 if not (same and u0[2] == 6) else 8)   # sink LE must not be the source LE
            arcs.append({"wire": "R4", "I": i, "tile": [X, Y], "lb": list(lb), "wire_name": ["R4", X, Y, i], "li": list(li),
                         "u0": list(u0), "u1": list(u1), "port": H.LI_PORT[li[3]]})
    out = Path(a.out or TMP / f"plan_r4df_X{X}Y{Y}.json")
    out.write_text(json.dumps({"tile": [X, Y], "arcs": arcs}))
    log.info("plan %s: %d arcs, %d bases => %d builds", out.name, len(arcs), len({N.base_name(x) for x in arcs}),
             len(arcs) + len({N.base_name(x) for x in arcs}))
    for x in arcs:
        log.info("  I=%d from %s -> LI %s (u0 %s u1 %s)", x["I"], x["lb"], x["li"][3], x["u0"], x["u1"])


def cmd_build(a):
    N.cmd_build(a)


def cmd_analyse(a):
    N.cmd_analyse(a)


def cmd_table(a):
    """Per (name, tile): sources, honoured, resolved record(s) and df.  df is read per fitting candidate record."""
    for f in a.plans:
        rows = json.loads(Path(f).read_text())["rows"]
        by = collections.defaultdict(list)
        for r in rows:
            by[(r["I"], tuple(r["tile"]))].append(r)
        for (i, t), rs in sorted(by.items()):
            for r in sorted(rs, key=lambda r: r["lb"]):
                fits = [(c["dx"], c["idx"], c["fits"]) for c in r.get("cands", ()) if c["fits"]]
                log.info("I=%2d X%dY%d src %-18s %-13s flipped+ %2d -%2d fits(dx,idx,df) %s", i, t[0], t[1],
                         "%d,%d,b%d" % (r["lb"][1], r["lb"][2], r["lb"][3]), r["status"], len(r.get("on", ())), len(r.get("off", ())), fits)
            dfs = {tuple(sorted({d for c in r.get("cands", ()) if c["fits"] for d in c["fits"][:1]})) for r in rs if r.get("status") == "resolved"}
            res = {(r["resolved"]["dx"], r["resolved"]["idx"], r["resolved"]["fits"][0]) for r in rs if r.get("resolved")}
            log.info("   => resolved (dx,idx,df) set %s  %s", sorted(res), "CONSTANT" if len(res) <= 1 else "DIFFERS")


def cmd_record(a):
    import db
    from provenance import evidence_io as E
    commit = E.git_head(REPO)
    n = 0
    with db.engine().begin() as conn:
        E.ensure_family(conn, "cycloneiv")
        for f in a.plans:
            for r in json.loads(Path(f).read_text())["rows"]:
                if r.get("status") not in ("resolved",) and not str(r.get("status", "")).startswith("unresolved"):
                    continue
                if "on" not in r:
                    continue
                nme = spec_name(r)
                bid = H.register_build(conn, N.base_name(r), "r4 df source base")
                sid = H.register_build(conn, nme, "r4 df source forced single path")
                meta = {"group": "r4_df_source", "tile": r["tile"], "I": r["I"], "lb": r["lb"], "honoured": r["honoured"],
                        "status": r["status"], "plane_level": True, "evidence_level": "set",
                        "fits": [(c["dx"], c["idx"], c["fits"]) for c in r.get("cands", ()) if c["fits"]]}
                E.record_specimen(conn, "cycloneiv", "EP4CGX150", nme, N.base_name(r), r["on"], r["off"], meta, "r4_df_source:R4",
                                  "scripts/cycloneiv_r4_df_source.py", commit, H.NV, tool_version="25.1", build_base=bid, build_spec=sid)
                n += 1
    log.info("recorded %d evidence rows", n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("plan", "build", "analyse", "table", "record"))
    ap.add_argument("--tile", default="47,45")
    ap.add_argument("--names", default="10,15,0,19")
    ap.add_argument("--spread", action="store_true", help="one source per LAB")
    ap.add_argument("--ksrc", type=int, default=3)
    ap.add_argument("--out", default=None)
    ap.add_argument("--plan", default=None)
    ap.add_argument("--nulls", action="store_true")
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("plans", nargs="*")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_r4_df_source.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    for lg in (N.log, H.log):
        lg.setLevel(logging.INFO)
        for h in log.handlers:
            lg.addHandler(h)
    globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    main()
