#!/usr/bin/env python3
"""Pluribus — Netlist query API (issue #12).

A thin, read-only query surface over the pre-computed analysis tables.  Every
method is a focused SELECT against a table that an earlier pipeline stage has
already filled — nothing here recomputes reachability, patterns, or naming.

    nl = Netlist(bitstream="V07")
    nl.reachable("n307", stop_at="FF", depth=8)   # from reachability
    nl.efb_port("JUPDATE")                          # -> net
    nl.name("n307")                                 # -> friendly name
    nl.net_for_pad("ADC_D0A")                       # -> net
    nl.shift_registers()                            # from patterns table
    nl.spi_reg(0x17)                                # -> {name, bit_fields}
    nl.taint_fwd("n307", stop_at="FF")             # from reachability

Backend-agnostic: uses the shared SQLAlchemy engine (`db.engine()`), so it
works unchanged on the SQLite default and on PostgreSQL.

Source tables (which stage fills them):
    net_names        load.py / auto_name.py     -> name()
    pad_map          load.py                     -> net_for_pad()
    efb_ports        load.py                     -> efb_port()
    reachability     reach.py                    -> reachable(), taint_fwd()
    ffs              load.py                     -> reachable(stop_at="FF")
    patterns +       reach3.py                   -> shift_registers()
      shift_reg_bits
    spi_registers    annotate.py (issue #12,     -> spi_reg()
                       not yet written)

Where a backing table is present but empty (e.g. spi_registers before
annotate.py exists) the corresponding method degrades gracefully, returning
None or [] rather than raising.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import select, and_, or_

import schema
from db import engine, die


# ── FF input pins that a signal can "reach" (data/control path, not the clock).
#    Used by reachable(stop_at="FF") / taint_fwd(stop_at="FF").  The clock pin is
#    deliberately excluded: a clock arriving at a FF is not the FF being tainted
#    by the source's data.  Matches reach.py's pad_ff_influence (d / ce) plus the
#    synchronous set/reset input.
_FF_INPUT_PINS = (("d", "D"), ("ce", "CE"), ("lsr", "LSR"))


def _as_json(val: Any, default: Any) -> Any:
    """JSON columns come back as native lists/dicts on some drivers and as raw
    strings on others — normalise to the Python value, falling back to
    `default` on NULL or an unparseable payload."""
    if val is None:
        return default
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except (TypeError, ValueError):
        return default


class Netlist:
    """Read-only query interface to one loaded bitstream's recovered netlist.

    Resolve the label to its bitstream id once at construction; every method is
    then a single indexed query scoped to that id.
    """

    def __init__(self, bitstream: str, eng=None):
        self.label = bitstream
        self._eng = eng or engine()
        with self._eng.connect() as conn:
            row = conn.execute(
                select(schema.bitstreams.c.id)
                .where(schema.bitstreams.c.label == bitstream)
            ).fetchone()
        if not row:
            die(f"Bitstream {bitstream!r} not found — run the pipeline first")
        self.bs_id = row[0]

    def __repr__(self) -> str:
        return f"Netlist(bitstream={self.label!r}, bs_id={self.bs_id})"

    # ── Naming ──────────────────────────────────────────────────────────────

    def name(self, net: str) -> Optional[str]:
        """Friendly name annotated for `net`, or None if the net is unnamed.

        Reads the `net_names` knowledge table (populated by load.py's pin/net
        annotations and auto_name.py's derived names).
        """
        nn = schema.net_names
        with self._eng.connect() as conn:
            row = conn.execute(
                select(nn.c.name)
                .where(and_(nn.c.bitstream == self.bs_id, nn.c.net == net))
            ).fetchone()
        return row[0] if row else None

    def net_info(self, net: str) -> Optional[Dict[str, Any]]:
        """Full annotation row for `net` (name, description, confidence,
        source, freq_mhz), or None if unnamed."""
        nn = schema.net_names
        with self._eng.connect() as conn:
            row = conn.execute(
                select(nn.c.name, nn.c.description, nn.c.confidence,
                       nn.c.source, nn.c.freq_mhz)
                .where(and_(nn.c.bitstream == self.bs_id, nn.c.net == net))
            ).fetchone()
        if not row:
            return None
        return {"net": net, "name": row[0], "description": row[1],
                "confidence": row[2], "source": row[3], "freq_mhz": row[4]}

    # ── Pads ────────────────────────────────────────────────────────────────

    def net_for_pad(self, pad_label: str) -> Optional[str]:
        """Fabric net connected to the pad labelled `pad_label`, or None.

        Returns the input net (`net_in`) when the pad drives the fabric, else
        the output net (`net_out`).  Matches report.py's input/output split.
        """
        pm = schema.pad_map
        with self._eng.connect() as conn:
            row = conn.execute(
                select(pm.c.net_in, pm.c.net_out)
                .where(and_(pm.c.bitstream == self.bs_id,
                            pm.c.label == pad_label))
                .order_by(pm.c.pin)
            ).fetchone()
        if not row:
            return None
        net_in, net_out = row
        return net_in if net_in is not None else net_out

    def pad_for_net(self, net: str) -> List[Dict[str, Any]]:
        """All pads whose `net_in` or `net_out` is `net` (reverse of
        net_for_pad).  Returns [] when the net touches no pad."""
        pm = schema.pad_map
        with self._eng.connect() as conn:
            rows = conn.execute(
                select(pm.c.pin, pm.c.label, pm.c.direction,
                       pm.c.net_in, pm.c.net_out)
                .where(and_(pm.c.bitstream == self.bs_id,
                            or_(pm.c.net_in == net, pm.c.net_out == net)))
                .order_by(pm.c.pin)
            ).fetchall()
        return [{"pin": p, "label": lbl, "direction": d,
                 "net_in": ni, "net_out": no}
                for p, lbl, d, ni, no in rows]

    # ── Hard IP ports ───────────────────────────────────────────────────────

    def efb_port(self, port_name: str) -> Optional[str]:
        """Fabric net wired to EFB (embedded function block) port `port_name`
        (e.g. "JUPDATE"), or None.  Case-insensitive fallback."""
        ep = schema.efb_ports
        with self._eng.connect() as conn:
            row = conn.execute(
                select(ep.c.net)
                .where(and_(ep.c.bitstream == self.bs_id,
                            ep.c.port_name == port_name))
            ).fetchone()
            if row:
                return row[0]
            # Case-insensitive fallback (port names are conventionally upper).
            row = conn.execute(
                select(ep.c.net)
                .where(and_(ep.c.bitstream == self.bs_id,
                            schema.efb_ports.c.port_name.ilike(port_name)))
            ).fetchone()
        return row[0] if row else None

    def efb_ports(self) -> List[Dict[str, str]]:
        """All EFB ports and their nets for this bitstream."""
        ep = schema.efb_ports
        with self._eng.connect() as conn:
            rows = conn.execute(
                select(ep.c.port_name, ep.c.net)
                .where(ep.c.bitstream == self.bs_id)
                .order_by(ep.c.port_name)
            ).fetchall()
        return [{"port_name": pn, "net": n} for pn, n in rows]

    # ── Reachability ────────────────────────────────────────────────────────

    def reachable(self, net: str, stop_at: Optional[str] = None,
                  depth: Optional[int] = None) -> List[Dict[str, Any]]:
        """Forward reachability from `net` — read straight from the pre-computed
        `reachability` transitive closure (reach.py).

        stop_at=None  -> reached nets:  [{"net", "hops"}, ...]
        stop_at="FF"  -> reached FFs:   [{"ff_cell", "pin", "via_net", "hops"}]
                         (a FF is "reached" when the net arrives at its D / CE /
                         LSR input; the clock pin is excluded — see _FF_INPUT_PINS)
        depth         -> optional max hop count (min_hops <= depth)

        Rows are ordered nearest-first (ascending hops).
        """
        r = schema.reachability
        conds = [r.c.bitstream == self.bs_id, r.c.src == net]
        if depth is not None:
            conds.append(r.c.min_hops <= depth)

        if stop_at is None:
            with self._eng.connect() as conn:
                rows = conn.execute(
                    select(r.c.dst, r.c.min_hops)
                    .where(and_(*conds))
                    .order_by(r.c.min_hops, r.c.dst)
                ).fetchall()
            return [{"net": dst, "hops": hops} for dst, hops in rows]

        if stop_at.upper() != "FF":
            raise ValueError(
                f"stop_at={stop_at!r} unsupported; use None or 'FF'")

        f = schema.ffs
        pin_match = or_(*[getattr(f.c, col) == r.c.dst
                          for col, _ in _FF_INPUT_PINS])
        with self._eng.connect() as conn:
            rows = conn.execute(
                select(f.c.cell, f.c.d, f.c.ce, f.c.lsr, r.c.dst, r.c.min_hops)
                .select_from(r.join(f, and_(
                    f.c.bitstream == r.c.bitstream, pin_match)))
                .where(and_(*conds))
                .order_by(r.c.min_hops, f.c.cell)
            ).fetchall()

        # One entry per FF at its nearest reaching hop.
        best: Dict[str, Dict[str, Any]] = {}
        for cell, d, ce, lsr, dst, hops in rows:
            pin = next((label for col, label in _FF_INPUT_PINS
                        if {"d": d, "ce": ce, "lsr": lsr}[col] == dst), "?")
            cur = best.get(cell)
            if cur is None or hops < cur["hops"]:
                best[cell] = {"ff_cell": cell, "pin": pin,
                              "via_net": dst, "hops": hops}
        return sorted(best.values(), key=lambda e: (e["hops"], e["ff_cell"]))

    def taint_fwd(self, net: str,
                  stop_at: Optional[str] = None) -> List[str]:
        """Forward taint cone of `net` — every net (or FF, with stop_at="FF")
        the value on `net` can influence.  The unbounded-depth name projection
        of reachable(); returns a sorted list of names."""
        reached = self.reachable(net, stop_at=stop_at, depth=None)
        if stop_at is None:
            return sorted(e["net"] for e in reached)
        return sorted(e["ff_cell"] for e in reached)

    # ── Structural patterns ─────────────────────────────────────────────────

    def shift_registers(self) -> List[Dict[str, Any]]:
        """Detected shift-register chains (reach3.py, pattern_type='shift_reg').

        Each entry carries the chain summary from `patterns.detail` plus its
        ordered bits from `shift_reg_bits`:
            {"label", "length", "clk_net", "ce_net", "head_ff", "tail_ff",
             "bits": [{"bit_index", "ff_cell", "q_net"}, ...]}
        """
        pat = schema.patterns
        srb = schema.shift_reg_bits
        out: List[Dict[str, Any]] = []
        with self._eng.connect() as conn:
            pats = conn.execute(
                select(pat.c.id, pat.c.label, pat.c.detail)
                .where(and_(pat.c.bitstream == self.bs_id,
                            pat.c.pattern_type == "shift_reg"))
                .order_by(pat.c.label)
            ).fetchall()
            for pat_id, label, detail in pats:
                d = _as_json(detail, {})
                bits = conn.execute(
                    select(srb.c.bit_index, srb.c.ff_cell, srb.c.q_net)
                    .where(srb.c.pattern_id == pat_id)
                    .order_by(srb.c.bit_index)
                ).fetchall()
                out.append({
                    "label":   label,
                    "length":  d.get("length"),
                    "clk_net": d.get("clk_net"),
                    "ce_net":  d.get("ce_net"),
                    "head_ff": d.get("head_ff"),
                    "tail_ff": d.get("tail_ff"),
                    "bits": [{"bit_index": bi, "ff_cell": fc, "q_net": qn}
                             for bi, fc, qn in bits],
                })
        return out

    def patterns(self, pattern_type: Optional[str] = None
                 ) -> List[Dict[str, Any]]:
        """Raw rows from the `patterns` table (all types, or one type).

        Covers every detector — patterns.py's stuck_pad / orphan_pad /
        shared_net_pad / pclk_lane / const_ff as well as reach3.py's shift_reg.
        """
        pat = schema.patterns
        conds = [pat.c.bitstream == self.bs_id]
        if pattern_type is not None:
            conds.append(pat.c.pattern_type == pattern_type)
        with self._eng.connect() as conn:
            rows = conn.execute(
                select(pat.c.pattern_type, pat.c.label, pat.c.detail)
                .where(and_(*conds))
                .order_by(pat.c.pattern_type, pat.c.label)
            ).fetchall()
        return [{"pattern_type": pt, "label": lbl, "detail": _as_json(det, {})}
                for pt, lbl, det in rows]

    # ── SPI registers ───────────────────────────────────────────────────────

    def spi_reg(self, address: int,
                bank: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """SPI register at `address` (int, e.g. 0x17), or None if unknown.

        Reads the `spi_registers` knowledge table.  That table is filled by
        annotate.py (issue #12, not yet written); until then this returns None
        for every address.  Returns:
            {"bank", "address", "name", "description", "bit_fields"}
        `bit_fields` is the decoded JSON list.  When `bank` is omitted the
        lowest-sorted bank at that address is returned.
        """
        sr = schema.spi_registers
        conds = [sr.c.bitstream == self.bs_id, sr.c.address == address]
        if bank is not None:
            conds.append(sr.c.bank == bank)
        with self._eng.connect() as conn:
            row = conn.execute(
                select(sr.c.bank, sr.c.address, sr.c.name,
                       sr.c.description, sr.c.bit_fields)
                .where(and_(*conds))
                .order_by(sr.c.bank)
            ).fetchone()
        if not row:
            return None
        return {"bank": row[0], "address": row[1], "name": row[2],
                "description": row[3], "bit_fields": _as_json(row[4], [])}

    def spi_regs(self) -> List[Dict[str, Any]]:
        """Every known SPI register for this bitstream, ordered by bank+address."""
        sr = schema.spi_registers
        with self._eng.connect() as conn:
            rows = conn.execute(
                select(sr.c.bank, sr.c.address, sr.c.name,
                       sr.c.description, sr.c.bit_fields)
                .where(sr.c.bitstream == self.bs_id)
                .order_by(sr.c.bank, sr.c.address)
            ).fetchall()
        return [{"bank": b, "address": a, "name": n,
                 "description": desc, "bit_fields": _as_json(bf, [])}
                for b, a, n, desc, bf in rows]


# ── Tiny CLI demo (house style: `python3 api.py --bitstream V07 …`) ──────────

def main():
    ap = argparse.ArgumentParser(
        description="Query the recovered netlist (issue #12 Netlist API).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bitstream", required=True)
    ap.add_argument("--name", metavar="NET", help="friendly name for a net")
    ap.add_argument("--pad", metavar="LABEL", help="fabric net for a pad")
    ap.add_argument("--efb", metavar="PORT", help="net for an EFB port")
    ap.add_argument("--reachable", metavar="NET",
                    help="forward-reachable FFs from a net")
    ap.add_argument("--depth", type=int, help="max hops for --reachable")
    ap.add_argument("--spi", metavar="ADDR",
                    help="SPI register at ADDR (hex ok, e.g. 0x17)")
    ap.add_argument("--shift-registers", action="store_true",
                    help="list detected shift-register chains")
    args = ap.parse_args()

    nl = Netlist(args.bitstream)
    if args.name:
        print(nl.name(args.name))
    if args.pad:
        print(nl.net_for_pad(args.pad))
    if args.efb:
        print(nl.efb_port(args.efb))
    if args.reachable:
        for e in nl.reachable(args.reachable, stop_at="FF", depth=args.depth):
            print(f"  {e['hops']:>3} hops  {e['ff_cell']:<24} "
                  f"({e['pin']} <- {e['via_net']})")
    if args.spi:
        addr = int(args.spi, 0)
        print(nl.spi_reg(addr))
    if args.shift_registers:
        for sr in nl.shift_registers():
            print(f"  {sr['label']}  len={sr['length']}  "
                  f"clk={sr['clk_net']}  head={sr['head_ff']}")


if __name__ == "__main__":
    main()
