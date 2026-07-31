#!/usr/bin/env python3.15t
"""Report the recovered MachXO2 EFB interface, paired by direction.

A count of `efb_ports` rows is a weak check: a wrong wire pattern would also
produce rows.  What actually shows the recovery is sound is whether the port
NAMES pair up into the hard block's documented interfaces -- a WISHBONE slave
needs its address and data inputs alongside the data output and the ack, and
recovering only one half of a bus is a symptom, not a result.  That is the
check issue #100 asked for, so this script makes it repeatable.

For each interface group (WISHBONE, SPI, I2C, timer/counter, PLL, config) it
lists the recovered inputs against the recovered outputs and flags buses whose
two halves disagree in width.  Ports the design never routed are simply absent;
that is expected -- V07 uses the WISHBONE side and nothing else -- so an absent
group is reported as unused, not as a failure.

Usage:
    scripts/efb_interface_report.py [--bitstream LABEL]
Logs to `tmp/logs/efb_interface_report.log`.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
LOG_DIR = REPO / "tmp/logs"

import db  # noqa: E402

# Interface groups, matched against the canonical port name in order.  The EFB
# is several unrelated peripherals behind one block, so grouping by peripheral
# is what makes the pairing legible.
# Order matters, and the timer/counter pattern is spelled out rather than left
# as a "^JTC" prefix on purpose: JTCK is the JTAG test clock, not a timer port,
# and a prefix match files it under timer/counter.
GROUPS = [
    ("WISHBONE",      re.compile(r"^JWB")),
    ("SPI",           re.compile(r"^JSPI")),
    ("I2C",           re.compile(r"^JI2C")),
    ("timer/counter", re.compile(r"^JTC(CLKI|IC|RSTN|OC|INT)$")),
    ("PLL",           re.compile(r"^JPLL")),
    ("UFM",           re.compile(r"^JUFM")),
    ("config",        re.compile(r"^CFG")),
    ("JTAG",          re.compile(r"^(JTCK|JTDI|JTDO|JRSTN|JSHIFTDR|JUPDATE|JF\d)$")),
]

# Buses whose input and output halves should be the same width if both are
# present at all.  Mismatched halves mean half a bus was recovered.
BUS_PAIRS = [("JWBDATI", "JWBDATO")]


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("efb_interface_report")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "efb_interface_report.log", mode="w")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


def group_of(port: str) -> str:
    for name, rx in GROUPS:
        if rx.match(port):
            return name
    return "other"


def fetch(label: str | None):
    conn = db.connect_threadsafe()
    cur = conn.cursor()
    sql = """select b.label, p.port_name, p.direction, p.net,
                    coalesce(nn.name, '')
             from efb_ports p
             join bitstreams b on b.id = p.bitstream
             left join net_names nn
                    on nn.bitstream = p.bitstream and nn.net = p.net"""
    args: tuple = ()
    if label:
        sql += " where b.label = ?" if db.BACKEND == "sqlite" else " where b.label = %s"
        args = (label,)
    sql += " order by b.label, p.direction, p.port_name"
    cur.execute(sql, args)
    return cur.fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bitstream", help="label to report on (default: all)")
    args = ap.parse_args()

    log = setup_logging()
    rows = fetch(args.bitstream)
    if not rows:
        log.error("no efb_ports rows found%s",
                  f" for {args.bitstream}" if args.bitstream else "")
        return 1

    by_label: dict[str, list] = defaultdict(list)
    for label, port, direction, net, name in rows:
        by_label[label].append((port, direction, net, name))

    rc = 0
    for label, ports in by_label.items():
        n_in = sum(1 for _, d, _, _ in ports if d == "in")
        n_out = sum(1 for _, d, _, _ in ports if d == "out")
        log.info("=== %s: %d EFB ports (%d in, %d out) ===",
                 label, len(ports), n_in, n_out)

        grouped: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for port, direction, net, name in ports:
            grouped[group_of(port)][direction].append((port, net, name))

        for gname, _ in GROUPS + [("other", None)]:
            g = grouped.get(gname)
            if not g:
                continue
            gi, go = g.get("in", []), g.get("out", [])
            log.info("  %s: %d in, %d out", gname, len(gi), len(go))
            for direction, items in (("in", gi), ("out", go)):
                for port, net, name in items:
                    log.info("      %-3s %-12s %-8s %s", direction, port, net, name)

        present = {p for p, _, _, _ in ports}
        for lo, hi in BUS_PAIRS:
            w_in = sum(1 for p in present if p.startswith(lo))
            w_out = sum(1 for p in present if p.startswith(hi))
            if w_in and w_out and w_in != w_out:
                log.warning("  BUS WIDTH MISMATCH %s[%d] vs %s[%d] "
                            "-- half a bus recovered", lo, w_in, hi, w_out)
                rc = 1
            elif w_in and w_out:
                log.info("  bus %s/%s paired at %d bits", lo, hi, w_in)

        if n_in == 0 and n_out:
            log.warning("  %s: outputs only, no inputs recovered (issue #100)",
                        label)
            rc = 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
