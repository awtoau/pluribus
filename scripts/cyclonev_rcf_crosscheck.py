#!/usr/bin/env python3
"""Cross-check route_hops (timing-report routes) against rcf_routes (full RCF trees).

Per build (design):
  forward : every distinct RE hop in route_hops (net = driver atom) must be in the RCF of that net.
            I-form elements (TYPE:XxYySnIk) match on (type,x,y,n,idx); block-port elements (the
            RCF `B:` form) have no comparable n/idx in route_hops, so match on (type,x,y).
  backward: RCF nets with no route_hops hop at all (RCF-only) and RCF elements, on nets that do
            have timing hops, that no timing path touches.
Usage: python3.15t scripts/cyclonev_rcf_crosscheck.py [design ...]
Log: tmp/logs/cyclonev_rcf_crosscheck.log
"""
import logging
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(REPO / "corpus" / "cyclonev" / "corpus.db"))
sys.path.insert(0, str(REPO))

import db  # noqa: E402

LOG = REPO / "tmp" / "logs" / "cyclonev_rcf_crosscheck.log"
log = logging.getLogger("rcf_crosscheck")


# Block sites listed as RE rows in route_hops; the RCF carries routing elements only.
CELL_SITES = {"CLKCTRL", "DSP", "FF", "IOIBUF", "IOPAD", "LABCELL", "MLABCELL", "M10K"}


def net_of(driver):
    return driver.rsplit("|", 1)[0] if driver and "|" in driver else driver


def check(conn, build, design):
    rcf = defaultdict(set)       # net -> {keys}
    rcf_all = defaultdict(set)   # net -> {full (type,x,y,n,idx or port)} for I-form only
    bform = set()
    for net, el, x, y, n, idx, pp, kind in conn.execute(
            "select net,element,x,y,n,idx,port_path,kind from rcf_routes where build=?", (build,)):
        if kind == "dest":
            continue
        if pp is not None:
            bform.add(el)
            rcf[net].add((el, x, y))
        else:
            rcf[net].add((el, x, y, n, idx))
    hops = set()
    for drv, frm, el, x, y, n, idx in conn.execute(
            "select driver,from_node,loc_kind,x,y,n,idx from route_hops where build=? and type='RE'",
            (build,)):
        if x is None or el in CELL_SITES:
            continue
        hops.add((net_of(drv), el, x, y, n, idx))   # driver None: pad hops, net unknown
    tot = Counter()
    miss = Counter()
    miss_ex = {}
    seen_in_rcf = defaultdict(set)
    nets_with_hops = set()
    unmapped = Counter()
    keynets = defaultdict(set)
    for nm, ks in rcf.items():
        for k in ks:
            keynets[k].add(nm)
    anynet = keynets
    for net, el, x, y, n, idx in hops:
        if net is None or net not in rcf:   # pad hops (driver None), DSP/M10K-driven nets: match on any net
            unmapped[el] += 1
            key = (el, x, y) if el in bform else (el, x, y, n, idx)
            tot[el] += 1
            if key not in anynet:
                miss[el] += 1
                miss_ex.setdefault(el, (net, key, None))
            for nm in anynet.get(key, ()):
                nets_with_hops.add(nm)
                seen_in_rcf[nm].add(key)
            continue
        nets_with_hops.add(net)
        key = (el, x, y) if el in bform else (el, x, y, n, idx)
        tot[el] += 1
        if net in rcf and key in rcf[net]:
            seen_in_rcf[net].add(key)
        else:
            miss[el] += 1
            miss_ex.setdefault(el, (net, key, net in rcf))
    n_hops, n_miss = sum(tot.values()), sum(miss.values())
    n_unmapped = sum(unmapped.values())
    only_nets = [n for n in rcf if n not in nets_with_hops]
    hop_nets_in_rcf = [n for n in nets_with_hops if n in rcf]
    rcf_elems_on_hop_nets = sum(len(rcf[n]) for n in hop_nets_in_rcf)
    seen = sum(len(seen_in_rcf[n]) for n in hop_nets_in_rcf)
    res = dict(design=design, hops_matched_by_key_only=n_unmapped, hops=n_hops, hops_in_rcf=n_hops - n_miss, rcf_nets=len(rcf),
               hop_nets=len(nets_with_hops), hop_nets_in_rcf=len(hop_nets_in_rcf),
               rcf_only_nets=len(only_nets), rcf_elems_on_hop_nets=rcf_elems_on_hop_nets,
               rcf_elems_seen_by_timing=seen)
    log.info("%s", res)
    for el, c in miss.most_common(8):
        log.info("  %s miss %s/%s  e.g. %s", el, c, tot[el], miss_ex[el])
    log.info("  rcf-only examples: %s", sorted(only_nets)[:5])
    return res, miss


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(LOG, mode="w"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    conn = db.connect_threadsafe()
    rows = conn.execute("select id,design from postfit_builds where status='ok' order by design").fetchall()
    want = set(sys.argv[1:])
    agg = Counter()
    allmiss = Counter()
    for bid, design in rows:
        if want and design not in want:
            continue
        res, miss = check(conn, bid, design)
        for k, v in res.items():
            if k != "design":
                agg[k] += v
        allmiss.update(miss)
    log.info("TOTAL %s", dict(agg))
    log.info("MISS BY TYPE %s", dict(allmiss))


if __name__ == "__main__":
    main()
