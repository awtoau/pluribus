#!/usr/bin/env python3.15t
"""Classify the undriven-and-read nets of a lifted MachXO2 label (#113).

    PLURIBUS_SQLITE_PATH=x.db scripts/undriven_classify.py --label V07 --config <.config> [--list N]

Undriven = net read by a LUT/FF input (net_fanout) with no LUT z / FF q / EFB out / pad-in driver.
Wire members come from re-running the lifter (raw `n<k>` names are stable); class = first
matching rule on the member wire names.  Log: tmp/logs/undriven_classify.log
"""
import argparse
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from sqlalchemy import text  # noqa: E402
import db  # noqa: E402
from lifters.machxo2_lift import MachXO2Lift  # noqa: E402

LOG = REPO / "tmp/logs/undriven_classify.log"

GLOBAL_RX = re.compile(r"^(G_|U_|BRANCH_|D_)")
EDGE_RX = re.compile(r"^[EW]\d_H0")


def classify(wires, dropped, roots, max_col):
    """dropped = names of config-arc ends gkey() returned None for on this net's arcs."""
    if any(GLOBAL_RX.match(n) for n in dropped):
        return "global-spine arc dropped (#109)"
    if any(EDGE_RX.match(n) for n in dropped):
        return "edge H06 stub arc dropped"
    for w in roots:
        if isinstance(w, tuple) and re.match(r"^H06[EW]", str(w[2])) and (w[0] <= 2 or w[0] >= max_col - 2):
            return "edge H06 turnaround (no driver at edge wire)"
    names = {str(w[2]) for w in wires if isinstance(w, tuple)}
    if any(re.match(r"^(CLK\d|JCLK|LSR\d|CE\d)$", n) for n in names) and any(
            isinstance(w, tuple) and re.match(r"^(JCLK|CLK)", str(w[2])) for w in wires):
        return "clock-pin net with no driver"
    return "other"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--device", default="LCMXO2-1200")
    ap.add_argument("--list", type=int, default=0, help="also list N nets per class")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG, "w")])
    log = logging.getLogger("undriven")
    with db.engine().connect() as c:
        b = c.execute(text("select id from bitstreams where label=:l"), {"l": a.label}).scalar()
        q = text("""
            select distinct f.net from net_fanout f where f.bitstream=:b and f.net not like '1''b%'
            and f.net not in (select z from luts where bitstream=:b and z is not null)
            and f.net not in (select q from ffs where bitstream=:b and q is not null)
            and f.net not in (select out_net from net_fanout where bitstream=:b and out_net is not null)
            and f.net not in (select net_in from pad_map where bitstream=:b and net_in is not null)
            and f.net not in (select net from efb_ports where bitstream=:b and direction='out')""")
        und = [r[0] for r in c.execute(q, {"b": b})]
    lift = MachXO2Lift(a.device)
    pc = lift.parse_config(a.config)
    d = lift.recover_netlist(pc)
    members = defaultdict(list)
    for k in d.dsu.p:
        r = d.dsu.find(k)
        if r in d.net_name:
            members[d.net_name[r]].append(k)
    sinks = set()
    for (r, cc, sink, src) in pc.arcs:
        k = lift.gkey(r, cc, sink)
        if k is not None:
            sinks.add(k)
    roots = {}
    for n, ws in members.items():
        roots[n] = sorted((w for w in ws if w not in sinks), key=str)
    max_col = lift.chip.get_max_col()
    dropped = defaultdict(set)
    for (r, cc, sink, src) in pc.arcs:
        ks, kd = lift.gkey(r, cc, sink), lift.gkey(r, cc, src)
        if (ks is None) != (kd is None):
            other, nm = (ks, src if kd is None else sink)
            other = ks if kd is None else kd
            nm = src if kd is None else sink
            if other in d.dsu.p and d.dsu.find(other) in d.net_name:
                dropped[d.net_name[d.dsu.find(other)]].add(nm)
    by = defaultdict(list)
    for n in sorted(und):
        if n in members:
            by[classify(members[n], dropped.get(n, set()), roots.get(n, []), max_col)].append(n)
        elif n.startswith("ghost_d_"):
            by["ghost-D (EBR OUTREG bypass)"].append(n)
        else:
            by["renamed/not-in-dsu"].append(n)
    log.info("undriven-and-read nets: %d", len(und))
    for cls, ns in sorted(by.items(), key=lambda x: -len(x[1])):
        log.info("  %-28s %d", cls, len(ns))
        for n in ns[:a.list]:
            log.info("      %s  roots(col,row,wire)=%s", n, roots.get(n, [])[:4])
    return 0


if __name__ == "__main__":
    sys.exit(main())
