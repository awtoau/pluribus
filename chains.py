#!/usr/bin/env python3
"""Pluribus — Stage: signal chain report.

Generates V07-chains.txt from the reachability DB — no hand-coded BFS.
Every section queries reachability / reachability_rev / net_fanout so
results are generic across all pads and all hard IP (EBR, EFB, PLL).

Replaces fpga/scripts/fpga_chain.py (issue #127).

Sections:
  1.  All configured pads — immediate fabric driver (FF / LUT / IOLOGIC / none)
  2.  Hard IP reachability summary (EBR / EFB ports)
  3.  Input pad → EBR write reachability (forward, filter by pad_map src)
  4.  EBR read → output pad reachability (forward, filter by pad_map dst)
  5.  Output pad ← EBR write reverse reachability
  6.  SPI CS (CSSPIN) forward fanout
  7.  Clock domain summary per hard IP tile
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

_HERE    = Path(__file__).parent
_SCRIPTS = _HERE.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_HERE))

from sqlalchemy import select, func, and_
import schema
from db import engine, die


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bitstream", required=True)
    ap.add_argument("--out",       required=True)
    args = ap.parse_args()

    with engine().connect() as conn:
        # ── Resolve bitstream id ──────────────────────────────────────────────
        row = conn.execute(
            select(schema.bitstreams.c.id).where(
                schema.bitstreams.c.label == args.bitstream
            )
        ).fetchone()
        if not row:
            die(f"Bitstream {args.bitstream!r} not found")
        bs_id = row[0]

        lines = []
        L = lines.append

        L(f"== Signal chain report  ({args.bitstream}) ==")
        L(f"source: Pluribus DB — all sections from reachability / net_fanout")
        L("")

        # ── 1. All pads — immediate driver ───────────────────────────────────
        L("-- 1. Pad immediate drivers (all configured pads) --")
        L(f"  {'pin':<4} {'label':<16} {'dir':<6} {'net':<8} {'driver'}")
        L(f"  {'-'*4} {'-'*16} {'-'*6} {'-'*8} {'-'*40}")

        pm = schema.pad_map
        pads = conn.execute(
            select(
                pm.c.pin, pm.c.label, pm.c.direction,
                pm.c.net_in, pm.c.net_out,
                pm.c.chip_ref, pm.c.chip_signal,
            ).where(pm.c.bitstream == bs_id).order_by(pm.c.pin)
        ).fetchall()

        nf = schema.net_fanout
        ff = schema.ffs

        for pin, label, direction, net_in, net_out, chip_ref, chip_signal in pads:
            net = net_out or net_in
            if not net:
                L(f"  {pin:<4} {(label or '?'):<16} {direction:<6} {'(none)':<8} —")
                continue

            # Look up immediate driver from net_fanout (what has out_net = this net).
            # Prefer PAD/FF drivers over synthetic EBR JQ_ff entries; exclude
            # JQ_src (write-transparency) since those are not direct drivers.
            drivers = conn.execute(
                select(
                    nf.c.cell_type, nf.c.cell, nf.c.pin, nf.c.net
                ).where(
                    and_(
                        nf.c.bitstream == bs_id,
                        nf.c.out_net == net,
                        nf.c.pin.notin_(["JQ_src", "JQ_ff"]),
                    )
                ).distinct().limit(3)
            ).fetchall()

            if not drivers:
                # Fall back to JQ_ff drivers (EBR read output path)
                drivers = conn.execute(
                    select(
                        nf.c.cell_type, nf.c.cell, nf.c.pin, nf.c.net
                    ).where(
                        and_(
                            nf.c.bitstream == bs_id,
                            nf.c.out_net == net,
                            nf.c.pin == "JQ_ff",
                        )
                    ).distinct().limit(3)
                ).fetchall()

            if not drivers:
                # Input pad — check what this net fans out into
                fwd = conn.execute(
                    select(
                        nf.c.cell_type, nf.c.cell, nf.c.pin, nf.c.out_net
                    ).where(
                        and_(
                            nf.c.bitstream == bs_id,
                            nf.c.net == net,
                        )
                    ).limit(1)
                ).fetchone()
                driver_str = f"→ {fwd[0]}:{fwd[1]}" if fwd else "(no fanout in netlist)"
            else:
                seen_cells: set = set()
                parts = []
                for ctype, cell, ipin, drv_net in drivers:
                    key = (ctype, cell)
                    if key in seen_cells:
                        continue
                    seen_cells.add(key)
                    if ctype == "PAD":
                        parts.append("IOLOGIC")
                    elif ctype == "FF":
                        # Get FF D to show if stuck
                        ff_row = conn.execute(
                            select(ff.c.d, ff.c.clk).where(
                                and_(ff.c.bitstream == bs_id, ff.c.cell == cell)
                            )
                        ).fetchone()
                        d_str   = f" D={ff_row[0]}" if ff_row else ""
                        clk_str = f" CLK={ff_row[1]}" if ff_row else ""
                        parts.append(f"FF:{cell}{d_str}{clk_str}")
                    elif ctype == "LUT":
                        parts.append(f"LUT:{cell}")
                    else:
                        parts.append(f"{ctype}:{cell}")
                driver_str = "  |  ".join(parts)

            chip_str = f"{chip_ref}/{chip_signal}" if chip_ref else ""
            L(f"  {pin:<4} {(label or '?'):<16} {direction:<6} {net:<8} "
              f"{driver_str:<50} {chip_str}")
        L("")

        # ── 2. Hard IP reachability summary ──────────────────────────────────
        L("-- 2. Hard IP ports (EBR + EFB) --")

        ep = schema.ebr_ports
        ebr_summary = conn.execute(
            select(
                ep.c.block, ep.c.role,
                func.count().label("n"),
                func.count(ep.c.net).label("with_net"),
            ).where(ep.c.bitstream == bs_id)
            .group_by(ep.c.block, ep.c.role)
            .order_by(ep.c.block, ep.c.role)
        ).fetchall()

        eb = schema.ebr_buses
        bus_rows = conn.execute(
            select(
                eb.c.block, eb.c.bus_role,
                func.count().label("n"),
            ).where(eb.c.bitstream == bs_id)
            .group_by(eb.c.block, eb.c.bus_role)
            .order_by(eb.c.block, eb.c.bus_role)
        ).fetchall()
        bus_by_block: dict = defaultdict(dict)
        for block, bus_role, n in bus_rows:
            bus_by_block[block][bus_role] = n

        cur_block = None
        for block, role, n, with_net in ebr_summary:
            if block != cur_block:
                buses = bus_by_block.get(block, {})
                bus_str = "  ".join(f"{k}={v}" for k, v in sorted(buses.items()))
                L(f"  {block}  [{bus_str}]")
                cur_block = block
            L(f"    {role:<6} ports={n}  with_net={with_net}")
        L("")

        efbp = schema.efb_ports
        efb = conn.execute(
            select(efbp.c.port_name, efbp.c.net)
            .where(efbp.c.bitstream == bs_id)
            .order_by(efbp.c.port_name)
        ).fetchall()
        L(f"  EFB: {len(efb)} ports")
        for port, net in efb[:8]:
            L(f"    {port:<20} net={net}")
        if len(efb) > 8:
            L(f"    ... and {len(efb)-8} more")
        L("")

        # ── 3. Input pad → EBR write reachability ────────────────────────────
        L("-- 3. Input pads → EBR write ports (forward reachability) --")
        L("  Shows which input pads can reach each EBR write net within the BFS depth.")

        ebr_write_nets = {
            row[0] for row in conn.execute(
                select(ep.c.net).where(
                    and_(
                        ep.c.bitstream == bs_id,
                        ep.c.role == "write",
                        ep.c.net.isnot(None),
                    )
                )
            ).fetchall()
        }

        input_pads = conn.execute(
            select(pm.c.pin, pm.c.label, pm.c.net_in)
            .where(
                and_(
                    pm.c.bitstream == bs_id,
                    pm.c.direction == "in",
                    pm.c.net_in.isnot(None),
                )
            ).order_by(pm.c.pin)
        ).fetchall()

        # For each input pad, find which EBR write nets it reaches
        pad_to_ebr: dict = defaultdict(list)
        r = schema.reachability
        if ebr_write_nets and input_pads:
            in_nets = [p[2] for p in input_pads]
            ebr_write_list = list(ebr_write_nets)
            for src, dst, hops in conn.execute(
                select(r.c.src, r.c.dst, r.c.min_hops)
                .where(
                    and_(
                        r.c.bitstream == bs_id,
                        r.c.dst.in_(ebr_write_list),
                        r.c.src.in_(in_nets),
                    )
                ).order_by(r.c.src, r.c.min_hops)
            ).fetchall():
                pad_to_ebr[src].append((dst, hops))

        # Group by EBR block
        ebr_net_to_block: dict = {}
        for net, block in conn.execute(
            select(ep.c.net, ep.c.block).where(
                and_(
                    ep.c.bitstream == bs_id,
                    ep.c.role == "write",
                    ep.c.net.isnot(None),
                )
            )
        ).fetchall():
            ebr_net_to_block[net] = block

        # Build: block → {pad_label: min_hops}
        block_to_pads: dict = defaultdict(dict)
        net_to_pad = {p[2]: (p[0], p[1]) for p in input_pads}
        for pad_net, ebr_hits in pad_to_ebr.items():
            pin, label = net_to_pad.get(pad_net, ("?", pad_net))
            for ebr_net, hops in ebr_hits:
                block = ebr_net_to_block.get(ebr_net, "?")
                existing = block_to_pads[block].get(label, 999)
                if hops < existing:
                    block_to_pads[block][label] = hops

        if block_to_pads:
            for block in sorted(block_to_pads):
                pads_str = "  ".join(
                    f"{lbl}({h})" for lbl, h in
                    sorted(block_to_pads[block].items(), key=lambda x: x[1])
                )
                L(f"  {block}  ←  {pads_str}")
        else:
            L("  (no input pad → EBR write paths found in reachability table)")
        L("")

        # ── 4. EBR read → output pad reachability ────────────────────────────
        L("-- 4. EBR read ports → output pads (forward reachability) --")

        # Source nets = JQ output nets (actual EBR DOB read-data).  These are the
        # out_net values from net_fanout JQ_src rows (write net → JQ net).
        # Also include ebr_ports role='read' nets for EBRs that lack JQ stitching.
        jq_rows = conn.execute(
            select(nf.c.out_net.label("net"), nf.c.cell.label("block"))
            .where(
                and_(
                    nf.c.bitstream == bs_id,
                    nf.c.pin == "JQ_src",
                    nf.c.out_net.isnot(None),
                )
            ).distinct()
        ).fetchall()
        jq_nets = [row[0] for row in jq_rows]
        jq_net_to_block = {row[0]: row[1] for row in jq_rows}

        ebr_read_rows = conn.execute(
            select(ep.c.net, ep.c.block).where(
                and_(
                    ep.c.bitstream == bs_id,
                    ep.c.role == "read",
                    ep.c.net.isnot(None),
                )
            )
        ).fetchall()
        ebr_read_block: dict = {row[0]: row[1] for row in ebr_read_rows}
        # Prefer JQ nets; fall back to ebr_ports 'read' nets for EBRs without JQ
        jq_blocks = {row[1] for row in jq_rows}
        extra_read_nets = [row[0] for row in ebr_read_rows if row[1] not in jq_blocks]
        for row in ebr_read_rows:
            if row[1] not in jq_blocks:
                ebr_read_block[row[0]] = row[1]

        ebr_read_nets = jq_nets + extra_read_nets
        ebr_read_block_merged = {**ebr_read_block, **jq_net_to_block}

        output_pads = conn.execute(
            select(pm.c.pin, pm.c.label, pm.c.net_out)
            .where(
                and_(
                    pm.c.bitstream == bs_id,
                    pm.c.direction.in_(["out", "bidir"]),
                    pm.c.net_out.isnot(None),
                )
            ).order_by(pm.c.pin)
        ).fetchall()
        out_nets = [p[2] for p in output_pads]
        out_net_to_pad = {p[2]: (p[0], p[1]) for p in output_pads}

        ebr_to_pads: dict = defaultdict(list)
        if ebr_read_nets and out_nets:
            for src, dst, hops in conn.execute(
                select(r.c.src, r.c.dst, r.c.min_hops)
                .where(
                    and_(
                        r.c.bitstream == bs_id,
                        r.c.src.in_(ebr_read_nets),
                        r.c.dst.in_(out_nets),
                    )
                ).order_by(r.c.src, r.c.min_hops)
            ).fetchall():
                block = ebr_read_block_merged.get(src, "?")
                pin, label = out_net_to_pad.get(dst, ("?", dst))
                ebr_to_pads[block].append((label, pin, hops))

        if ebr_to_pads:
            for block in sorted(ebr_to_pads):
                # Deduplicate: keep best (min) hops per pad label
                best: dict = {}
                for lbl, pin, h in ebr_to_pads[block]:
                    if lbl not in best or h < best[lbl]:
                        best[lbl] = h
                pads_str = "  ".join(
                    f"{lbl}({h})" for lbl, h in
                    sorted(best.items(), key=lambda x: x[1])
                )
                L(f"  {block}  →  {pads_str}")
        else:
            L("  (no EBR read → output pad paths found in reachability table)")
        L("")

        # ── 5. Output pads ← upstream input pads (reverse) ───────────────────
        L("-- 5. Output pads ← upstream input pads (reverse reachability) --")
        L("  For each output pad: which input pad nets can reach it?")

        rr = schema.reachability_rev
        nn = schema.net_names

        if out_nets:
            rev_rows = conn.execute(
                select(
                    rr.c.dst, rr.c.src, rr.c.min_hops,
                    nn.c.name.label("src_name"),
                )
                .join(
                    pm,
                    and_(pm.c.bitstream == rr.c.bitstream, pm.c.net_in == rr.c.src),
                )
                .outerjoin(
                    nn,
                    and_(nn.c.bitstream == rr.c.bitstream, nn.c.net == rr.c.src),
                )
                .where(
                    and_(
                        rr.c.bitstream == bs_id,
                        rr.c.dst.in_(out_nets),
                    )
                ).order_by(rr.c.dst, rr.c.min_hops)
            ).fetchall()
            rev_by_dst: dict = defaultdict(list)
            for dst, src, hops, src_name in rev_rows:
                rev_by_dst[dst].append((src, hops, src_name))

            for pin, label, net_out in output_pads:
                srcs = rev_by_dst.get(net_out, [])
                if not srcs:
                    L(f"  pin {pin:<3} {(label or '?'):<16} net={net_out}  ← (no upstream source found)")
                else:
                    src_str = "  ".join(
                        f"{sn or src}({h})" for src, h, sn in srcs[:6]
                    )
                    if len(srcs) > 6:
                        src_str += f"  +{len(srcs)-6} more"
                    L(f"  pin {pin:<3} {(label or '?'):<16} net={net_out}  ← {src_str}")
        L("")

        # ── 6. SPI CS (CSSPIN) forward fanout ────────────────────────────────
        L("-- 6. SPI CS (CSSPIN) forward reachability --")

        cs_rows = conn.execute(
            select(pm.c.pin, pm.c.net_in)
            .where(
                and_(
                    pm.c.bitstream == bs_id,
                    func.upper(pm.c.si_function).like(func.upper("%CSSPIN%")),
                )
            )
        ).fetchall()

        for cs_pin, cs_net in cs_rows:
            L(f"  pin {cs_pin}  net={cs_net}")
            if cs_net:
                # total nets reachable
                n_total = conn.execute(
                    select(func.count()).where(
                        and_(r.c.bitstream == bs_id, r.c.src == cs_net)
                    )
                ).scalar()

                # how many of those are FF data inputs
                n_ff = conn.execute(
                    select(func.count()).select_from(
                        r.join(
                            ff,
                            and_(
                                ff.c.bitstream == r.c.bitstream,
                                (ff.c.d == r.c.dst) | (ff.c.ce == r.c.dst),
                            ),
                        )
                    ).where(
                        and_(r.c.bitstream == bs_id, r.c.src == cs_net)
                    )
                ).scalar()

                # how many of those are output pad nets
                n_pad = conn.execute(
                    select(func.count()).select_from(
                        r.join(
                            pm,
                            and_(
                                pm.c.bitstream == r.c.bitstream,
                                pm.c.net_out == r.c.dst,
                            ),
                        )
                    ).where(
                        and_(r.c.bitstream == bs_id, r.c.src == cs_net)
                    )
                ).scalar()

                L(f"  reaches: {n_total} nets total  {n_ff} FF inputs  {n_pad} output pads")
                # Show immediate fanout
                for ctype, cell, out_net in conn.execute(
                    select(nf.c.cell_type, nf.c.cell, nf.c.out_net)
                    .where(
                        and_(nf.c.bitstream == bs_id, nf.c.net == cs_net)
                    ).limit(8)
                ).fetchall():
                    L(f"    → {ctype}:{cell}  out={out_net}")
        L("")

        # ── 7. EBR write clock domains ────────────────────────────────────────
        L("-- 7. Clock domains driving EBR write ports --")

        clk_rows = conn.execute(
            select(ep.c.block, ff.c.clk, func.count().label("n"))
            .join(nf, and_(nf.c.bitstream == ep.c.bitstream, nf.c.out_net == ep.c.net))
            .join(ff, and_(ff.c.bitstream == ep.c.bitstream, ff.c.cell == nf.c.cell))
            .where(
                and_(ep.c.bitstream == bs_id, ep.c.role == "write")
            )
            .group_by(ep.c.block, ff.c.clk)
            .order_by(ep.c.block, func.count().desc())
        ).fetchall()

        cur_block = None
        for block, clk, n in clk_rows:
            if block != cur_block:
                L(f"  {block}")
                cur_block = block
            # look up clock net name
            clk_name = conn.execute(
                select(nn.c.name)
                .where(
                    and_(nn.c.bitstream == bs_id, nn.c.net == clk)
                ).limit(1)
            ).fetchone()
            clk_str = f"{clk} ({clk_name[0]})" if clk_name else clk
            L(f"    CLK={clk_str}  {n} FFs")
        if not clk_rows:
            L("  (no EBR write clock domain data — EBR fanout not in net_fanout)")
        L("")

    report = "\n".join(lines) + "\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write(report)
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
