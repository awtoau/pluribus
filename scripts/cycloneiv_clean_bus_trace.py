#!/usr/bin/env python3.15t
"""Group a board pin TSV's per-chip_ref pads into real buses by STRUCTURE, not by the TSV's own
grouping text: same clock domain + same enable/consumer signature + a repeated per-bit cone shape
under leaf permutation = a real bus member; anything sharing the clock/chip_ref label but breaking
the cone-shape pattern is an outlier, reported separately, never silently folded in (#186/#177).

  python3.15t scripts/cycloneiv_clean_bus_trace.py --nl NL.pkl --pins PINS.tsv [--chip-ref AD9363]
Read-only on the netlist and the TSV.  Log tmp/logs/cycloneiv_clean_bus_trace.log, JSON
tmp/cycloneiv_clean/bus_trace.json.

Method per chip_ref group:
  1. Collect every pad row for that chip_ref from the TSV.
  2. For each pad's drive/capture FF (same walk as cycloneiv_clean_pad_roles.py), record its clock
     domain and the first 3 levels of its forward consumer cone (a cheap, stable structural signature
     -- NOT a full truth-table compare, since pads legitimately carry different DATA while still being
     the same kind of bus member; cone SHAPE, not cone VALUE, is the bus signature).
  3. Cluster pads whose (clock domain, cone-shape signature) match exactly; the largest cluster per
     chip_ref is "the bus"; every other pad in that chip_ref is an outlier, reported with its own
     signature so a human can judge whether it's a second bus, a control pin, or a mis-assignment.
"""
import argparse
import collections
import json
import logging
import os
import pickle
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("bus_trace")


# The TSV's own "# COLUMN FORMAT" comment is descriptive prose (e.g. "confidence(3=U 5=I 8=V)"
# splits into 3 words on whitespace), not a clean machine-readable column list -- hardcode the
# real tab-separated field order instead of parsing it from that line (confirmed against a real
# data row in tmp/dji_pins/board/pins_corrected.tsv, 2026-10-31).
PIN_COLS = ["ball", "bank", "site", "diffio_fn", "dir", "label", "function", "confidence", "tag",
            "chip_ref", "chip_pin", "chip_signal", "net_in", "net_out", "note"]


def load_pins(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= len(PIN_COLS):
            rows.append(dict(zip(PIN_COLS, parts)))
    if not rows:
        raise SystemExit(f"{path}: no data rows parsed (check tab-separated field count vs PIN_COLS)")
    return rows


def _capture_ff(D, pad_sig, seen=None):
    """Walk forward from a pad signal to its capture FF, through any number of pass-through LUTs
    (the project's existing pad-role convention: a pad can feed an FF directly, or feed a LUT --
    often a trivial single-real-pin buffer, as the earlier manual AD9363-group scan found -- whose
    output then feeds the real capture FF). Returns the FF dict, or None if no FF is reached."""
    seen = seen or set()
    if pad_sig in seen:
        return None
    seen.add(pad_sig)
    for F in D.nl.ffs:
        if F.get("d") == pad_sig:
            return F
    for L in D.nl.luts:
        if pad_sig in L.get("pins", []):
            found = _capture_ff(D, L["name"], seen)
            if found:
                return found
    return None


def pad_signature(D, FT, fanout, pad_name, max_hops=3):
    """(clock domain, consumer-cone shape) for the pad's capture FF, via functrace's own
    trace_sinks -- sorted (kind, hops) multiset, capped at max_hops so two bus members with
    slightly different downstream depth still cluster if their near structure matches, while a
    genuinely different consumer shape (a different hard-block kind, a much shorter/longer path)
    does not."""
    ff = _capture_ff(D, f"pad_{pad_name}") or _capture_ff(D, pad_name)
    if ff is None:
        return None
    sinks = FT.trace_sinks(D, fanout, ff["name"], ff_hops=max_hops)
    shape = tuple(sorted((s["kind"], min(s["hops"], max_hops)) for s in sinks))
    return (ff.get("clk"), shape)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", required=True)
    ap.add_argument("--pins", required=True)
    ap.add_argument("--chip-ref", default=None, help="restrict to one chip_ref (default: all)")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    os.makedirs(os.path.join(REPO, "tmp", "cycloneiv_clean"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_bus_trace.log"))])
    from lifters.cycloneiv_clean import patterns as PT
    from lifters.cycloneiv_clean import functrace as FT
    nl = pickle.load(open(a.nl, "rb"))
    D = PT.Design(nl)
    fanout = FT._build_fanout(nl)
    rows = load_pins(a.pins)
    by_chip = collections.defaultdict(list)
    for r in rows:
        ref = r.get("chip_ref", "").strip()
        if ref and (a.chip_ref is None or ref == a.chip_ref):
            by_chip[ref].append(r)

    result = {}
    for chip_ref, group_rows in sorted(by_chip.items()):
        sigs = {}
        for r in group_rows:
            pad = r["ball"]
            sig = pad_signature(D, FT, fanout, pad)
            sigs[pad] = sig
        unresolved = sorted(pad for pad, sig in sigs.items() if sig is None)
        clusters = collections.defaultdict(list)
        for pad, sig in sigs.items():
            if sig is not None:          # None (no FF found) is a real dict key -- never cluster it
                clusters[sig].append(pad)
        ordered = sorted(clusters.items(), key=lambda kv: -len(kv[1]))
        bus_sig, bus_pads = (ordered[0] if ordered else (None, []))
        outliers = {str(sig): pads for sig, pads in ordered[1:]} if len(ordered) > 1 else {}
        result[chip_ref] = dict(
            n_pads=len(group_rows),
            bus_size=len(bus_pads), bus_pads=sorted(bus_pads), bus_signature=str(bus_sig),
            n_outlier_clusters=len(outliers), outliers=outliers,
            unresolved=unresolved,
        )
        log.info("%s: %d pads, bus=%d (%s), outlier clusters=%d, unresolved=%d",
                  chip_ref, len(group_rows), len(bus_pads), sorted(bus_pads), len(outliers),
                  len(result[chip_ref]["unresolved"]))

    out = os.path.join(REPO, "tmp", "cycloneiv_clean", "bus_trace.json")
    json.dump(result, open(out, "w"), indent=1)
    log.info("-> %s", out)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
