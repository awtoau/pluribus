#!/usr/bin/env python3
"""Pluribus — Stage: resources report.

Generates a full per-pin resource report from the DB + bitstream, matching the
format of fpga_resources_v7.txt (issue #126).  Replaces fpga/scripts/fpga_resources.py.

Output columns:
  pin dir site iostd drv pull function conn fan live signal chip c.pin c.sig conf

Sources:
  [bs]  — pad_map columns loaded from iomap during load.py
  [rev] — liveness / fanout computed here from the bitstream via machxo2_lift
  [usr] — label / chip_ref / chip_pin / chip_signal from pad_map (TSV annotations)
"""

import argparse
import os
import sys
from pathlib import Path

_HERE    = Path(__file__).parent
_SCRIPTS = _HERE.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_HERE))

from lifters import machxo2_lift as mx
from sqlalchemy import select
from db import engine, die
import schema

DEVICE = os.environ.get("TRELLIS_DEVICE", "LCMXO2-1200")

PERIPHERAL_GROUPS = [
    ("Crystal / PLL",
        lambda x: x["conn_class"] == "pll" or x["chip_ref"] == "XTAL1"),
    ("SPI config — sysCONFIG (hardwired, cannot be reassigned)",
        lambda x: x["conn_class"] == "spi_cfg" or
                  (x["chip_ref"] == "STM32" and "SPI" in (x["chip_signal"] or ""))),
    ("ADC channel A — U31 DA0-DA7 + ENCA",
        lambda x: x["chip_ref"] == "U31" and
                  ((x["chip_signal"] or "").endswith("A") or x["chip_signal"] == "ENCA")),
    ("ADC channel B — U31 DB0-DB7 + ENCB",
        lambda x: x["chip_ref"] == "U31" and
                  ((x["chip_signal"] or "").endswith("B") or x["chip_signal"] == "ENCB")),
    ("DAC — U12 D0-D11 + CLK",
        lambda x: x["chip_ref"] == "U12"),
    ("AFE control — U7 (74HC595, left-edge)",
        lambda x: x["chip_ref"] == "U7"),
    ("AFE control — U1 (74HC595, right-edge)",
        lambda x: x["chip_ref"] == "U1"),
    ("MCU — STM32",
        lambda x: x["chip_ref"] == "STM32"),
    ("Unknown / untraced",
        lambda x: True),
]

CONF_MAP = {"confirmed": 10, "inferred": 8, "estimate": 5, "guess": 3}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bitstream", required=True, help="bitstream label e.g. V07")
    ap.add_argument("--config",    required=True, help="path to .bin.config")
    ap.add_argument("--out",       required=True, help="output .txt path")
    args = ap.parse_args()

    with engine().connect() as conn:
        # ── look up bitstream id ───────────────────────────────────────────────
        row = conn.execute(
            select(schema.bitstreams.c.id).where(
                schema.bitstreams.c.label == args.bitstream
            )
        ).fetchone()
        if not row:
            die(f"Bitstream {args.bitstream!r} not found in DB")
        bs_id = row[0]

        # ── recover netlist for liveness analysis ──────────────────────────────
        print(f"Recovering netlist from {args.config}…")
        lift   = mx.MachXO2Lift(DEVICE)
        pc     = lift.parse_config(args.config)
        design = lift.recover_netlist(pc)
        res    = mx.resource_summary(design, DEVICE)
        hardip = mx.hardip_summary(pc)
        unknowns = mx.scan_unknown_bits(args.config)

        # ── load pad rows from DB ──────────────────────────────────────────────
        pm = schema.pad_map
        pad_rows = conn.execute(
            select(
                pm.c.pin, pm.c.label, pm.c.direction,
                pm.c.row, pm.c.col, pm.c.pio,
                pm.c.net_in, pm.c.net_out,
                pm.c.iostd, pm.c.drive, pm.c.pull,
                pm.c.si_function, pm.c.conn_class,
                pm.c.chip_ref, pm.c.chip_pin, pm.c.chip_signal,
            ).where(pm.c.bitstream == bs_id).order_by(pm.c.pin)
        ).fetchall()

        rows = []
        for (pin, label, direction, row_r, col, pio,
             net_in, net_out,
             iostd, drive, pull, si_fn, conn_cls,
             chip_ref, chip_pin, chip_signal) in pad_rows:
            site = f"R{row_r}C{col}:PIO{pio}" if row_r is not None else "?"
            rows.append({
                "pin": pin, "label": label, "dir": direction,
                "row": row_r, "col": col, "pio": pio, "site": site,
                "net_in": net_in, "net_out": net_out,
                "iostd": iostd or "", "drive": drive or "",
                "pull": pull or "", "si_function": si_fn or "",
                "conn_class": conn_cls or "unused",
                "chip_ref": chip_ref or "", "chip_pin": chip_pin or "",
                "chip_signal": chip_signal or "",
            })

        # ── liveness ───────────────────────────────────────────────────────────
        primary_in  = {x["net_in"]  for x in rows if x["net_in"]}
        primary_out = {x["net_out"] for x in rows if x["net_out"]}
        live = mx.analyze_liveness(design, primary_in, primary_out)
        for x in rows:
            if x["net_out"]:
                fan, ok = mx.net_liveness(live, x["net_out"])
                x["fan"], x["live"] = "src", ("yes" if ok else "dead")
            elif x["net_in"]:
                fan, ok = mx.net_liveness(live, x["net_in"])
                x["fan"], x["live"] = str(fan), ("yes" if ok else "dead")
            else:
                x["fan"], x["live"] = "-", "-"

        # ── patterns ───────────────────────────────────────────────────────────
        import json as _json
        pt = schema.patterns
        pattern_rows = conn.execute(
            select(pt.c.pattern_type, pt.c.label, pt.c.detail).where(
                pt.c.bitstream == bs_id
            ).order_by(pt.c.pattern_type, pt.c.label)
        ).fetchall()

        patterns_by_type = {}
        for ptype, lbl, detail in pattern_rows:
            if isinstance(detail, str):
                detail = _json.loads(detail)
            patterns_by_type.setdefault(ptype, []).append((lbl, detail))

    # ── build report text ──────────────────────────────────────────────────────
    def util(used, cap):
        return f"{used}/{cap} ({100*used/cap:.0f}%)" if cap else str(used)

    counts = {}
    for x in rows:
        counts[x["conn_class"]] = counts.get(x["conn_class"], 0) + 1

    lines = []
    lines.append(f"================ {DEVICE} recovered-design summary ================")
    lines.append(f"source : {os.path.basename(args.config)}")
    lines.append(f"arcs   : {design.n_arcs} routed ({design.skipped_arcs} global/spine skipped)")
    lines.append("note   : functionally-equivalent primitives, not vendor RTL")
    lines.append("")
    lines.append("== fabric resources ==")
    lines.append(f"LUT4   : {util(res['lut4_used'], res['lut4_capacity'])}"
                 f"  ({res['lut4_driving_fabric']} drive fabric)")
    lines.append(f"FF     : {util(res['ff_used'], res['ff_capacity'])}")
    lines.append(f"EBR9K  : {util(len(hardip['ebr']), res['ebr_capacity'])}")
    lines.append(f"PLL    : {util(len(hardip['plls']), res['pll_capacity'])}")
    lines.append(f"nets   : {res['nets']}")
    lines.append(f"pins   : {len(rows)} configured  "
                 f"({', '.join(f'{k}={counts[k]}' for k in sorted(counts))})")
    lines.append("")
    lines.append("== influence / liveness (cone of influence) ==")
    lines.append("sinks = package pads + register inputs")
    lines.append(f"LUT4 live : {live['lut_live']}/{res['lut4_used']}  "
                 f"({live['lut_dead']} with no visible sink)")
    lines.append(f"FF   live : {live['ff_live']}/{res['ff_used']}  "
                 f"({live['ff_dead']} with no visible sink)")
    lines.append(f"vacuous LUT inputs : {live['vacuous_lut_inputs']} routed "
                 "but the truth table ignores them")
    lines.append("NOTE: LOWER BOUND — EBR write ports + external pad outputs not modelled as sinks")
    lines.append("")
    lines.append("== internal hard IP ==")
    if hardip["sysconfig"]:
        sc = hardip["sysconfig"]
        lines.append(f"sysCONFIG : slave-SPI={sc.get('slave_spi','-')}  GSR={sc.get('gsr','-')}")
    for p in hardip["plls"]:
        divs = ", ".join(f"{k}={v}" for k, v in sorted(p["dividers"].items()) if k.endswith("_DIV"))
        lines.append(f"PLL {p['loc']} : {p['mode']}  outputs={'+'.join(p['outputs'])}  "
                     f"WB={'yes' if p['wishbone'] else 'no'}")
        xtal = 25.0
        freqs = []
        for k, v in sorted(p["dividers"].items()):
            if not k.endswith("_DIV") or k == "CLKFB_DIV": continue
            fb = p["dividers"].get("CLKFB_DIV", 1)
            freqs.append(f"{k[:-4]}={xtal*fb/v:.1f}MHz" if v else f"{k[:-4]}=?")
        lines.append(f"          ratios: {divs}  (crystal=25MHz; {', '.join(freqs)})")
    if hardip["ebr"]:
        lines.append(f"EBR9K x{len(hardip['ebr'])} (uninitialised — no ROM/microcode):")
        for e in hardip["ebr"]:
            lines.append(f"  {e['loc']:<8} mode={e['mode']:<8} width={e['width']}  regmode={e['regmode']}")
    lines.append("")
    lines.append("== edges of knowledge (unknown bits) ==")
    lines.append(f"{unknowns['total']} bits set that Trellis cannot name, "
                 f"across {len(unknowns['by_tiletype'])} tile types:")
    for t, n in sorted(unknowns["by_tiletype"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {t:<22} {n}")

    # ── pin table ──────────────────────────────────────────────────────────────
    H = (f"{'pin':>3}  {'dir':<5} {'site':<13} {'iostd':<18} "
         f"{'drv':<4} {'pull':<8} {'function':<12} {'conn':<8} "
         f"{'fan':>4} {'live':<5}  {'signal':<16} {'chip':<6} "
         f"{'c.pin':<6} {'c.sig':<14} conf")
    SRC = (f"{'':>3}  {'[bs]':<5} {'[bs]':<13} {'[bs]':<18} "
           f"{'[bs]':<4} {'[bs]':<8} {'[bs]':<12} {'[rev]':<8} "
           f"{'[rev]':>4} {'[rev]':<5}  {'[usr]':<16} {'[usr]':<6} "
           f"{'[usr]':<6} {'[usr]':<14} [usr]")
    SEP = "-" * len(H)

    def pin_line(x):
        return (f"{x['pin']:>3}  {x['dir']:<5} {x['site']:<13} "
                f"{x['iostd']:<18} {(x['drive'] or '-'):<4} "
                f"{(x['pull'] or '-'):<8} {(x['si_function'] or '-'):<12} "
                f"{x['conn_class']:<8} {x['fan']:>4} {x['live']:<5}  "
                f"{(x['label'] or '-'):<16} "
                f"{(x['chip_ref'] or '-'):<6} "
                f"{(x['chip_pin'] or '-'):<6} "
                f"{(x['chip_signal'] or '-'):<14} "
                f"{x.get('conf','')}")

    def section(title, subset):
        if not subset: return
        n = len(subset)
        lines.append("")
        lines.append(f"-- {title} ({n} pin{'s' if n!=1 else ''}) --")
        lines.append(H); lines.append(SRC); lines.append(SEP)
        for x in sorted(subset, key=lambda x: x["pin"]):
            lines.append(pin_line(x))

    # ── patterns summary ───────────────────────────────────────────────────────
    lines.append("")
    lines.append("== patterns ==")

    # stuck_pad
    stuck = patterns_by_type.get("stuck_pad", [])
    if stuck:
        lines.append(f"\n-- stuck output pads ({len(stuck)}) --")
        lines.append("  Pads driven by a FF with D=const, CE=1, LSR=0 (permanently static output)")
        lines.append(f"  {'pin':<4} {'label':<16} {'net':<8} {'val':<4} {'clk_net':<8} {'ff_cell'}")
        for lbl, d in sorted(stuck, key=lambda x: x[1].get("pin", 0)):
            lines.append(f"  {d['pin']:<4} {lbl:<16} {d['net']:<8} "
                         f"{d['stuck_value']:<4} {d['clk_net']:<8} {d['ff_cell']}")

    # orphan_pad
    orphans = patterns_by_type.get("orphan_pad", [])
    if orphans:
        lines.append(f"\n-- orphan output pads ({len(orphans)}) --")
        lines.append("  Pads with no fabric driver in recovered netlist")
        lines.append("  Cause: spine/global route, EFB hard connection, or genuine netlist gap")
        lines.append(f"  {'pin':<4} {'label':<16} {'net':<8} {'fanout'}")
        for lbl, d in sorted(orphans, key=lambda x: x[1].get("pin", 0)):
            lines.append(f"  {d['pin']:<4} {lbl:<16} {d['net']:<8} {d['net_fanout']}")

    # shared_net_pad
    shared = patterns_by_type.get("shared_net_pad", [])
    if shared:
        lines.append(f"\n-- shared-net pads ({len(shared)}) --")
        lines.append("  Multiple output pads on same fabric net — LVDS pair, bus, or netlist gap")
        for lbl, d in shared:
            pin_labels = ", ".join(f"pin{p}={lbl2}"
                                   for p, lbl2 in zip(d["pins"], d["labels"]))
            lines.append(f"  {d['net']:<8} {pin_labels}")

    # pclk_lane
    pclk = patterns_by_type.get("pclk_lane", [])
    if pclk:
        lines.append(f"\n-- PCLK/GCLK-capable pads ({len(pclk)}) --")
        lines.append("  Pads on silicon-alternate clock lane pins")
        lines.append(f"  {'pin':<4} {'label':<16} {'si_function':<16} {'dir':<6} {'net':<8} {'site'}")
        for lbl, d in sorted(pclk, key=lambda x: x[1].get("pin", 0)):
            lines.append(f"  {d['pin']:<4} {lbl:<16} {d['si_function']:<16} "
                         f"{d['direction']:<6} {d['net']:<8} {d['site']}")

    # const_ff summary (just count — full list is too long)
    const_ffs = patterns_by_type.get("const_ff", [])
    if const_ffs:
        lines.append(f"\n-- constant FFs ({len(const_ffs)}) --")
        lines.append("  FFs with D=const, CE=1, LSR=0 not driving a pad (stuck-at in fabric)")
        lines.append("  These may be unused registers, tie-offs, or synthesis artefacts.")
        lines.append("  (Full list omitted — query: SELECT * FROM patterns WHERE pattern_type='const_ff')")

    lines.append("")
    lines.append("== pin list ==")
    lines.append("")
    lines.append("Column legend:")
    lines.append("  pin [bs]  package pin  |  dir [bs]  direction  |  site [bs]  tile:PIO")
    lines.append("  iostd [bs]  IO standard  |  drv [bs]  drive mA  |  pull [bs]  termination")
    lines.append("  function [bs]  silicon alt-function  |  conn [rev]  fabric/pll/spi_cfg/unused")
    lines.append("  fan [rev]  LUT/FF fanout or 'src'  |  live [rev]  yes/dead/'-'")
    lines.append("  signal=label [usr]  |  chip/c.pin/c.sig [usr]  |  conf [usr]  confidence")
    lines.append("")
    lines.append("== by peripheral ==")
    remaining = list(rows)
    for title, pred in PERIPHERAL_GROUPS:
        matched = [x for x in remaining if pred(x)]
        remaining = [x for x in remaining if not pred(x)]
        section(title, matched)
    if remaining:
        section("Uncategorised", remaining)

    lines.append("")
    lines.append("")
    lines.append("== by pin number (pattern view) ==")
    lines.append(H); lines.append(SRC); lines.append(SEP)
    for x in sorted(rows, key=lambda x: x["pin"]):
        lines.append(pin_line(x))

    report = "\n".join(lines) + "\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write(report)
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
