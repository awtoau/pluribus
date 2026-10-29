#!/usr/bin/env python3.15t
"""Per-cell attribution of the Cyclone IV LOCAL_LINE specimen pip table (#141).

For every tile-relative cell of cycloneiv_pip_table.build_table(): (1) dependency on source LE / sink LE / port
by exact enumeration, (2) exact value table, (3) isolating pair-of-pairs, (4) queue of cells without evidence.
Specimens are differential (spec minus base) with exactly 4 cells per pair, so two pairs never differ in ONE cell:
the smallest observable change is a 1-for-1 swap (cell a off, cell b on). `isolating` = the two pairs differ in
exactly one variable and their cell sets differ by exactly that swap; both cells are then attributed to that variable.
Port is a function of (source, sink) in the specimens, so port-only changes do not exist: port dependence is
confounded with sink/source and is reported as such. Re-run when more port rows (DATAA/DATAB) land.

  python3.15t scripts/cycloneiv_localline_bits.py     -> docs/cycloneiv-localline-bits.md, tmp/cycloneiv_localline_bits.json
Log tmp/logs/cycloneiv_localline_bits.log
"""
import collections
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_bit_inventory as bi  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_pip_table as pt  # noqa: E402

log = logging.getLogger("localline_bits")


def ranges(vals):
    vals = sorted(vals)
    return "{" + ",".join(map(str, vals)) + "}" if len(vals) <= 8 else f"{len(vals)} values {{{vals[0]}..{vals[-1]}}}"


def analyse(table):
    pairs = sorted(table)                     # (src, snk, port)
    by_ss = {(k[0], k[1]): k for k in pairs}
    cells = sorted({c for v in table.values() for c in v})
    srcs = sorted({k[0] for k in pairs})
    snks = sorted({k[1] for k in pairs})
    out = {}
    # isolating pair-of-pairs: differ in exactly one of (src, snk) with the same port (port-only changes do not exist)
    iso = collections.defaultdict(list)
    for a in pairs:
        for b in pairs:
            if a >= b or a[2] != b[2]:
                continue
            diff = (a[0] != b[0]) + (a[1] != b[1])
            if diff != 1:
                continue
            sd = set(table[a]) ^ set(table[b])
            var = "source" if a[0] != b[0] else "sink"
            for c in sd:
                iso[c].append((a, b, var, len(sd)))
    for c in cells:
        on = [k for k in pairs if c in table[k]]
        onset = set(on)
        # dependency by enumeration over pairs sharing the other variable(s)
        dep_src = any((k[0] != k2[0] and k[1] == k2[1] and k[2] == k2[2] and ((k in onset) != (k2 in onset))) for k in pairs for k2 in pairs if k < k2)
        dep_snk = any((k[1] != k2[1] and k[0] == k2[0] and k[2] == k2[2] and ((k in onset) != (k2 in onset))) for k in pairs for k2 in pairs if k < k2)
        s_on, t_on = {k[0] for k in on}, {k[1] for k in on}
        prod = len(on) == len(s_on) * len(t_on)       # set pairs form a full product A x B (within existing pairs)
        # per-source / per-sink completeness: set for ALL existing pairs of that source / sink?
        full_src = all((k in onset) for k in pairs if k[0] in s_on)
        full_snk = all((k in onset) for k in pairs if k[1] in t_on)
        if len(on) == 1:
            rule = f"pair-unique: source {on[0][0]}, sink {on[0][1]} ({on[0][2]})"
            cls = "pair"
        elif full_src and len(s_on) < len(srcs) + 1 and not dep_snk:
            rule = f"set iff source in {ranges(s_on)} (all sinks)"
            cls = "source"
        elif full_snk and not dep_src:
            ports = sorted({k[2] for k in on})
            rule = f"set iff sink in {ranges(t_on)}, port {'/'.join(ports)} (all sources)"
            cls = "sink+port"
        else:
            rule = f"explicit: {len(on)} pairs, sources {ranges(s_on)}, sinks {ranges(t_on)}" + (" (product A x B)" if prod else "")
            cls = "joint"
        fl = iso.get(c, [])
        out[c] = dict(cell=c, n_set=len(on), dep_source=dep_src, dep_sink=dep_snk, cls=cls, rule=rule,
                      n_iso=sum(1 for f in fl if f[3] == 2), n_flip=len(fl), min_symdiff=min((f[3] for f in fl), default=None),
                      iso_vars=sorted({f[2] for f in fl}), example=[(f[0], f[1]) for f in fl[:1]], ports=sorted({k[2] for k in on}),
                      members=tuple(on))
    return cells, out


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/cycloneiv_localline_bits.log", "w")])
    g = cg.load(cg.die_of("EP4CGX150"))
    table, agree, drop = pt.build_table(g)
    cells, info = analyse(table)
    cnt_cls = collections.Counter(i["cls"] for i in info.values())
    with_iso = [c for c in cells if info[c]["n_iso"]]
    queue = [c for c in cells if not info[c]["n_iso"]]
    groups = collections.defaultdict(list)
    for c in cells:
        groups[info[c]["members"]].append(c)
    confounded = [v for v in groups.values() if len(v) > 1]
    msd = collections.Counter(info[c]["min_symdiff"] for c in cells)
    flipped = sum(1 for c in cells if info[c]["n_flip"])
    log.info("cells %d; with isolating pairs %d; without %d; classes %s", len(cells), len(with_iso), len(queue), dict(cnt_cls))
    ports = collections.Counter(k[2] for k in table)
    # evidence ids: specimen names per LAB (identical cell sets at all four LABs)
    ev = {}
    for fp, (lx, ly) in zip(bi.FORCED, bi.FORCED_LAB):
        ev[f"X{lx}Y{ly}"] = sorted(bi.forced_table(fp))[:2]
    L = ["# Cyclone IV LOCAL_LINE: per-cell attribution", "",
         "Generated by `scripts/cycloneiv_localline_bits.py` from the 240 same-LAB pairs (4 cells each), identical at the 4 specimen LABs (X10Y10, X58Y30, X37Y60, X100Y75).", "",
         "- Cells are tile-relative `(df, dv)`: frame = FX[x] + df, v = vy0 + 70 y + dv.",
         "- Specimens are spec-minus-base with exactly 4 cells each: two pairs never differ in ONE cell; the smallest change is a 1-for-1 swap. Isolating pair-of-pairs = same port, differ in exactly one of (source, sink), cell sets differ by exactly one swap; both cells are attributed to that variable.",
         f"- Port is a function of (source, sink) here (ports seen: {dict(ports)}); port-only changes do not exist, so port dependence is confounded with sink/source.",
         f"- Result: {len(cells)} cells; strict isolating evidence (cell sets differ by one swap) for {len(with_iso)}, none for {len(queue)}. Classes: {dict(cnt_cls)}.",
         f"- Weaker evidence: {flipped} cells flip in at least one single-variable pair-of-pairs; smallest cell-set difference per cell (cells: size): {dict(msd)}. The grid never produces a 2-cell swap because changing source flips source cells + pair cell, changing sink flips sink cells + pair cell.",
         f"- Confounded groups (cells with identical membership over all 240 pairs; no experiment in this grid separates them): {len(confounded)} groups, sizes {dict(collections.Counter(len(v) for v in confounded))}.", "",
         "| cell (df, dv) | set in pairs | depends on | class | strict isolating / single-variable flips (min diff) | rule |", "|---|---|---|---|---|---|"]
    for c in cells:
        i = info[c]
        dep = "+".join(n for n, f in (("source", i["dep_source"]), ("sink", i["dep_sink"])) if f) or "none"
        L.append(f"| ({c[0]}, {c[1]}) | {i['n_set']} | {dep} | {i['cls']} | {i['n_iso']} / {i['n_flip']} ({i['min_symdiff']}) {'/'.join(i['iso_vars'])} | {i['rule']} |")
    L += ["", "## Queue: cells with no isolating pair (need a new minimal specimen)", ""]
    if queue:
        L += [f"- {len(queue)} cells; by class: {dict(collections.Counter(info[c]['cls'] for c in queue))}",
              "- Needed: specimens whose spec-minus-base is 1-2 cells. Recipes: (a) source cells: base already has the source driving another sink of the same LAB (subtracts its two source cells), spec adds a second sink; (b) sink/pair cells: base drives the sink input from another path (LI), spec re-routes through LOCAL_LINE; vary one variable per pair. Confounded groups need a design that sets one member without the others."]
        by = collections.defaultdict(list)
        for c in queue:
            by[info[c]["cls"]].append(c)
        for k, v in by.items():
            L.append(f"- {k}: " + ", ".join(f"({a},{b})" for a, b in v[:40]) + (" ..." if len(v) > 40 else ""))
    else:
        L.append("- none")
    L += ["", "## Evidence ids", "", "- Each cell's isolating pairs are specimen-pair evidence rows (names `gxll_<src>_<snk>` at X10Y10; `gxll58x30_*`, `gxll37x60_*`, `gxll100x75_*` at the others, same cell sets). Full pair lists: `tmp/cycloneiv_localline_bits.json`."]
    (REPO / "docs/cycloneiv-localline-bits.md").write_text("\n".join(L) + "\n")
    (REPO / "tmp/cycloneiv_localline_bits.json").write_text(json.dumps(
        {f"{c[0]},{c[1]}": {k: v for k, v in info[c].items() if k != "members"} for c in cells}, default=list))
    log.info("queue (no isolating pair) %d", len(queue))


if __name__ == "__main__":
    main()
