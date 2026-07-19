#!/usr/bin/env python3
"""Trace a GOWIN capture/acquisition engine's arming structure from the DB.

Runs under python3.15t against a loaded bitstream (PLURIBUS_SQLITE_PATH / the
usual backend selection).  Every section is a query over tables an earlier
pipeline stage already filled — nothing here re-derives reachability.

Written for the OpenScope / FNIRSI 2C53T (GW1N-2) R3 "what arms capture"
cross-check, but nothing in it is board-specific: give it a control net and,
optionally, a BSRAM port sidecar and it reports the same structure for any
GOWIN design.

    python3.15t scripts/gowin_capture_trace.py --bitstream LABEL \
        --bsram-ports tmp/bsram_ports.json --control-node R1C20_Q6

Sections
    1. BSRAM control map      — CLK/CE/WRE/OCE/RESET per block, constants
                                resolved through routing hops to VCC/VSS
    2. CE-gate decode         — the LUT (or FF) driving each CEA, its INIT
                                decoded to a boolean expression, and which of
                                its inputs are register (counter-state) outputs
    3. Control-net fan-out    — FF fan-out of a control/run net split by the pin
                                it lands on (D / CE / LSR) at several trace
                                depths, plus the async set/preset/reset breakdown
    4. Set/preset targets     — the flops the control net can asynchronously
                                force, and whether they feed the CE gates
    5. Cone comparison        — backward FF cones of the CE gates and any named
                                output nets, tested for set equality

Requires the BSRAM sidecar (scripts/gowin_bsram_ports.py) for sections 1-2;
without it those sections are skipped and the rest still runs.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from sqlalchemy import text  # noqa: E402

from db import engine, die  # noqa: E402

CONTROL_A = ("CLKA", "CEA", "WREA", "OCEA", "RESETA")
CONTROL_B = ("CLKB", "CEB", "WREB", "OCEB", "RESETB")
DEFAULT_DEPTHS = (1, 2, 4, 6, 8, 12, 20, None)


# ── LUT INIT decoding ────────────────────────────────────────────────────────

def lut_expr(init16):
    """Decode a pluribus 16-bit LUT INIT string into a sum-of-products string.

    Convention (see lifters/gowin_lift.py): v = int(init16, 2); pins are
    A=I0 B=I1 C=I2 D=I3; truth-table address = A + 2B + 4C + 8D and
    INIT bit p = f(p).  Returns (expr, cared_inputs).
    """
    v = int(init16, 2)
    ons = [p for p in range(16) if (v >> p) & 1]
    if not ons:
        return "0", []
    if len(ons) == 16:
        return "1", []
    care = []
    for bit, name in enumerate("ABCD"):
        m = 1 << bit
        if any(((v >> p) & 1) != ((v >> (p ^ m)) & 1) for p in range(16)):
            care.append(name)
    terms = set()
    for p in ons:
        lits = [(nm if (p >> i) & 1 else "~" + nm)
                for i, nm in enumerate("ABCD") if nm in care]
        terms.add("&".join(lits) if lits else "1")
    return " | ".join(sorted(terms)), care


# ── DB helpers ───────────────────────────────────────────────────────────────

class Trace:
    def __init__(self, label):
        self.eng = engine()
        self.conn = self.eng.connect()
        row = self.conn.execute(
            text("select id from bitstreams where label=:l"), {"l": label}
        ).fetchone()
        if not row:
            die(f"Bitstream {label!r} not found — run the pipeline first")
        self.bs = row[0]
        self.label = label

    def q(self, sql, **kw):
        kw["bs"] = self.bs
        return self.conn.execute(text(sql), kw).fetchall()

    def q1(self, sql, **kw):
        r = self.q(sql, **kw)
        return r[0] if r else None

    def net_of(self, wire):
        """pluribus net for a raw wire node (NULL when tied to a constant)."""
        r = self.q1("""select coalesce(sink_net, source_net) from arcs
                       where bitstream=:bs and (sink_wire=:w or source_wire=:w)
                        and coalesce(sink_net, source_net) is not null limit 1""",
                    w=wire)
        return r[0] if r else None

    def src_wire(self, wire):
        r = self.q1("""select source_wire from arcs
                       where bitstream=:bs and sink_wire=:w limit 1""", w=wire)
        return r[0] if r else None

    def resolve_const(self, wire, depth=8):
        """Follow single-source routing hops to VCC/VSS if they end there."""
        path, cur = [], wire
        for _ in range(depth):
            s = self.src_wire(cur)
            if s is None:
                return None, path
            path.append(s)
            if s in ("VCC", "VSS"):
                return s, path
            cur = s
        return None, path

    def driver(self, net):
        """Human description of the cell driving `net` (LUT / FF / ALU)."""
        if net is None:
            return None
        r = self.q1("""select cell, init from luts
                       where bitstream=:bs and z=:n""", n=net)
        if r:
            return f"LUT {r[0]} INIT={int(r[1], 2):#06x}", ("lut", r[0], r[1])
        r = self.q1("""select cell, dtype from ffs
                       where bitstream=:bs and q=:n""", n=net)
        if r:
            return f"FF {r[0]} ({r[1]})", ("ff", r[0], r[1])
        r = self.q1("""select cell, mode from alu_cells
                       where bitstream=:bs and (sum_net=:n or cout_net=:n)""", n=net)
        if r:
            return f"ALU {r[0]} mode={r[1]}", ("alu", r[0], r[1])
        return None, None

    def ff_cone(self, net):
        """Set of FF cells in the backward cone of `net` (reach2 reverse closure)."""
        return {r[0] for r in self.q(
            """select distinct f.cell from reachability_rev rr
               join ffs f on f.bitstream=rr.bitstream and f.q=rr.src
               where rr.bitstream=:bs and rr.dst=:n""", n=net)}


# ── Sections ─────────────────────────────────────────────────────────────────

def section_bsram(t, blocks):
    print("\n== 1. BSRAM control map ==")
    ce_gates = {}
    for b in sorted(blocks, key=lambda x: (x["row"], x["col"])):
        print(f"\n  {b['tile']} (grid {b['row']},{b['col']})")
        for side, ports in (("A", CONTROL_A), ("B", CONTROL_B)):
            for port in ports:
                nodes = b["ports"].get(port)
                if not nodes:
                    continue
                node = nodes[0]
                net = t.net_of(node)
                if net is None:
                    const, path = t.resolve_const(node)
                    via = f" via {'->'.join(path)}" if len(path) > 1 else ""
                    print(f"    {port:7} {node:16} = {const or 'UNROUTED'}{via}")
                    continue
                desc, meta = t.driver(net)
                src = t.src_wire(node)
                print(f"    {port:7} {node:16} net={net:8} "
                      f"<- {desc or src or '?'}")
                if port == "CEA":
                    ce_gates[b["tile"]] = (net, meta)
    return ce_gates


def section_ce_gates(t, ce_gates):
    print("\n== 2. CE-gate decode (what gates the write window) ==")
    for tile, (net, meta) in sorted(ce_gates.items()):
        if not meta:
            print(f"  {tile}: CEA net={net} has no modelled driver")
            continue
        kind, cell, extra = meta
        if kind != "lut":
            print(f"  {tile}: CEA net={net} driven directly by {kind.upper()} {cell} ({extra})")
            continue
        expr, care = lut_expr(extra)
        print(f"  {tile}: CEA <- LUT {cell} INIT={int(extra, 2):#06x}  expr = {expr}")
        r = t.q1("""select a,b,c,d from luts where bitstream=:bs and cell=:c""", c=cell)
        for pin, net_in in zip("ABCD", r):
            if not net_in or pin not in care:
                continue
            desc, _ = t.driver(net_in)
            print(f"      {pin} = {net_in:8} <- {desc or '?'}")


def section_fanout(t, net, depths):
    print(f"\n== 3. control-net fan-out (net {net}) ==")
    print("   depth |     D     CE    LSR |  preset(DFFP)  set(DFFS)  reset(DFFR)")
    for d in depths:
        cond = "" if d is None else " and r.min_hops<=:d"
        rows = t.q(f"""select f.dtype,
                         case when f.d=r.dst then 'D'
                              when f.ce=r.dst then 'CE'
                              when f.lsr=r.dst then 'LSR' end pin
                       from reachability r join ffs f
                         on f.bitstream=r.bitstream
                        and (f.d=r.dst or f.ce=r.dst or f.lsr=r.dst)
                       where r.bitstream=:bs and r.src=:n{cond}""",
                   n=net, **({} if d is None else {"d": d}))
        sp, kinds = {}, {}
        for dtype, pin in rows:
            sp[pin] = sp.get(pin, 0) + 1
            if pin == "LSR":
                kinds[dtype] = kinds.get(dtype, 0) + 1
        label = "full" if d is None else str(d)
        print(f"   {label:>5} | {sp.get('D',0):5} {sp.get('CE',0):6} {sp.get('LSR',0):6} |"
              f"  {kinds.get('DFFP',0):11} {kinds.get('DFFS',0):10} {kinds.get('DFFR',0):12}")


def section_async(t, net, ce_gates):
    print(f"\n== 4. async set/preset targets of net {net} ==")
    gate_inputs = set()
    for tile, (cenet, meta) in ce_gates.items():
        if not meta or meta[0] != "lut":
            continue
        r = t.q1("select a,b,c,d from luts where bitstream=:bs and cell=:c", c=meta[1])
        for n in r:
            if not n:
                continue
            d = t.q1("select cell from ffs where bitstream=:bs and q=:n", n=n)
            if d:
                gate_inputs.add(d[0])
    for dtype in ("DFFP", "DFFS"):
        rows = t.q("""select distinct f.cell, f.lsr, r.min_hops
                      from reachability r join ffs f
                        on f.bitstream=r.bitstream and f.lsr=r.dst
                      where r.bitstream=:bs and r.src=:n and f.dtype=:t
                      order by r.min_hops, f.cell""", n=net, t=dtype)
        total = t.q1("select count(*) from ffs where bitstream=:bs and dtype=:t", t=dtype)[0]
        if not rows:
            continue
        print(f"  {dtype}: {len(rows)} of {total} reached on LSR")
        for cell, lsr, hops in rows:
            mark = "  <-- drives a CE gate" if cell in gate_inputs else ""
            print(f"      {hops:3}h {cell:22} LSR={lsr}{mark}")
    if gate_inputs:
        print(f"  CE-gate register inputs: {sorted(gate_inputs)}")


def section_cones(t, ce_gates, extra_nets):
    print("\n== 5. backward FF cone comparison ==")
    cones = {}
    for tile, (net, _m) in sorted(ce_gates.items()):
        cones[f"CE@{tile}"] = t.ff_cone(net)
    for name, net in extra_nets:
        cones[name] = t.ff_cone(net)
    for k, v in cones.items():
        print(f"  {k:20} {len(v):5} FFs")
    keys = list(cones)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = cones[keys[i]], cones[keys[j]]
            if not a or not b:
                continue
            rel = "IDENTICAL" if a == b else f"|shared|={len(a & b)}"
            print(f"  {keys[i]:20} vs {keys[j]:20} -> {rel}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bitstream", required=True, help="bitstream label")
    ap.add_argument("--bsram-ports", help="JSON from scripts/gowin_bsram_ports.py")
    ap.add_argument("--control-net", help="run/arm control net (e.g. n591)")
    ap.add_argument("--control-node", help="raw wire node for the control net "
                                           "(e.g. R1C20_Q6); resolved to a net")
    ap.add_argument("--extra-net", action="append", default=[],
                    metavar="NAME=NET", help="extra net to cone-compare "
                                             "(repeatable, e.g. dataready=n2993)")
    args = ap.parse_args()

    t = Trace(args.bitstream)
    print(f"pluribus gowin capture trace — bitstream {t.label} (id={t.bs})")

    ce_gates = {}
    if args.bsram_ports:
        with open(args.bsram_ports) as fh:
            blocks = json.load(fh)
        ce_gates = section_bsram(t, blocks)
        section_ce_gates(t, ce_gates)
    else:
        print("\n(no --bsram-ports sidecar: BSRAM sections skipped)")

    net = args.control_net
    if not net and args.control_node:
        net = t.net_of(args.control_node)
        if not net:
            die(f"control node {args.control_node} resolves to no net")
        print(f"\ncontrol node {args.control_node} -> net {net}")
    if net:
        section_fanout(t, net, DEFAULT_DEPTHS)
        section_async(t, net, ce_gates)

    extras = []
    for spec in args.extra_net:
        name, _, n = spec.partition("=")
        if n:
            extras.append((name, n))
    if ce_gates or extras:
        section_cones(t, ce_gates, extras)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
