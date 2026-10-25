#!/usr/bin/env python3
"""Does a lifted design look like real logic, or like noise?  Detection statistics only.

Reads lifted designs from a pluribus DB (luts / ffs / nets / net_fanout / pad_map / cv_hard_cells)
and compares one or more IMAGE labels against
  - a CORPUS of known-real designs (label prefix; min..max and median per metric), and
  - CONTROL labels: bitstreams with random bytes in place of the configuration RAM.
Per metric the verdict is R (inside the corpus range), C (inside the control range), ? (neither),
- (metric cannot separate the two: corpus and control ranges overlap, or scale-dependent count).  No key handling, no decryption.

Subcommands (all log to ./tmp/logs/lift_realism.log):
  lift    load .bt decompiles into the DB, one load.py at a time (corpus / controls / images)
  report  metric table; --json writes the raw numbers

  PLURIBUS_SQLITE_PATH=tmp/realism.db python3.15t scripts/lift_realism.py lift \
      --device 5CEBA4U19C8 --lifter cyclonev --label-prefix cv_corpus_ --bt 'corpus/cyclonev/*/decomp.bt'
  PLURIBUS_SQLITE_PATH=tmp/realism.db python3.15t scripts/lift_realism.py report \
      --corpus-prefix cv_corpus_ --control ctl_a ctl_b --image img_x img_y
"""
import argparse
import glob
import json
import logging
import math
import os
import re
import statistics
import subprocess
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

log = logging.getLogger("lift_realism")
PINS = "abcdef"
NET_RE = re.compile(r"^n\d+$")
# load.py of a ~2 MB image: 2-6 s measured; 60 s no-completion = hung, step fails and is logged.
STEP_LIMIT_S = 60


def _q(conn, sql, *a):
    cur = conn.cursor()
    cur.execute(sql, a)
    return cur.fetchall()


def _scc_nodes_in_cycles(adj):
    """Iterative Tarjan: number of nodes in non-trivial SCCs, number of SCCs, self-loops."""
    index, low, on, stack, idx = {}, {}, set(), [], [0]
    in_cycle, n_scc = 0, 0
    for root in adj:
        if root in index:
            continue
        work = [(root, iter(adj[root]))]
        index[root] = low[root] = idx[0]; idx[0] += 1
        stack.append(root); on.add(root)
        while work:
            v, it = work[-1]
            adv = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = idx[0]; idx[0] += 1
                    stack.append(w); on.add(w)
                    work.append((w, iter(adj.get(w, ()))))
                    adv = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if adv:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop(); on.discard(w); comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    in_cycle += len(comp); n_scc += 1
    return in_cycle, n_scc


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0


def metrics(conn, label):
    """Dict metric -> number for one lifted design (None when not computable)."""
    r = _q(conn, "select id from bitstreams where label=?", label)
    if not r:
        raise SystemExit(f"label {label!r} not in DB")
    b = r[0][0]
    luts = _q(conn, "select cell,init,a,b,c,d,e,f,z,deps from luts where bitstream=?", b)
    ffs = _q(conn, "select cell,clk,ce,d,q,lsr from ffs where bitstream=?", b)
    fan = _q(conn, "select net,cell_type,cell,pin from net_fanout where bitstream=?", b)
    pads = _q(conn, "select direction,net_in,net_out from pad_map where bitstream=?", b)
    n_nets = _q(conn, "select count(*) from nets where bitstream=?", b)[0][0]
    try:
        hard = _q(conn, "select data from cv_hard_cells where bitstream=?", b)
    except Exception:
        hard = []
    m = {"luts": len(luts), "ffs": len(ffs), "nets": n_nets, "pads": len(pads), "hard_cells": len(hard)}
    m["ff_per_lut"] = len(ffs) / len(luts) if luts else None

    # ---- LUT masks ----
    const = [l for l in luts if set(l[1]) <= {"0"} or set(l[1]) <= {"1"}]
    act = [l for l in luts if l not in const]
    m["lut_const_frac"] = len(const) / len(luts) if luts else None
    if act:
        sup = []
        for l in act:
            deps = json.loads(l[9]) if isinstance(l[9], str) else (l[9] or [])
            sup.append(len(deps))
        k = max(len(l[1]).bit_length() - 1 for l in act)
        m["lut_support_le1_frac"] = sum(s <= 1 for s in sup) / len(act)
        m["lut_support_le2_frac"] = sum(s <= 2 for s in sup) / len(act)
        m["lut_full_support_frac"] = sum(s >= k for s in sup) / len(act)
        m["lut_support_mean"] = statistics.fmean(sup)
        cnt = Counter(l[1] for l in act)
        m["mask_distinct_frac"] = len(cnt) / len(act)
        m["mask_top_share"] = cnt.most_common(1)[0][1] / len(act)
        dens = [l[1].count("1") / len(l[1]) for l in act]
        m["mask_density_mean"] = statistics.fmean(dens)
        m["mask_density_mid_frac"] = sum(0.35 <= d <= 0.65 for d in dens) / len(act)
        unw = 0
        for l in act:
            deps = json.loads(l[9]) if isinstance(l[9], str) else (l[9] or [])
            unw += any(l[2 + PINS.index(p)] is None for p in deps)
        m["lut_dep_on_unwired_pin_frac"] = unw / len(act)
    # ---- drivers / sinks ----
    drivers = Counter()
    for l in luts:
        if l[8]:
            drivers[l[8]] += 1
    for f in ffs:
        if f[4]:
            drivers[f[4]] += 1
    for p in pads:
        if p[0] == "in" and p[1]:
            drivers[p[1]] += 1
    for h in hard:
        d = h[0] if isinstance(h[0], dict) else json.loads(h[0])
        for net in _walk_outs(d.get("outs")):
            drivers[net] += 1
    sinks = Counter()
    for net, ct, cell, pin in fan:
        sinks[net] += 1
    for p in pads:
        if p[0] != "in" and p[2]:
            sinks[p[2]] += 1
    sink_nets = [n for n in sinks if NET_RE.match(n)]
    m["undriven_sink_net_frac"] = (sum(n not in drivers for n in sink_nets) / len(sink_nets)) if sink_nets else None
    m["multi_driver_net_frac"] = (sum(v > 1 for v in drivers.values()) / len(drivers)) if drivers else None
    dr = [n for n in drivers if NET_RE.match(n)]
    m["driven_no_sink_frac"] = (sum(n not in sinks for n in dr) / len(dr)) if dr else None
    lz = [l[8] for l in act if l[8]]
    m["lut_out_unused_frac"] = (sum(z not in sinks for z in lz) / len(lz)) if lz else None
    fo = [sinks[n] for n in dr if n in sinks]
    if fo:
        m["fanout_mean"] = statistics.fmean(fo)
        m["fanout_eq1_frac"] = sum(x == 1 for x in fo) / len(fo)
        m["fanout_p99"] = _pct(fo, 0.99)
        m["fanout_max_over_nets"] = max(fo) / max(1, n_nets)
    # ---- FFs ----
    if ffs:
        m["ff_clk_set_frac"] = sum(1 for f in ffs if f[1]) / len(ffs)
        m["ff_d_driven_frac"] = sum(1 for f in ffs if f[3] and (f[3] in drivers or f[3].startswith("1'b"))) / len(ffs)
        clks = Counter(f[1] for f in ffs if f[1])
        m["ff_clock_nets"] = len(clks)
        m["ff_top_clock_share"] = clks.most_common(1)[0][1] / len(ffs) if clks else None
        m["ff_ce_set_frac"] = sum(1 for f in ffs if f[2]) / len(ffs)
    # ---- combinational loops (mask-dependent pins only) ----
    zmap = {l[8]: i for i, l in enumerate(luts) if l[8]}
    adj = {i: set() for i in range(len(luts))}
    selfl = 0
    for i, l in enumerate(luts):
        deps = json.loads(l[9]) if isinstance(l[9], str) else (l[9] or [])
        for p in deps:
            j = zmap.get(l[2 + PINS.index(p)])
            if j is None:
                continue
            if j == i:
                selfl += 1
            else:
                adj[j].add(i)
    in_cyc, n_scc = _scc_nodes_in_cycles(adj)
    m["comb_loop_lut_frac"] = (in_cyc + selfl) / len(luts) if luts else None
    # ---- pads ----
    if pads:
        ins = [p for p in pads if p[0] == "in"]
        outs = [p for p in pads if p[0] != "in"]
        m["pad_in_frac"] = len(ins) / len(pads)
        m["pad_in_used_frac"] = (sum(1 for p in ins if p[1] in sinks) / len(ins)) if ins else None
        m["pad_out_driven_frac"] = (sum(1 for p in outs if p[2] in drivers) / len(outs)) if outs else None
    return m


def _walk_outs(o):
    if isinstance(o, str):
        if NET_RE.match(o):
            yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _walk_outs(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            yield from _walk_outs(v)


# Scale-dependent counts: shown, never judged.
INFO = {"luts", "ffs", "nets", "pads", "hard_cells", "fanout_p99"}


def _ranges(corpus, ctl):
    lo, hi = min(corpus), max(corpus)
    clo, chi = min(ctl), max(ctl)
    pad = 0.25 * max(abs(clo), abs(chi), 1e-9)
    return (lo, hi), (clo - pad, chi + pad)


def discriminates(corpus, ctl):
    """True when the corpus range and the (padded) control range do not overlap."""
    if not corpus or not ctl:
        return False
    (lo, hi), (clo, chi) = _ranges(corpus, ctl)
    return hi < clo or chi < lo


def verdict(v, corpus, ctl):
    """R inside corpus range, C inside control range, ? neither; '-' if the metric cannot separate them."""
    if v is None or not discriminates(corpus, ctl):
        return "-"
    (lo, hi), (clo, chi) = _ranges(corpus, ctl)
    in_c = lo - 1e-9 <= v <= hi + 1e-9
    in_r = clo <= v <= chi
    return "R" if in_c else "C" if in_r else "?"


def fmt(v):
    if v is None:
        return "n/a"
    if isinstance(v, int):
        return str(v)
    return f"{v:.4g}"


def cmd_report(a):
    from db import connect_threadsafe
    conn = connect_threadsafe()
    labels = [r[0] for r in _q(conn, "select label from bitstreams where label like ? order by label", a.corpus_prefix + "%")]
    if not labels:
        raise SystemExit(f"no corpus labels with prefix {a.corpus_prefix!r}")
    cm = {l: metrics(conn, l) for l in labels}
    ctl = {l: metrics(conn, l) for l in a.control}
    img = {l: metrics(conn, l) for l in a.image}
    keys = list(next(iter(cm.values())).keys())
    for d in list(ctl.values()) + list(img.values()):
        for k in d:
            if k not in keys:
                keys.append(k)
    rows = []
    hdr = ["metric", f"corpus min..max (median) n={len(labels)}"] + [f"ctl:{l}" for l in ctl] + [f"img:{l}" for l in img]
    for k in keys:
        cv = [d[k] for d in cm.values() if d.get(k) is not None]
        cr = (f"{fmt(min(cv))}..{fmt(max(cv))} ({fmt(statistics.median(cv))})" if cv else "n/a")
        cvals = [d.get(k) for d in ctl.values() if d.get(k) is not None]
        row = [k, cr] + [fmt(d.get(k)) for d in ctl.values()]
        for d in img.values():
            v = d.get(k)
            row.append(f"{fmt(v)} [{'-' if k in INFO else verdict(v, cv, cvals)}]")
        rows.append(row)
    w = [max(len(str(r[i])) for r in rows + [hdr]) for i in range(len(hdr))]
    out = ["  ".join(str(c).ljust(w[i]) for i, c in enumerate(hdr))]
    out += ["  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)) for r in rows]
    judged = [k for k in keys if k not in INFO]
    out.append("")
    for l, d in img.items():
        vs = Counter(verdict(d.get(k), [c[k] for c in cm.values() if c.get(k) is not None],
                             [c[k] for c in ctl.values() if c.get(k) is not None]) for k in judged
                     if d.get(k) is not None)
        out.append(f"summary {l}: R={vs['R']} C={vs['C']} ?={vs['?']} (of {sum(v for k, v in vs.items() if k != '-')} discriminating metrics)")
    text = "\n".join(out)
    log.info("\n%s", text)
    if a.json:
        json.dump({"corpus": cm, "control": ctl, "image": img}, open(a.json, "w"), indent=1)


def cmd_lift(a):
    files = sorted(glob.glob(a.bt))
    bad = 0
    for f in files:
        name = os.path.basename(os.path.dirname(f)) if a.label_from_dir else os.path.splitext(os.path.basename(f))[0]
        label = a.label_prefix + name
        cmd = [sys.executable if a.python is None else a.python, os.path.join(REPO, "load.py"), "--lifter", a.lifter,
               "--device", a.device, "--label", label, "--config", f]
        try:
            r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=a.step_limit)
        except subprocess.TimeoutExpired:
            log.error("FAIL %s: load exceeded %ds", label, a.step_limit)
            bad += 1
            continue
        if r.returncode:
            log.error("FAIL %s rc=%d: %s", label, r.returncode, (r.stderr or r.stdout).strip().splitlines()[-1:])
            bad += 1
        else:
            log.info("ok %s: %s", label, r.stdout.strip().splitlines()[-1])
    log.info("lift: %d/%d ok", len(files) - bad, len(files))
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("report")
    r.add_argument("--corpus-prefix", required=True)
    r.add_argument("--control", nargs="*", default=[])
    r.add_argument("--image", nargs="+", required=True)
    r.add_argument("--json")
    l = sp.add_parser("lift")
    l.add_argument("--bt", required=True, help="glob of .bt decompiles")
    l.add_argument("--label-prefix", default="")
    l.add_argument("--label-from-dir", action="store_true", help="label = parent directory name (corpus layout)")
    l.add_argument("--lifter", default="cyclonev")
    l.add_argument("--device", required=True)
    l.add_argument("--python", default=None, help="interpreter for load.py (python3.15t)")
    l.add_argument("--step-limit", type=int, default=STEP_LIMIT_S)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(REPO, "tmp", "logs", "lift_realism.log"))])
    (cmd_report if a.cmd == "report" else cmd_lift)(a)


if __name__ == "__main__":
    main()
