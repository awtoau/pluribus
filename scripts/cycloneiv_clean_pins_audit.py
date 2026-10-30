#!/usr/bin/env python3.15t
"""Pins audit (#168, #165): cause of every GT ball the clean decoder does not match, over the gate member set.

  python3.15t scripts/cycloneiv_clean_pins_audit.py [--members-run 26] [--stride N]

Per GT ball (build.pin x postfit.vo ports): package of the design (rcf `device =`), ball -> site (F896 chain), site class
(io_fields.Decoder: fixed / unused / used / MISSING), direction status.  Log: tmp/logs/cycloneiv_clean_pins_audit.log.
"""
import argparse
import collections
import concurrent.futures as cf
import json
import logging
import os
import re
import sqlite3
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import io_decode as ID  # noqa: E402
from lifters.cycloneiv_clean import io_fields as IF  # noqa: E402
from lifters.cycloneiv_clean import tracer as T  # noqa: E402
import cycloneiv_clean_gate as G  # noqa: E402

log = logging.getLogger("pins_audit")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_pins_audit.log")


def package(d):
    m = re.search(r"device = (\w+);", open(os.path.join(d, "routing.rcf")).read(600))
    return m[1] if m else "?"


def audit_design(io, dec, d):
    pkg = package(d)
    ports, _, _ = G.parse_vo(os.path.join(d, "postfit.vo"))
    gt = {b: dr for n, (b, dr) in G.parse_pin(os.path.join(d, "build.pin")).items() if n in ports}
    val, _ = io.cff.read(os.path.join(d, "bitstream.rbf"))
    cl = io.classify(os.path.join(d, "bitstream.rbf"))
    old = {io.site_ball[s]: k for s, k in cl.items() if io.site_ball.get(s)}
    rows = []
    for b, dr in gt.items():
        s = io.chain.ball_site.get(b)
        old_ok = b in old and old[b] <= G.DIR[dr]
        if s is None:
            cause = "no_site"
        else:
            r = dec.decode(s, ID.site_vector(io.chain, val, s))
            cause = r["class"]
            if cause == "used":
                dd = r["direction"]
                cause = "used_" + (dd["value"] if dd["status"] != "ambiguous_MISSING" else "direction_ambiguous")
                if r["standard"]["status"] == "ambiguous_MISSING":
                    cause += "+std_ambiguous"
        rows.append((pkg[7:], b, dr, bool(old_ok), cause))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--members-run", type=int, default=26)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    con = sqlite3.connect(os.path.join(REPO, "databases", "cycloneiv", "gx150.db"))
    mem = json.loads(con.execute("select params from gate_runs where id=?", (a.members_run,)).fetchone()[0])["members"][:: a.stride]
    io = T.Io()
    dec = IF.Decoder(json.load(open(ID.DECODE_PATH)))
    cnt, per_ball = collections.Counter(), collections.Counter()
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for rows in ex.map(lambda m: audit_design(io, dec, os.path.join(REPO, "corpus", "cycloneiv", m.split("@")[0])), mem):
            for pkg, b, dr, old_ok, cause in rows:
                cnt[(pkg, "old_ok" if old_ok else "old_miss", dr, cause)] += 1
                if not old_ok:
                    per_ball[(b, cause)] += 1
    for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]):
        log.info("%7d  %s", v, k)
    log.info("old_miss total %d", sum(v for k, v in cnt.items() if k[1] == "old_miss"))
    log.info("top balls %s", per_ball.most_common(40))


if __name__ == "__main__":
    main()
