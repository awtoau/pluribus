#!/usr/bin/env python3.15t
"""Generic hard-block functional trace + chain-classification report (functrace.py core, #165/#177/#179).

  python3.15t scripts/cycloneiv_clean_functrace_report.py --type mac [--nl NL.pkl] [--out tmp/functrace]
  python3.15t scripts/cycloneiv_clean_functrace_report.py --type m9k [--nl NL.pkl] [--out tmp/functrace]
Same report shape regardless of --type: per-instance operand-source / sink trace (functrace.trace_source
/ trace_sinks), connected-component chain groups (functrace.chain_groups), per-group topology (linear /
tree / fan-in-to-one-sink / isolated). Re-running after a lift improvement needs no code change, only a
fresh --nl. --type mac additionally runs the MAC-specific "coefficient ROM vs data buffer" M9K-content
classification plugin (mac_m9k_classify() below) — kept here, not in functrace.py, per the generic-core
rule in lifters/cycloneiv_clean/functrace.py's own docstring.
Outputs tmp/functrace/<type>.json (full detail, gitignored) + counts to the log.
Log tmp/logs/cycloneiv_clean_functrace_report.log.  Image is read-only; no decoder code is touched.
"""
import argparse
import collections
import json
import logging
import os
import pickle
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("functrace_report")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_functrace_report.log")
OUT = os.path.join(REPO, "tmp", "functrace")
DEFAULT_NL = os.path.join(REPO, "tmp", "image_sim", "nl.pkl")
CLASSIFY_JSON = os.path.join(REPO, "tmp", "dji_m9k_content", "classify.json")


def topology(group, edges):
    """Plain description of one chain group's shape, from the edge list restricted to this group
    (no forced label onto a known signature; see docs/altera/cycloneIV/cycloneiv-image-prior-art.md
    "a correct topology description is more valuable than a forced FFT label")."""
    if len(group) == 1:
        return "isolated"
    gset = set(group)
    ge = [(a, b, v) for a, b, v in edges if a in gset and b in gset]
    indeg, outdeg = collections.Counter(), collections.Counter()
    for a, b, _v in ge:
        outdeg[a] += 1
        indeg[b] += 1
    max_in, max_out = max(indeg.values(), default=0), max(outdeg.values(), default=0)
    if max_in >= 3 and all(outdeg[n] <= 1 for n in group):
        return f"fan-in (star): {max_in} sources into one sink-side instance -- MAC-based dot-product/correlator shape"
    if max_out >= 3 and all(indeg[n] <= 1 for n in group):
        return f"fan-out (star): one instance feeds {max_out} others -- broadcast/shared-operand shape"
    if all(indeg[n] <= 1 and outdeg[n] <= 1 for n in group):
        return f"linear chain, length {len(group)} -- FIR/accumulator pipeline shape"
    if max_in >= 2 or max_out >= 2:
        return f"tree/branching, {len(group)} nodes, max fan-in {max_in} max fan-out {max_out} -- possible radix butterfly shape"
    return f"irregular, {len(group)} nodes, {len(ge)} edges"


def mac_m9k_classify(result, classify_path):
    """MAC-specific plugin (not in functrace.py): of the MACs with an M9K operand, does that tile's
    content (tmp/dji_m9k_content/classify.json, already-done content-classification work) look like a
    coefficient ROM (few distinct values, reused across many words: FIR/twiddle shape) or a data buffer
    (near-unique values per word: a running computation on buffered data)? Heuristic, not a decoder
    rule: distinct_frac < COEF_FRAC and nonzero_words >= COEF_MIN_WORDS => coefficient-shaped (I)."""
    COEF_FRAC, COEF_MIN_WORDS = 0.1, 8
    by_xy = {}
    if os.path.exists(classify_path):
        raw = json.load(open(classify_path))
        for key, v in raw.items():
            try:
                xy = key.split("_x", 1)[1].split(".")[0]
                x, y = xy.split("_y")
            except Exception:
                continue
            seg = (v.get("segments") or [{}])[0]
            perm = seg.get("perm", {})
            by_xy.setdefault((int(x), int(y)), []).append(dict(width=v.get("width"), nonzero=v.get("nonzero_words"),
                                                               distinct=perm.get("distinct"), distinct_frac=perm.get("distinct_frac")))
    out = []
    for m in result["instances"]:
        tiles = set()
        for s in m["operand_sources"]:
            if s["kind"] == "m9k":
                tiles.add(tuple(s["detail"][:2]))
            elif s["kind"] == "lab_logic":
                for sig in s.get("has_m9k") or []:
                    x, y = sig.split("_")[1:3]
                    tiles.add((int(x), int(y)))
        tiles = sorted(tiles)
        if not tiles:
            continue
        shapes = []
        for t in tiles:
            views = by_xy.get(t)
            if not views:
                shapes.append(dict(xy=t, content_known=False))
                continue
            v = views[0]
            frac = v.get("distinct_frac")
            coef = frac is not None and frac < COEF_FRAC and (v.get("nonzero") or 0) >= COEF_MIN_WORDS
            shapes.append(dict(xy=t, content_known=True, width=v.get("width"), nonzero_words=v.get("nonzero"),
                               distinct=v.get("distinct"), distinct_frac=frac,
                               classification=("I: coefficient-ROM-shaped (few distinct values, reused)" if coef
                                                else "I: data-buffer-shaped (near-unique per word)" if frac is not None
                                                else "U: no distinct-value data")))
        out.append(dict(mac=m["id"], m9k_tiles=shapes))
    return out


def run(spec_name, nl_path, out_dir, ff_hops):
    t0 = time.time()
    sys.path.insert(0, os.path.join(REPO))
    from lifters.cycloneiv_clean import functrace as FT
    log.info("loading %s", nl_path)
    nl = pickle.load(open(nl_path, "rb"))
    spec = FT.TYPE_SPECS[spec_name]
    design = FT.PT.Design(nl)
    fanout = FT._build_fanout(nl)
    insts = spec.instances(nl)
    log.info("%d used %s instances", len(insts), spec_name)
    instances_out = []
    for inst in insts:
        iid = spec.id_fn(inst)
        srcs, sinks = [], []
        for name, idx, s in spec.operand_signals(inst):
            if name == spec.out_prefix.rstrip("_"):
                continue
            tr = FT.trace_source(design, s, ff_hops=ff_hops)
            srcs.append(dict(pin=name, index=idx, kind=tr["kind"], detail=tr.get("detail"), hops=tr.get("hops"),
                             leaves=tr.get("leaves") if tr["kind"] == "lab_logic" else None,
                             has_m9k=tr.get("has_m9k") if tr["kind"] == "lab_logic" else None,
                             has_mac=tr.get("has_mac") if tr["kind"] == "lab_logic" else None))
        out_prefix = spec.out_prefix
        out_sig_candidates = [s for s in fanout if s.startswith(f"{out_prefix}{iid[0]}_{iid[1]}_") or s.startswith(f"{out_prefix}{iid[0]}_{iid[1]}[")]
        for s in sorted(out_sig_candidates):
            for sk in FT.trace_sinks(design, fanout, s, ff_hops=ff_hops):
                sinks.append(dict(out_signal=s, kind=sk["kind"], detail=sk.get("detail"), pin=sk.get("pin"), hops=sk.get("hops")))
        rec = dict(id=list(iid) if isinstance(iid, tuple) else iid, operand_sources=srcs, output_sinks=sinks)
        if spec_name == "mac":
            rec["nine_bit"] = bool(inst.get("nine"))
            rec["signed"] = [not u for u in (inst.get("sreg") or [False, False])]
            rec["ireg"], rec["oreg"] = inst.get("ireg"), inst.get("oreg")
        instances_out.append(rec)
    edges, groups = FT.chain_groups(nl, spec, ff_hops=ff_hops)
    group_reports = []
    for g in groups:
        group_reports.append(dict(size=len(g), members=[list(m) if isinstance(m, tuple) else m for m in g],
                                  topology=topology(g, edges) if len(g) > 1 else "isolated"))
    def _has(src, kind):
        # "has an M9K/MAC operand" = patterns.mac_roms()'s own test: ANY leaf of the operand bit's
        # cone (direct hit, or inside a mixed lab_logic cone -- e.g. a word-select mux over several
        # M9K read bits) is of that kind -- not "the whole operand resolves to nothing else".
        if src["kind"] == kind:
            return True
        if src["kind"] == "lab_logic":
            return bool(src.get(f"has_{kind}"))
        return False
    m9k_operand = sum(1 for r in instances_out if any(_has(s, "m9k") for s in r["operand_sources"]))
    mac_chain = sum(1 for r in instances_out if any(_has(s, "mac") for s in r["operand_sources"]))
    result = dict(type=spec_name, n_instances=len(insts),
                  n_with_m9k_operand=m9k_operand if spec_name == "mac" else None,
                  n_chained_to_other_mac=mac_chain if spec_name == "mac" else None,
                  edges=[dict(src=list(a) if isinstance(a, tuple) else a, dst=list(b) if isinstance(b, tuple) else b, via=v) for a, b, v in edges],
                  groups=sorted(group_reports, key=lambda r: -r["size"]),
                  instances=instances_out)
    if spec_name == "mac":
        result["m9k_content_classification"] = mac_m9k_classify(result, CLASSIFY_JSON)
    os.makedirs(out_dir, exist_ok=True)
    json.dump(result, open(os.path.join(out_dir, f"{spec_name}.json"), "w"), indent=1, default=str)
    log.info("[V] %s: %d instances, %d chain groups (sizes %s), %.1fs", spec_name, len(insts), len(groups),
              sorted((g["size"] for g in group_reports), reverse=True)[:10], time.time() - t0)
    if spec_name == "mac":
        log.info("[V] MACs with an M9K operand: %d of %d (re-verified by trace, not cited from a prior chat finding)", m9k_operand, len(insts))
        log.info("[V] MACs chained to another MAC (operand <- MAC output, direct or via one LAB-logic/FF hop): %d of %d", mac_chain, len(insts))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True, choices=["mac", "m9k"])
    ap.add_argument("--nl", default=DEFAULT_NL)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--ff-hops", type=int, default=1, help="FF stages crossed before a backward/forward trace gives up. Decision: 1 "
                     "reproduces patterns.mac_roms()'s own M9K-operand test (Design.support(sig, hops=1)) almost exactly (31 vs 32 of 87 "
                     "MACs with an M9K operand on the DJI image, one-instance difference not chased per the project's "
                     "'don't chase the last cell' rule, docs/altera/cycloneIV/cycloneiv-clean-mac-trace.md); ff_hops=2 nearly doubles the "
                     "count by reaching through a second register stage into unrelated accumulator feedback, over-attributing M9K operands")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    run(a.type, a.nl, a.out, a.ff_hops)


if __name__ == "__main__":
    main()
