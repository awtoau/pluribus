#!/usr/bin/env python3.15t
"""Score the high-level Verilog lifter (lifters/cycloneiv_clean/rtl.py) on the hl_* corpus against src/hl_truth.json (#165).

  python3.15t scripts/cycloneiv_hl_score.py [--root DIR] [--match 'hl_*'] [--cycles 200] [--vo] [--workers 4] [--tag T]
Per design: emit -> rtl (cycloneiv_clean_rtl_check.one: RTL vs flat emit, iverilog, same vectors), optional RTL vs post-fit .vo.
Per count key (counters, adders, subtractors, comparators, fsms, shift_registers, muxes, m9k, mac, reg_bits): matched = min(expected, recovered),
missing = expected - matched, extra = recovered - matched, wrong = recovered adders whose width matches no expected adder (width-checked designs only).
Headline per key and overall: matched / (matched + missing + extra + wrong).
Log tmp/logs/cycloneiv_hl_score.log; results tmp/cycloneiv_clean/hl_score_<tag>.json (counts only).  Read-only on the corpus; no DB access.
"""
import argparse
import collections
import concurrent.futures as cf
import fnmatch
import json
import logging
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("cycloneiv_hl_score")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_hl_score.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean")
KEYS = ("reg_bits", "counters", "adders", "subtractors", "comparators", "fsms", "shift_registers", "muxes", "m9k", "mac")
# kinds whose adder widths are known exactly from the truth (others: counters / fifo / mac adders have no width in the manifest)
WIDTH_OK = {"adder", "subtractor", "comparator", "equality", "register", "lfsr", "shift_register", "crc", "fsm", "mux", "decoder", "prienc"}


def recovered(rep):
    r = {k: rep.get(k, 0) for k in KEYS}
    r["reg_bits"] = rep["reg_bits"] + rep.get("fsm_state_bits", 0)
    return r


def truth_widths(tr):
    ws = []
    for c in tr["constructs"]:
        if c["kind"] == "adder":
            ws += [c["width"]] * (2 if c.get("op") == "add3" else 1)
    return ws


def score_one(d, rep, tr):
    exp, rec = tr["expected"], recovered(rep)
    out = {}
    for k in KEYS:
        e, r = exp.get(k, 0), rec[k]
        m = min(e, r)
        out[k] = dict(matched=m, missing=e - m, extra=r - m, wrong=0)
    if {c["kind"] for c in tr["constructs"] if c["role"] == "dut"} <= WIDTH_OK:
        tw, rw = sorted(truth_widths(tr)), sorted(rep.get("adder_widths", []))
        wrong = sum(1 for a, b in zip(tw, rw) if a not in (b, b + 1, b - 1))
        out["adders"]["wrong"] = wrong
        out["adders"]["matched"] -= wrong
    ea, ra = exp.get("counters", 0) + exp.get("adders", 0) + exp.get("subtractors", 0), rec["counters"] + rec["adders"] + rec["subtractors"]
    out["arith_class"] = dict(matched=min(ea, ra), missing=max(ea - ra, 0), extra=max(ra - ea, 0), wrong=0)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.path.join(REPO, "corpus", "cycloneiv"))
    ap.add_argument("--match", default="hl_*")
    ap.add_argument("--cycles", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--vo", action="store_true")
    ap.add_argument("--tag", default="x")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    import cycloneiv_clean_rtl_check as RC
    import heavy_guard
    from lifters.cycloneiv_clean import emit, rtl
    ds = [os.path.join(a.root, n) for n in sorted(os.listdir(a.root)) if fnmatch.fnmatch(n, a.match)
          and all(os.path.exists(os.path.join(a.root, n, f)) for f in ("bitstream.rbf", "postfit.vo", "src/hl_truth.json"))]
    log.info("%d designs", len(ds))
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + a.workers * (heavy_guard.JOB_GB["cyc4_clean_gate_worker"] + 0.6)
    rows, t0 = [], time.time()
    with heavy_guard.lease(gb, "cyc4_hl_score", log):
        cx = emit.Ctx()
        cx.st.edge_ids([0], [0])
        with cf.ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(RC.one, cx, d, a.cycles, a.seed): d for d in ds}
            pending = set(futs)
            while pending:
                done, pending = cf.wait(pending, timeout=60, return_when=cf.FIRST_COMPLETED)
                if not done:
                    log.error("stall: no design finished in 60 s (%d pending, load %s)", len(pending), os.getloadavg())
                    raise SystemExit(3)
                for f in done:
                    d = futs[f]
                    try:
                        r = f.result()
                    except Exception as e:
                        r = dict(design=os.path.basename(d), eq_flat="error", eq_info=f"{type(e).__name__}: {e}")
                    tr = json.load(open(os.path.join(d, "src", "hl_truth.json")))
                    r["kind"], r["fit"] = tr["kind"], tr.get("fit")
                    if "report" in r:
                        r["score"] = score_one(d, r["report"], tr)
                    rows.append(r)
                    log.info("%s eq_flat=%s", r["design"], r["eq_flat"])
        if a.vo:
            import cycloneiv_clean_emit_sim as S
            orig = emit.verilog

            def sweep(key):
                with cf.ThreadPoolExecutor(a.workers) as ex:
                    vf = {ex.submit(S.run_one, cx, d, a.cycles, a.seed): d for d in ds}
                    for f in cf.as_completed(vf):
                        n = os.path.basename(vf[f])
                        try:
                            r = f.result()
                            v = dict(status=r["status"], comparable=r.get("comparable"), bad_ports=r.get("bad_ports"), err=r.get("err"))
                        except Exception as e:
                            v = dict(status="error", err=f"{type(e).__name__}: {e}")
                        next(x for x in rows if x["design"] == n)[key] = v
            sweep("eq_vo_flat")
            emit.verilog = lambda nl, module="cyc4_top": rtl.lift(nl, "pad_", module)[0]
            try:
                sweep("eq_vo")
            finally:
                emit.verilog = orig
    summ = summarise(rows)
    summ["seconds"] = round(time.time() - t0)
    json.dump(dict(summary=summ, rows=rows), open(os.path.join(OUT, f"hl_score_{a.tag}.json"), "w"), default=str)
    log.info("EQUIV rtl-vs-flat %s", summ["eq_flat"])
    if a.vo:
        log.info("EQUIV flat-vs-vo %s ; rtl-vs-vo %s", summ["eq_vo_flat"], summ["eq_vo"])
    for k, v in summ["by_key"].items():
        log.info("KEY %-15s %s headline %.1f%%", k, {x: v[x] for x in ("matched", "missing", "extra", "wrong")}, v["headline"])
    for kd, v in summ["by_kind"].items():
        log.info("KIND %-9s designs %3d eq %s  %s", kd, v["designs"], v["eq"], {k: f"{x['matched']}/{x['missing']}/{x['extra']}/{x['wrong']}" for k, x in v["keys"].items() if sum(x.values())})
    log.info("OVERALL %s", summ["overall"])


def head(v):
    t = v["matched"] + v["missing"] + v["extra"] + v["wrong"]
    return round(100.0 * v["matched"] / t, 1) if t else 100.0


def summarise(rows):
    z = lambda: collections.Counter(matched=0, missing=0, extra=0, wrong=0)
    by_key, by_kind, kind_eq, kind_n = collections.defaultdict(z), collections.defaultdict(lambda: collections.defaultdict(z)), collections.defaultdict(collections.Counter), collections.Counter()
    for r in rows:
        kind_n[r["kind"]] += 1
        kind_eq[r["kind"]][r["eq_flat"]] += 1
        for k, v in (r.get("score") or {}).items():
            by_key[k].update(v)
            by_kind[r["kind"]][k].update(v)
    tot = z()
    for k in KEYS:
        tot.update(by_key[k])
    out = dict(designs=len(rows), eq_flat=dict(collections.Counter(r["eq_flat"] for r in rows)),
               eq_vo_flat=dict(collections.Counter(r.get("eq_vo_flat", {}).get("status") for r in rows)),
               eq_vo=dict(collections.Counter(r.get("eq_vo", {}).get("status") for r in rows)),
               by_key={k: dict(v, headline=head(v)) for k, v in by_key.items()},
               by_kind={kd: dict(designs=kind_n[kd], eq=dict(kind_eq[kd]), keys={k: dict(v) for k, v in by_kind[kd].items() if k != "arith_class"}) for kd in sorted(kind_n)},
               overall=dict(tot, headline=head(tot)))
    return out


if __name__ == "__main__":
    main()
