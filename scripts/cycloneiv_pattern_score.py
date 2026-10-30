#!/usr/bin/env python3.15t
"""Score lifters/cycloneiv_clean/patterns.py (#165): known specimens, negative controls, the third-party image.

  python3.15t scripts/cycloneiv_pattern_score.py --specimens          # tmp/pattern_tests/<name>/ built by cycloneiv_pattern_specimens.py
  python3.15t scripts/cycloneiv_pattern_score.py --negatives [--limit N]   # reference/corpus_keep.tsv designs without hl_*: detector hit counts (all are false positives for the XOR classes)
  python3.15t scripts/cycloneiv_pattern_score.py --hl [--limit N]     # hl_* generator designs with hl_truth.json ground truth
  python3.15t scripts/cycloneiv_pattern_score.py --image             # env PLURIBUS_DJI_IMAGE; full detail -> tmp/dji_patterns/patterns.json (local), counts to the log
Log tmp/logs/cycloneiv_pattern_score.log.  Scores per class: matched / missing / extra / wrong, headline matched / (matched + missing + extra + wrong).
Stall guard: a design that takes > 120 s (first-run backstop, ~10x a corpus build) is logged and the run fails.
"""
import argparse
import concurrent.futures as cf
import csv
import json
import logging
import os
import pickle
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("pattern_score")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_pattern_score.log")
TESTS = os.path.join(REPO, "tmp", "pattern_tests")
IMG_DIR = os.path.join(REPO, "tmp", "dji_patterns")
STALL_S = 120


def netlist(cx, rbf, label, cache=None):
    from lifters.cycloneiv_clean import emit
    if cache and os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(rbf):
        return pickle.load(open(cache, "rb"))
    nl = emit.Builder(cx, rbf, label).run()
    if cache:
        pickle.dump(nl, open(cache, "wb"))
    return nl


def score_specimen(name, res):
    """-> {class: dict(matched, missing, extra, wrong)} against tmp/pattern_tests/<name>/expected.json."""
    from lifters.cycloneiv_clean import patterns as P
    exp = json.load(open(os.path.join(TESTS, name, "expected.json")))
    out = {}

    def tally(cls, m=0, miss=0, extra=0, wrong=0):
        t = out.setdefault(cls, dict(matched=0, missing=0, extra=0, wrong=0))
        t["matched"] += m
        t["missing"] += miss
        t["extra"] += extra
        t["wrong"] += wrong
    if "lfsr" in exp:
        got = list(res["lfsr"])
        for e in exp["lfsr"]:
            p = P.poly_of(e["poly"])
            cand = [g for g in got if g["n"] == e["n"]]
            hit = next((g for g in cand if g["charpoly"] in (p, P.reciprocal(p))), None)
            if hit is not None:
                tally("lfsr", m=1)
                got.remove(hit)
                if e.get("data_xor") == "additive":
                    tally("lfsr_whitening", m=int(hit["whiten_consumers"] >= 1), wrong=int(hit["whiten_consumers"] < 1))
            elif cand:
                tally("lfsr", wrong=1)
                got.remove(cand[0])
            else:
                tally("lfsr", miss=1)
        tally("lfsr", extra=len(got))
    if "crc" in exp:
        got = list(res["parallel"])
        for e in exp["crc"]:
            p = (1 << e["n"]) | e["poly"]
            cand = [g for g in got if g["n"] == e["n"]]
            hit = next((g for g in cand if g["charpoly"] in (p, P.reciprocal(p)) and e["w"] == g["w"]), None)
            if hit is not None:
                tally("crc", m=1)
                got.remove(hit)
            elif cand:
                tally("crc", wrong=1)
                got.remove(cand[0])
            else:
                tally("crc", miss=1)
        tally("crc", extra=len(got))
    if "conv" in exp:
        got = list(res["conv"])
        for e in exp["conv"]:
            hit = next((c for c in got if c["k"] == e["k"] and c["match"]), None)
            if hit is not None:
                tally("conv", m=1)
                got.remove(hit)
            elif got:
                tally("conv", wrong=1)
                got.pop()
            else:
                tally("conv", miss=1)
        tally("conv", extra=len(got))
    if "gfmul" in exp:
        got = [g for g in res["gfmul"] if g["kind"] == "gf_const_mult"]
        for e in exp["gfmul"]:
            want = (hex(e["poly"]), hex(e["c"]))
            hit = next((g for g in got if want in [tuple(c) for c in g["candidates"]]), None)
            if hit is not None:
                tally("gfmul", m=1)
                got.remove(hit)
            else:
                tally("gfmul", miss=1)
        tally("gfmul", extra=len(got))
    if "fir" in exp:
        got = [x for x in res["fir"] if x["match"]]
        for e in exp["fir"]:
            hit = next((x for x in got if x["span"] == e["poly"][0]), None)
            tally("fir", m=int(hit is not None), miss=int(hit is None))
            if hit is not None:
                got.remove(hit)
        tally("fir", extra=len(got))
    if "sync_word" in exp:
        got = list(res["syncword"])
        for e in exp["sync_word"]:
            hit = next((g for g in got if g["literals"] == e["n"] and g["source"] == "shift_chain" and g["contiguous"]), None)
            tally("sync_word", m=int(hit is not None), miss=int(hit is None))
            if hit is not None:
                got.remove(hit)
        tally("sync_word", extra=len(got))
    if "shift" in exp:
        got = [c["n"] for c in res["shift"]["plain"] if not c["in_lfsr"]]
        for e in exp["shift"]:
            if e["n"] in got:
                got.remove(e["n"])
                tally("shift", m=1)
            else:
                tally("shift", miss=1)
    if "interleaver" in exp:
        got = [x for x in res["m9k_addr"] if x["modelled"] and x["cls"] == "counter_bit_permutation"]
        for e in exp["interleaver"]:
            hit = next((x for x in got if x["addr_bits"] == e["addr_bits"]), None)
            tally("interleaver", m=int(hit is not None), miss=int(hit is None))
            if hit is not None:
                got.remove(hit)
        tally("interleaver", extra=len(got))
    if "counter" in exp:
        got = [c["width"] for c in res["counters"] if c["kind"] == "counter"]
        for e in exp["counter"]:
            if e["width"] in got:
                got.remove(e["width"])
                tally("counter", m=1)
            else:
                tally("counter", miss=1)
        tally("counter", extra=len(got))
    if "cdc_sync" in exp:
        n = len(res["cdc"]["syncs"])
        want = sum(e["n"] for e in exp["cdc_sync"]) + sum(e["w"] for e in exp.get("cdc_bus", [])) * 0
        tally("cdc_sync", m=min(n, want), miss=max(0, want - n), extra=max(0, n - want))
    if "gray" in exp:
        n = len(res["cdc"]["gray"])
        want = sum(e["n"] for e in exp["gray"])
        tally("gray", m=min(n, want), miss=max(0, want - n), extra=max(0, n - want))
    if "pointer_compare" in exp:
        n = len(res["cdc"]["pointer_compares"])
        want = sum(e["n"] for e in exp["pointer_compare"])
        tally("pointer_compare", m=min(n, want), miss=max(0, want - n), extra=max(0, n - want))
    return out


def score_truth(res, truth):
    """Score one hl_* design (corpus/cycloneiv/hl_*/src/hl_truth.json, written by the generator) -> {class: tally}."""
    from lifters.cycloneiv_clean import patterns as P
    out = {}

    def tally(cls, m=0, miss=0, extra=0, wrong=0):
        t = out.setdefault(cls, dict(matched=0, missing=0, extra=0, wrong=0))
        t["matched"] += m
        t["missing"] += miss
        t["extra"] += extra
        t["wrong"] += wrong
    pool = list(res["lfsr"]) + list(res["parallel"]) + list(res["ring"])
    cons = truth["constructs"]
    # the fitter drops unobserved registers: truth reg_bits - fitted registers is the budget a missing construct may be attributed to (tallied as `pruned`)
    budget = max(0, truth.get("expected", {}).get("reg_bits", 0) - truth.get("fit", {}).get("registers", 0))

    def missing(cls, width):
        nonlocal budget
        if width <= budget:
            budget -= width
            tally(cls + "_pruned", miss=1)
        else:
            tally(cls, miss=1)
    for c in (x for x in cons if x["kind"] == "crc"):
        n = c["width"]
        p = (1 << n) | int(c["poly"], 16)
        hit = next((g for g in pool if g["n"] == n and g["charpoly"] in (p, P.reciprocal(p)) and g["w"] == c["data_width"]), None)
        if hit is not None:
            tally("crc", m=1)
            pool.remove(hit)
        else:
            cand = next((g for g in pool if g["n"] == n), None)
            if cand is None:
                missing("crc", n)
            else:
                tally("crc", wrong=1)
                pool.remove(cand)
    for c in (x for x in cons if x["kind"] == "lfsr"):
        n = c["width"]
        p = P.poly_of(list(c["taps"]) + [0])
        hit = next((g for g in pool if g["n"] == n and g["charpoly"] in (p, P.reciprocal(p))), None)
        if hit is not None:
            tally("lfsr", m=1)
            pool.remove(hit)
        else:
            cand = next((g for g in pool if g["n"] == n), None)
            if cand is None:
                missing("lfsr", n)
            else:
                tally("lfsr", wrong=1)
                pool.remove(cand)
    tally("linear_group", extra=len(pool))
    cw = [c["width"] for c in res["counters"] if c["kind"] == "counter"]
    for c in (x for x in cons if x["kind"] == "counter"):
        if c["width"] in cw:
            cw.remove(c["width"])
            tally("counter", m=1)
        else:
            missing("counter", c["width"])
    tally("counter", extra=len(cw))
    sw = [x["literals"] for x in res["syncword"]]
    for c in (x for x in cons if x["kind"] == "equality" and x["width"] >= P.SYNC_MIN):
        if c["width"] in sw:
            sw.remove(c["width"])
            tally("const_compare", m=1)
        else:
            tally("const_compare", miss=1)
    tally("const_compare", extra=len(sw))
    n_other = {k: sum(1 for x in cons if x["kind"] == k) for k in ("shift_register", "fifo", "ram", "rom", "mac")}
    tally("conv_not_in_truth", extra=len(res["conv"]))
    tally("gfmul_not_in_truth", extra=sum(1 for g in res["gfmul"] if g["kind"] == "gf_const_mult"))
    tally("fir_not_in_truth", extra=sum(1 for g in res["fir"] if g["match"]))
    return out, n_other


def run_hl(cx, limit, workers, only=""):
    import glob
    from lifters.cycloneiv_clean import patterns as P
    designs = sorted(os.path.basename(os.path.dirname(os.path.dirname(f))) for f in glob.glob(os.path.join(REPO, "corpus", "cycloneiv", "hl_*", "src", "hl_truth.json")))
    designs = [d for d in designs if os.path.exists(os.path.join(REPO, "corpus", "cycloneiv", d, "bitstream.rbf"))]
    if only:
        designs = [d for d in designs if d.startswith(tuple(only.split(",")))]
    if limit:
        designs = designs[:limit]

    def one(d):
        nl = netlist(cx, os.path.join(REPO, "corpus", "cycloneiv", d, "bitstream.rbf"), d)
        return d, score_truth(P.detect(nl), json.load(open(os.path.join(REPO, "corpus", "cycloneiv", d, "src", "hl_truth.json"))))[0]
    total, per = {}, {}
    with cf.ThreadPoolExecutor(workers) as ex:
        pending = {ex.submit(one, d) for d in designs}
        while pending:
            done, pending = cf.wait(pending, timeout=STALL_S, return_when=cf.FIRST_COMPLETED)
            if not done:
                log.error("stall: no design finished in %ds (%d pending, load %s)", STALL_S, len(pending), os.getloadavg())
                raise SystemExit(3)
            for f in done:
                d, sc = f.result()
                per[d] = sc
                for cls, t in sc.items():
                    tt = total.setdefault(cls, dict(matched=0, missing=0, extra=0, wrong=0))
                    for k, v in t.items():
                        tt[k] += v
    json.dump(per, open(os.path.join(TESTS, "hl_scores.json"), "w"), indent=1)
    for cls, t in sorted(total.items()):
        den = sum(t.values())
        log.info("HL %-20s matched %d missing %d extra %d wrong %d  headline %d/%d = %.1f%%", cls, t["matched"], t["missing"], t["extra"], t["wrong"],
                 t["matched"], den, 100.0 * t["matched"] / den if den else 0)
    log.info("HL designs scored: %d", len(designs))
    return total


def run_specimens(cx):
    from lifters.cycloneiv_clean import patterns as P
    total = {}
    for name in sorted(os.listdir(TESTS)):
        d = os.path.join(TESTS, name)
        rbf = os.path.join(d, "bitstream.rbf")
        if not os.path.exists(rbf):
            continue
        nl = netlist(cx, rbf, name, os.path.join(d, "nl.pkl"))
        res = P.detect(nl)
        sc = score_specimen(name, res)
        log.info("specimen %s: %s", name, json.dumps(sc))
        for cls, t in sc.items():
            tt = total.setdefault(cls, dict(matched=0, missing=0, extra=0, wrong=0))
            for k, v in t.items():
                tt[k] += v
    for cls, t in sorted(total.items()):
        den = sum(t.values())
        log.info("TOTAL %-16s matched %d missing %d extra %d wrong %d  headline %d/%d = %.1f%%", cls, t["matched"], t["missing"], t["extra"], t["wrong"],
                 t["matched"], den, 100.0 * t["matched"] / den if den else 0)
    return total


def negative_one(cx, d):
    from lifters.cycloneiv_clean import patterns as P
    rbf = os.path.join(REPO, "corpus", "cycloneiv", d, "bitstream.rbf")
    if not os.path.exists(rbf):
        return d, None
    nl = netlist(cx, rbf, d)
    res = P.detect(nl)
    s = P.summary(res)
    return d, s


def run_negatives(cx, limit, workers):
    keep = [r["design"] for r in csv.DictReader(open(os.path.join(REPO, "reference", "corpus_keep.tsv")), delimiter="\t")]
    keep = [d for d in keep if not d.startswith("hl_")]            # hl_* contain real LFSR / CRC / counter constructs: scored by --hl against hl_truth.json
    if limit:
        keep = keep[:limit]
    rows, t0 = {}, time.time()
    with cf.ThreadPoolExecutor(workers) as ex:
        pending = {ex.submit(negative_one, cx, d) for d in keep}
        while pending:
            done, pending = cf.wait(pending, timeout=STALL_S, return_when=cf.FIRST_COMPLETED)
            if not done:
                log.error("stall: no design finished in %ds (%d pending, load %s)", STALL_S, len(pending), os.getloadavg())
                raise SystemExit(3)
            for f in done:
                d, s = f.result()
                rows[d] = s
    ok = {d: s for d, s in rows.items() if s}
    json.dump(ok, open(os.path.join(TESTS, "negatives.json"), "w"), indent=1, default=str)
    agg = {}
    for d, s in ok.items():
        for k in ("lfsr", "parallel", "ring", "conv", "fir_xor", "fir_xor_matched_known", "shift_chains", "shift_loadable", "pointer_compares", "gray_registers"):
            agg[k] = agg.get(k, 0) + (s.get(k) or 0)
            if s.get(k):
                agg[k + "_designs"] = agg.get(k + "_designs", 0) + 1
        for k in ("gfmul", "syncword", "counters", "m9k_addr_classes"):
            for kk, v in (s.get(k) or {}).items():
                agg[f"{k}.{kk}"] = agg.get(f"{k}.{kk}", 0) + v
    log.info("negatives: %d designs scored (%d without rbf) in %.0fs; detections: %s", len(ok), len(rows) - len(ok), time.time() - t0, json.dumps(agg, sort_keys=True))
    return agg


def run_image(cx):
    from lifters.cycloneiv_clean import patterns as P
    img = os.environ.get("PLURIBUS_DJI_IMAGE")
    if not img or not os.path.isfile(img):
        raise SystemExit("PLURIBUS_DJI_IMAGE not set or file absent")
    cache = os.path.join(IMG_DIR, "image_nl.pkl")
    if os.path.exists(cache):
        nl = pickle.load(open(cache, "rb"))
    else:
        import cycloneiv_decompress as cd
        plane = os.path.join(IMG_DIR, "plane.rbf")
        open(plane, "wb").write(cd.decompress(open(img, "rb").read(), {}))
        try:
            nl = netlist(cx, plane, "image", cache)
        finally:
            os.remove(plane)
    t0 = time.time()
    res = P.detect(nl)
    json.dump(res, open(os.path.join(IMG_DIR, "patterns.json"), "w"), indent=1, default=str)
    s = P.summary(res)
    log.info("image detect %.0fs: %s", time.time() - t0, json.dumps(s, default=dict, sort_keys=True))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specimens", action="store_true")
    ap.add_argument("--negatives", action="store_true")
    ap.add_argument("--image", action="store_true")
    ap.add_argument("--hl", action="store_true", help="score against corpus/cycloneiv/hl_*/src/hl_truth.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="--hl: comma-separated design name prefixes")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    import heavy_guard
    from lifters.cycloneiv_clean import emit
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + a.workers * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    with heavy_guard.lease(gb, "cyc4_pattern_score", log):
        cx = emit.Ctx()
        if a.specimens:
            run_specimens(cx)
        if a.negatives:
            run_negatives(cx, a.limit, a.workers)
        if a.hl:
            run_hl(cx, a.limit, a.workers, a.only)
        if a.image:
            run_image(cx)


if __name__ == "__main__":
    main()
