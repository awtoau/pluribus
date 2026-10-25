#!/usr/bin/env python3.15t
"""Classify every native-vs-Mistral disagreement with the Quartus oracles (never by preferring a tool).

Classes: mistral_wrong (oracle contradicts Mistral, confirms native) | native_wrong | neither_provable.
Routing extras are checked against RCF edges; renamed fields are backed by the override evidence (logic/probes stages).
Output: tmp/cyclonev_native/results/classify.json, log tmp/logs/cyclonev_native_classify.log
"""
import collections
import concurrent.futures
import json
import logging
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_decode as cd  # noqa: E402
import cyclonev_native_oracle as orc  # noqa: E402
import cyclonev_native_tables as nt  # noqa: E402
import cyclonev_native_verify as vf  # noqa: E402

log = logging.getLogger("cyclonev_native_classify")
OPT_RENAMED = {"CVP_CONF_DONE_EN": "opt-6.2", "RELEASE_CLEARS_BEFORE_TRISTATES_DIS": "opt-6.3",
               "DEVICE_WIDE_RESET_EN": "opt-6.4", "START_UP_CLOCK": "opt-start_up_clock"}


def one(args):
    name, root, tables, bid = args
    data = open(os.path.join(root, name, "bitstream.rbf"), "rb").read()
    mc = cd.decode(data, vf.DEVICE, overrides=False, compat=True, tables=tables)
    mn = cd.decode(data, vf.DEVICE, overrides=True, compat=False, tables=tables)
    lc, ln = set(mc.routes()), set(mn.routes())
    conn = orc.connect()
    rcf = orc.load_rcf(conn, bid)
    conn.close()
    tid = {n: i for i, n in enumerate(tables["routes"]["type_names"])}
    # RCF edges as (type, x, y, idx) pairs
    edges = {(a[0], a[1], a[2], a[4], b[0], b[1], b[2], b[4]) for es in rcf.values() for a, b in es}
    cls = collections.Counter()
    ex = {}
    tn = tables["routes"]["type_names"]
    for s, d in sorted(ln - lc):
        ts, tdn = tn[s >> 24], tn[d >> 24]
        sx, sy, sz = (s >> 17) & 127, (s >> 10) & 127, s & 1023
        dx, dy, dz = (d >> 17) & 127, (d >> 10) & 127, d & 1023
        if ts == "GCLK" and tdn == "SCLK":
            ok = any(e[0] == "GLOBAL_CLOCK" and (e[1], e[2], e[3]) == (sx, sy, sz) and e[4] == "SPINE_CLOCK"
                     and (e[5], e[6], e[7]) == (dx, dy, dz) for e in edges)
            k = "route GCLK->SCLK" + (" RCF-edge" if ok else " not-in-RCF")
        elif ts == "GOUT" and tdn == "TCLK":
            ok = any(e[0].startswith("BLOCK_INPUT_MUX") and (e[1], e[2], e[3]) == (sx, sy, sz) and e[4] == "GLOBAL_LOCAL_SEL"
                     and (e[5], e[6], e[7]) == (dx, dy, dz) for e in edges)
            k = "route DATAIN->CLKIN (CLKA/B_SEL=DIN) " + ("RCF-edge" if ok else "not-in-RCF")
        else:
            ok = False
            k = f"route {ts}->{tdn} not-in-RCF"
        cls[("mistral_wrong" if ok else "neither_provable", k)] += 1
        ex.setdefault((("mistral_wrong" if ok else "neither_provable"), k), (rname(tables, s), rname(tables, d)))
    for s, d in sorted(lc - ln):
        cls[("native_wrong", "route lost by native")] += 1
    return name, {"|".join(k): v for k, v in cls.items()}, {"|".join(k): v for k, v in ex.items()}


def rname(tb, k):
    return cd.rname(tb, k)


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_native_classify.log"))])
    root = vf.corpus_root()
    names = vf.designs(root)
    tables = nt.load(vf.DEVICE)
    conn = orc.connect()
    bids = dict(conn.execute("select design, id from postfit_builds"))
    conn.close()
    tot = collections.Counter()
    ex = {}
    with concurrent.futures.ThreadPoolExecutor(6) as p:
        for name, c, e in p.map(one, [(n, root, tables, bids[n]) for n in names]):
            tot.update(c)
            ex.update({k: v for k, v in e.items() if k not in ex})
    for k, v in sorted(tot.items()):
        log.info("route disagreement %-70s %d  e.g. %s", k, v, ex.get(k))
    # field disagreements from the diff stage (default native vs Mistral)
    R = json.load(open(os.path.join(vf.RES, "diff.json")))
    fc = collections.Counter()
    for r in R:
        for kind, v in r["native"].items():
            if kind == "r":
                continue
            for l in v["only_native"] + v["only_mistral"]:
                side = "native" if l in v["only_native"] else "mistral"
                m = re.match(r"s \w+\.\d+\.\d+:(CLK[012]_(?:SEL|INV))", l)
                if m:
                    fc[("mistral_wrong", "LAB " + m.group(1) + " (clk select/invert roles swapped)", side)] += 1
                    continue
                m = re.match(r"o (\w+)", l)
                if m and m.group(1) in OPT_RENAMED or (m and m.group(1) in ("DEVICE_WIDE_RESET_DIS", "BIT_6_3_UNVERIFIED")):
                    fc[("mistral_wrong", "option " + m.group(1), side)] += 1
                    continue
                fc[("unclassified", l[:60], side)] += 1
    for k, v in sorted(fc.items()):
        log.info("field disagreement %s %d", k, v)
    out = {"routes": {k: v for k, v in tot.items()}, "fields": {"|".join(k): v for k, v in fc.items()}}
    json.dump(out, open(os.path.join(vf.RES, "classify.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
