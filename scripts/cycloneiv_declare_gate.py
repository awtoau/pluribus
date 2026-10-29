#!/usr/bin/env python3.15t
"""Declare the Cyclone IV required gate set as corpus_members(required=1) (#141).

  PLURIBUS_SQLITE_PATH=databases/cycloneiv/gx150.db python3.15t scripts/cycloneiv_declare_gate.py

Set = `gx150_rb*` designs of the odd crc32 split, same selection as
`cycloneiv_ddb_trace.py score --designs 'gx150_rb*' --split odd`. Idempotent; claims_register.py calls declare() because it rebuilds corpus_members every run.
Log: tmp/logs/cycloneiv_declare_gate.log
"""
import logging
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_common as cm  # noqa: E402
import db  # noqa: E402
import schema  # noqa: E402
from provenance import corpus as C  # noqa: E402
from provenance import evidence_io as E  # noqa: E402

log = logging.getLogger("cycloneiv_declare_gate")


def declare(conn, commit):
    names = [n for n in cc.designs("gx150_rb*") if cm.split_of(n, "odd")]
    for n in names:
        C.ensure_member(conn, "cycloneiv", n, "oracle-build", commit, device="EP4CGX150",
                        source_ref=f"corpus/cycloneiv/{n}", gate_script="scripts/cycloneiv_ddb_trace.py",
                        required=True)
    return len(names)


def main():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_declare_gate.log"))])
    schema.init()
    commit = E.git_head(REPO)
    with db.engine().begin() as conn:
        E.ensure_family(conn, "cycloneiv")
        n = declare(conn, commit)
        C.ensure_criterion(conn, "cycloneiv")
    log.info("cycloneiv: %d required members declared", n)


if __name__ == "__main__":
    main()
