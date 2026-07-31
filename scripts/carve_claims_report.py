#!/usr/bin/env python3.15t
"""Summarise the three claims over the commercial bitstreams.

Keeps the claims apart, and separates products so one product's 161-design
release zip cannot masquerade as breadth.
"""
import json
import os
import statistics
from collections import Counter, defaultdict

REPO = "/mnt/2tb/git/pluribus"
res = json.load(open(os.path.join(REPO, "tmp", "commercial_results.json")))
carve = json.load(open(os.path.join(REPO, "tmp", "commercial_carve.json")))

# map label/sha -> product via the carve records
prod_of = {}
for c in carve:
    src = c.get("source_file", "")
    key = src.split("/")[2] if src.startswith("corpus/vendor-firmware/") else "?"
    prod_of[os.path.basename(c["local"])] = key
    prod_of[c["sha256"]] = key

print(f"{len(res)} result records\n")
print("CLAIM 1 decode:", dict(Counter(r.get("decode") for r in res)))
print("CLAIM 2 oracle:", dict(Counter(str(r.get("oracle"))[:40] for r in res)))
print("CLAIM 3 lift  :", dict(Counter(str(r.get("lift"))[:40] for r in res)))
print("\ncrc_verified   :", dict(Counter(r.get("crc_verified") for r in res)))
print("frames_complete:", dict(Counter(r.get("frames_complete") for r in res)))
print("device         :", dict(Counter(r.get("device") for r in res)))
print("family         :", dict(Counter(r.get("family") for r in res)))

# per product
byprod = defaultdict(list)
for r in res:
    k = prod_of.get(r.get("sha256")) or prod_of.get(r.get("label")) or "?"
    byprod[k].append(r)
print("\n--- per product ---")
for k, rs in sorted(byprod.items(), key=lambda kv: -len(kv[1])):
    dec = sum(1 for r in rs if r.get("decode") == "ok")
    orc = sum(1 for r in rs if r.get("oracle") == "identical")
    lif = sum(1 for r in rs if r.get("lift") == "ok")
    print(f"  {k:26s} n={len(rs):4d} decode={dec:4d} oracle-identical={orc:4d} lift={lif:4d}")

# the headline: flip-flop clock loss
print("\n--- CLOCK-GLOBAL GAP (the headline question) ---")
rates = []
for r in res:
    m = r.get("metrics") or {}
    v = m.get("ff_clk_const_rate")
    if v is not None:
        rates.append((v, r.get("label", "?"), prod_of.get(r.get("sha256"), "?")))
if rates:
    vals = sorted(v for v, _l, _p in rates)
    print(f"  n={len(vals)}  min={min(vals):.3f} median={statistics.median(vals):.3f} "
          f"max={max(vals):.3f} mean={statistics.mean(vals):.3f}")
    print("  (existing hobby corpus: median 0.43; our own builds: 0.00)")
    # per product medians
    pp = defaultdict(list)
    for v, _l, p in rates:
        pp[p].append(v)
    print("  per product median:")
    for p, vs in sorted(pp.items(), key=lambda kv: -len(kv[1])):
        print(f"    {p:26s} n={len(vs):4d} median={statistics.median(vs):.3f} "
              f"min={min(vs):.3f} max={max(vs):.3f}")
else:
    print("  no ff_clk_const_rate recorded")

# wide muxes
print("\n--- WIDE MUXES ---")
wm = [(r.get("metrics") or {}).get("widemux_total") for r in res]
wm = [v for v in wm if v is not None]
if wm:
    nz = sum(1 for v in wm if v)
    print(f"  designs with wide muxes: {nz}/{len(wm)}")
    print(f"  total: min={min(wm)} median={statistics.median(wm)} max={max(wm)}")

# unknown lines = decoder's own admission
print("\n--- unknown: lines (decoder admits an unmodelled bit) ---")
ul = [r.get("unknown_lines") for r in res if r.get("unknown_lines") is not None]
if ul:
    print(f"  n={len(ul)} zero={sum(1 for v in ul if v==0)} "
          f"max={max(ul)} median={statistics.median(ul)}")

# failures in detail
print("\n--- non-ok records ---")
for r in res:
    if r.get("decode") != "ok" or r.get("lift") not in ("ok", "skipped", None):
        print(f"  {r.get('label','?')[:70]}")
        print(f"     decode={r.get('decode')} oracle={str(r.get('oracle'))[:50]} "
              f"lift={str(r.get('lift'))[:60]}")
