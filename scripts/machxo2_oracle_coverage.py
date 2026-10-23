#!/usr/bin/env python3
"""Coverage of the MachXO2 Diamond oracle corpus: which routing connections
defined in device-db are exercised by at least one corpus design.

A fault the comparison does not find may simply be untested; this reports how
much is tested.  Connection = (tile type, dest wire, source wire) from the
`.mux` blocks of device-db/MachXO2/tiledata/<type>/bits.db; exercised = an
`arc:` line of that type in any corpus `decoded.config`.

Usage: python3.15t scripts/machxo2_oracle_coverage.py [--corpus DIR]
Log:   tmp/logs/machxo2_oracle_coverage.log
"""
import argparse, collections, glob, logging, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_db(dbroot):
    db = collections.defaultdict(set)
    for d in sorted(glob.glob(os.path.join(dbroot, "tiledata", "*"))):
        f = os.path.join(d, "bits.db")
        if not os.path.exists(f):
            continue
        dst = None
        for line in open(f):
            s = line.strip()
            if s.startswith(".mux "):
                dst = s.split()[1]
            elif s.startswith("."):
                dst = None
            elif dst and s:
                db[os.path.basename(d)].add((dst, s.split()[0]))
    return db


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default=os.path.join(REPO, "corpus", "machxo2", "diamond-fuzz"))
    ap.add_argument("--dbroot", default=os.path.join(REPO, "device-db", "MachXO2"))
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.FileHandler(os.path.join(REPO, "tmp", "logs", "machxo2_oracle_coverage.log")),
        logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("cov")
    db = load_db(a.dbroot)
    used, unknown = collections.defaultdict(set), collections.Counter()
    cfgs = glob.glob(os.path.join(a.corpus, "*", "decoded.config"))
    if not cfgs:
        log.error("no decoded.config under %s", a.corpus)
        sys.exit(1)
    for f in cfgs:
        t = None
        for line in open(f):
            s = line.strip()
            if s.startswith(".tile"):
                t = s.split(None, 1)[1].split(":")[-1]
            elif s.startswith("arc:") and t:
                _, dst, src = s.split()
                if (dst, src) in db.get(t, ()):
                    used[t].add((dst, src))
                else:
                    unknown[t] += 1
    tot = sum(len(v) for v in db.values())
    hit = sum(len(v) for v in used.values())
    log.info("designs: %d; connections defined: %d; exercised by >=1 design: %d (%.1f%%)",
             len(cfgs), tot, hit, 100 * hit / tot)
    log.info("arcs in configs missing from the db (should be 0): %d", sum(unknown.values()))
    typed = [t for t in db if db[t]]
    log.info("tile types with routing: %d; never exercised: %d", len(typed),
             sum(1 for t in typed if not used[t]))
    for n, h, t in sorted(((len(db[t]), len(used[t]), t) for t in typed), reverse=True)[:12]:
        log.info("  %-22s defined %5d  exercised %5d  %5.1f%%", t, n, h, 100 * h / n)


if __name__ == "__main__":
    main()
