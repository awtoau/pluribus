#!/usr/bin/env python3
"""Pluribus — Stage 1: recover netlist and load into fpga_re database.

This is the only script that requires pytrellis.  EVERY run performs a full
drop-and-rebuild for the given label — there is no incremental mode.  Any
unexpected condition is a hard abort.

Pin and net annotations come from a user-supplied TSV (--pins).  The TSV
doubles as the device description file: row/col/pio for each physical pin,
plus label, function, and confidence (1–10).

Usage
-----
  cd /mnt/2tb/git/awto-2000
  TRELLIS_DBROOT=debris/tmp/prjtrellis/database \
  PYTHONPATH=debris/tmp/prjtrellis/libtrellis/build \
  python3 fpga/pluribus/load.py \
    --label V07 \
    --config fpga/v7/FPGA_V07.bin.config \
    --pins fpga/pluribus/hantek2d82-pins.tsv
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from lifters import machxo2_lift as mx
from db import engine, die, EFB_JF, JF_RE, BACKEND
import schema
from sqlalchemy import insert, delete, select, update, func, text

# EFB ports that MUST appear in the recovered bitstream for LCMXO2 with SPI enabled
REQUIRED_EFB_PORTS = {"JTCK", "JTDI", "JUPDATE", "JRSTN", "JSHIFTDR", "JTDO"}


def assert_eq(label, got, expected):
    if got != expected:
        die(f"{label}: expected {expected!r}, got {got!r}")


def assert_ge(label, got, minimum):
    if got < minimum:
        die(f"{label}: expected >= {minimum}, got {got!r}")


# ── helpers ───────────────────────────────────────────────────────────────────

def _insert_or_ignore(table):
    """Return an INSERT statement with ON CONFLICT DO NOTHING for the active backend."""
    if BACKEND == "sqlite":
        return insert(table).prefix_with("OR IGNORE")
    else:
        return insert(table).on_conflict_do_nothing()


# ── TSV pin file ─────────────────────────────────────────────────────────────

def parse_pins_tsv(path):
    """Return (metadata, pin_rows).

    metadata: dict from '# key: value' header lines
    pin_rows: list of (pin, row, col, pio, direction, label, function, confidence,
                       chip_ref, chip_pin, chip_signal)
    Columns 9-11 (chip_ref, chip_pin, chip_signal) are optional — older TSV files
    with only 8 columns are still accepted.
    """
    meta = {}
    rows = []
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                m = re.match(r'^#\s+(\w[\w_]*):\s+(.+)$', line)
                if m:
                    meta[m.group(1)] = m.group(2).strip()
                continue
            parts = line.split("\t")
            if len(parts) < 8:
                die(f"{path}: bad pin row (need 8 tab-separated fields): {line!r}")
            pin, row, col, pio, direction, label, function, confidence = parts[:8]
            chip_ref    = parts[8].strip()  if len(parts) > 8  else ""
            chip_pin    = parts[9].strip()  if len(parts) > 9  else ""
            chip_signal = parts[10].strip() if len(parts) > 10 else ""
            try:
                pin  = int(pin)
                row  = int(row)
                col  = int(col)
                conf = int(confidence)
            except ValueError as e:
                die(f"{path}: parse error in row {line!r}: {e}")
            if direction not in ("in","out","bidir","nc","cfg"):
                die(f"{path}: pin {pin}: unknown direction {direction!r}")
            if not (1 <= conf <= 10):
                die(f"{path}: pin {pin}: confidence {conf} not in 1–10")
            rows.append((pin, row, col, pio, direction, label, function.strip(), conf,
                         chip_ref, chip_pin, chip_signal))
    return meta, rows


# ── fpga_nets.tsv loader ─────────────────────────────────────────────────────

def parse_fpga_nets_tsv(path):
    """Return list of (net, name, type_, confidence, freq_mhz, hpbx, ff_count, notes).

    Reads fpga_nets.tsv — human-maintained net annotation table.
    Comment lines (#) and blank lines are skipped.
    Confidence must be one of: confirmed, inferred, speculative.
    """
    rows = []
    valid_conf = {"confirmed", "inferred", "speculative"}
    valid_type = {"clk", "data", "ctrl", "pad", "unknown"}
    with open(path) as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 8:
                die(f"{path}:{lineno}: need 8 tab-separated fields, got {len(parts)}: {line!r}")
            net, name, type_, confidence, freq_mhz, hpbx, ff_count, notes = parts[:8]
            net = net.strip(); name = name.strip(); type_ = type_.strip()
            confidence = confidence.strip()
            if confidence not in valid_conf:
                die(f"{path}:{lineno}: confidence must be one of {valid_conf}, got {confidence!r}")
            if type_ not in valid_type:
                die(f"{path}:{lineno}: type must be one of {valid_type}, got {type_!r}")
            freq = float(freq_mhz.strip()) if freq_mhz.strip() else None
            ffc  = int(ff_count.strip())   if ff_count.strip()  else None
            rows.append((net, name, type_, confidence, freq, hpbx.strip() or None, ffc, notes.strip()))
    return rows


# ── LUT classify ─────────────────────────────────────────────────────────────

def classify_lut(init_str):
    v = int(init_str[::-1], 2)
    if v == 0:      return "CONST0"
    if v == 0xFFFF: return "CONST1"
    deps = sorted(mx.lut_dependence(init_str))
    nd   = len(deps)
    if nd == 0:
        return "CONST0" if v == 0 else "CONST1"
    if nd == 1:
        p = deps[0]; w = {"a":1,"b":2,"c":4,"d":8}[p]
        b0 = (v>>0)&1; b1 = (v>>w)&1
        if b0 == 0 and b1 == 1: return f"BUF({p})"
        if b0 == 1 and b1 == 0: return f"INV({p})"
        raise AssertionError(f"unreachable: nd==1 but b0={b0} b1={b1} for {p}")
    if nd == 2:
        a,b = deps
        wa = {"a":1,"b":2,"c":4,"d":8}[a]; wb = {"a":1,"b":2,"c":4,"d":8}[b]
        out = tuple((v>>i)&1 for i in [0,wb,wa,wa|wb])
        pats = {
            (0,0,0,1): f"AND({a},{b})",  (1,1,1,0): f"NAND({a},{b})",
            (0,1,1,1): f"OR({a},{b})",   (1,0,0,0): f"NOR({a},{b})",
            (0,1,1,0): f"XOR({a},{b})",  (1,0,0,1): f"XNOR({a},{b})",
        }
        return pats.get(out, f"COMBO2({a},{b})")
    if nd == 3:
        a,b,c = deps
        wi = {"a":1,"b":2,"c":4,"d":8}
        for sel,i0,i1 in [(a,b,c),(b,a,c),(c,a,b)]:
            ws=wi[sel]; w0=wi[i0]; w1=wi[i1]
            ok = all(((v>>(b0*w0+b1*w1))&1)==b0 and
                     ((v>>(ws+b0*w0+b1*w1))&1)==b1
                     for b0 in range(2) for b1 in range(2))
            if ok: return f"MUX({sel},{i0},{i1})"
        return f"COMBO3({a},{b},{c})"
    return "COMBO4"


def resolve_net(design, lift, row, col, wire):
    key = lift.gkey(row, col, wire)
    if key is None or key not in design.dsu.p:
        return None
    return design.net_name.get(design.dsu.find(key))


# ── Main load ─────────────────────────────────────────────────────────────────

def load(label, config_path, pins_tsv, device, package, nets_tsv=None, fuzz=False):
    t0 = time.time()

    # ── parse pin annotation file ──────────────────────────────────────────
    print(f"Reading pin annotations from {pins_tsv}…")
    meta, pin_rows = parse_pins_tsv(pins_tsv)
    print(f"  device={meta.get('device','?')}  package={meta.get('package','?')}  "
          f"crystal={meta.get('crystal','?')}  {len(pin_rows)} pins")

    # Metadata in file should match CLI args (fail if mismatch)
    if meta.get("device") and meta["device"] != device:
        die(f"Pin file device {meta['device']!r} != CLI device {device!r}")
    if meta.get("package") and meta["package"] != package:
        die(f"Pin file package {meta['package']!r} != CLI package {package!r}")

    # Skip cfg/nc pins for fabric net resolution
    fabric_pins = [(pin, row, col, pio, direction, label, fn, conf, cref, cpin, csig)
                   for pin, row, col, pio, direction, label, fn, conf, cref, cpin, csig in pin_rows
                   if direction not in ("nc", "cfg")]

    # ── recover netlist ────────────────────────────────────────────────────
    print(f"Recovering netlist from {config_path}…")
    if not os.path.exists(config_path):
        die(f"Config file not found: {config_path}")
    lift   = mx.MachXO2Lift(device)
    pc     = lift.parse_config(config_path)
    design = lift.recover_netlist(pc)

    n_ffs   = len(design.ffs)
    n_luts  = len(design.luts)
    n_nets  = len(design.all_nets)
    print(f"  {n_ffs} FFs  {n_luts} LUTs  {n_nets} nets  ({time.time()-t0:.1f}s)")

    if not fuzz:
        assert_ge("FFs",   n_ffs,  100)
        assert_ge("LUTs",  n_luts, 100)
        assert_ge("nets",  n_nets, 500)

    # ── connect to DB and ALWAYS drop + recreate the label ─────────────────
    schema.init()   # create tables if this is a fresh DB

    with engine().begin() as conn:
        # Upsert the bitstream row — keep the existing id stable so concurrent reach.py
        # workers don't hit FK violations when load.py runs again mid-BFS.
        if BACKEND == "sqlite":
            # SQLite: INSERT OR REPLACE then SELECT id (no RETURNING in older SA/SQLite)
            conn.execute(
                insert(schema.bitstreams).prefix_with("OR REPLACE").values(
                    label=label,
                    filename=os.path.basename(config_path),
                    device=device,
                    package=package,
                )
            )
            bs_id = conn.execute(
                select(schema.bitstreams.c.id).where(schema.bitstreams.c.label == label)
            ).scalar()
        else:
            bs_id = conn.execute(
                insert(schema.bitstreams)
                .values(
                    label=label,
                    filename=os.path.basename(config_path),
                    device=device,
                    package=package,
                )
                .on_conflict_do_update(
                    index_elements=["label"],
                    set_=dict(
                        filename=os.path.basename(config_path),
                        device=device,
                        package=package,
                    ),
                )
                .returning(schema.bitstreams.c.id)
            ).scalar()

        if bs_id is None:
            die("INSERT INTO bitstreams returned NULL id")
        print(f"  bitstream id={bs_id}")

        # Clear all dependent rows for this bitstream before re-inserting.
        # Cascade order: child tables first, then nets (parent of most).
        for tbl in (
            schema.pad_ff_influence,
            schema.reachability,
            schema.net_names,
            schema.cell_names,
            schema.pad_map,
            schema.ffs,
            schema.luts,
            schema.const_nets,
            schema.net_fanout,
            schema.arcs,
            schema.net_stats,
            schema.clock_domains,
            schema.nets,
            schema.ebr_ports,
            schema.efb_ports,
        ):
            conn.execute(delete(tbl).where(tbl.c.bitstream == bs_id))

        # ── nets ───────────────────────────────────────────────────────────────
        net_list = sorted(design.all_nets)
        conn.execute(
            insert(schema.nets),
            [{"bitstream": bs_id, "name": n} for n in net_list],
        )
        net_count = conn.execute(
            select(func.count()).select_from(schema.nets)
            .where(schema.nets.c.bitstream == bs_id)
        ).scalar()
        assert_eq("net count in DB", net_count, n_nets)

        # ── FFs ───────────────────────────────────────────────────────────────
        # Fail-fast before insert: every FF must have a name and a Q net
        bad_ffs = [ff for ff in design.ffs if not ff.get("name") or not ff.get("q")]
        if bad_ffs:
            die(f"{len(bad_ffs)} FFs have missing name or Q: {[f['name'] for f in bad_ffs[:5]]}")
        conn.execute(
            insert(schema.ffs),
            [{"bitstream": bs_id, "cell": ff["name"], "clk": ff["clk"],
              "ce": ff["ce"], "d": ff["d"], "q": ff["q"], "lsr": ff["lsr"]}
             for ff in design.ffs],
        )
        ff_count = conn.execute(
            select(func.count()).select_from(schema.ffs)
            .where(schema.ffs.c.bitstream == bs_id)
        ).scalar()
        assert_eq("FF count in DB", ff_count, n_ffs)

        # ── LUTs ──────────────────────────────────────────────────────────────
        conn.execute(
            insert(schema.luts),
            [{"bitstream": bs_id, "cell": lt["name"], "init": lt["init"],
              "a": lt.get("a"), "b": lt.get("b"), "c": lt.get("c"), "d": lt.get("d"),
              "z": lt.get("z"),
              "deps": sorted(mx.lut_dependence(lt["init"])),
              "fn": classify_lut(lt["init"])}
             for lt in design.luts],
        )
        lut_count = conn.execute(
            select(func.count()).select_from(schema.luts)
            .where(schema.luts.c.bitstream == bs_id)
        ).scalar()
        assert_eq("LUT count in DB", lut_count, n_luts)

        # ── net_fanout ─────────────────────────────────────────────────────────
        fanout_rows = []
        for ff in design.ffs:
            q = ff["q"]
            for pin, net in (("D",ff["d"]),("CLK",ff["clk"]),("CE",ff["ce"]),("LSR",ff["lsr"])):
                if net and not net.startswith("1'b"):
                    fanout_rows.append({"bitstream": bs_id, "net": net, "cell_type": "FF",
                                        "cell": ff["name"], "pin": pin, "out_net": q})
        for lt in design.luts:
            z = lt.get("z")
            for pin in ("a","b","c","d"):
                net = lt.get(pin)
                if net and not net.startswith("1'b"):
                    fanout_rows.append({"bitstream": bs_id, "net": net, "cell_type": "LUT",
                                        "cell": lt["name"], "pin": pin.upper(), "out_net": z})

        if not fuzz:
            assert_ge("fanout rows", len(fanout_rows), 100)
        conn.execute(insert(schema.net_fanout), fanout_rows)
        fanout_count = conn.execute(
            select(func.count()).select_from(schema.net_fanout)
            .where(schema.net_fanout.c.bitstream == bs_id)
        ).scalar()
        assert_eq("fanout count in DB", fanout_count, len(fanout_rows))
        print(f"  {len(fanout_rows)} fanout entries")

        # ── pad_map ────────────────────────────────────────────────────────────
        # Step 1: scan bitstream JQ/JA arcs to discover ALL configured pads.
        # This is authoritative — no TSV coordinates needed.
        _JQ = re.compile(r'^JQ(\d)$')
        _JA = re.compile(r'^JA(\d)$')

        # Parse iomap to map (row,col,pio) -> (pin#, dir, iostd, drive, pull, si_function).
        # iomap sits next to the .config file and is generated from the bitstream.
        iomap_path = str(config_path) + ".iomap.tsv"
        iomap_by_site = {}   # (row,col,pio) -> pin#
        iomap_io      = {}   # pin# -> (dir, iostd, drive, pull, si_function)
        if os.path.exists(iomap_path):
            with open(iomap_path) as _fh:
                _hdr = _fh.readline().rstrip("\n").split("\t")
                _col = {n: i for i, n in enumerate(_hdr)}
                for _line in _fh:
                    _parts = _line.rstrip("\n").split("\t")
                    if len(_parts) < 5: continue
                    _site = _parts[_col["site"]]
                    _m = re.match(r"R(\d+)C(\d+):PIO(\w)", _site)
                    if not _m: continue
                    _k   = (int(_m.group(1)), int(_m.group(2)), _m.group(3))
                    _pin = int(_parts[_col["pin"]])
                    iomap_by_site[_k] = _pin
                    iomap_io[_pin] = (
                        _parts[_col["dir"]]   if "dir"   in _col else "",
                        _parts[_col["iostd"]] if "iostd" in _col and len(_parts) > _col["iostd"] else "",
                        _parts[_col["drive"]] if "drive" in _col and len(_parts) > _col["drive"] else "",
                        _parts[_col["pull"]]  if "pull"  in _col and len(_parts) > _col["pull"]  else "",
                        _parts[_col["function"]] if "function" in _col and len(_parts) > _col["function"] else "",
                    )
            print(f"  iomap: {len(iomap_by_site)} configured pins from {os.path.basename(iomap_path)}")
        else:
            print(f"  WARNING: no iomap found at {iomap_path} — pad discovery will be TSV-only")

        # Build TSV annotation lookup keyed by pin number
        tsv_by_pin = {}  # pin# -> (label, fn, conf, direction_tsv, chip_ref, chip_pin, chip_signal)
        for pin, row, col, pio, direction, label_p, fn, conf, cref, cpin, csig in fabric_pins:
            tsv_by_pin[pin] = (label_p, fn, conf, direction, cref, cpin, csig)

        # Classify connectivity: use machxo2_lift arc endpoint sets
        sources, sinks = lift.arc_endpoint_sets(pc)

        # Discover all pads from JQ/JA arcs in the bitstream
        discovered = {}  # (row,col,pio,direction) -> net_name
        for (r, c, sink, src) in pc.arcs:
            for wire in (sink, src):
                mq = _JQ.match(wire); ma = _JA.match(wire)
                if not mq and not ma: continue
                idx = int((mq or ma).group(1))
                pio = chr(ord("A") + idx)
                direction = "in" if mq else "out"
                for actual_row in (r, r - 1, r + 1):
                    if actual_row < 0: continue
                    if (actual_row, c, pio) in iomap_by_site:
                        net = mx.pad_net(design, lift, actual_row, c, pio, direction)
                        key = (actual_row, c, pio, direction)
                        if key not in discovered:
                            discovered[key] = net
                        break

        from collections import defaultdict
        by_site = defaultdict(dict)  # (row,col,pio) -> {direction: net}
        for (row, col, pio, direction), net in discovered.items():
            by_site[(row, col, pio)][direction] = net

        tsv_sites = {}  # pin# -> (row,col,pio)
        for pin, row, col, pio, direction, label_p, fn, conf, cref, cpin, csig in fabric_pins:
            tsv_sites[pin] = (row, col, pio)

        iomap_pins = set(iomap_by_site.values())
        pad_rows_out = []  # (pin,row,col,pio,dir,label,fn,conf,ni,no,iostd,drive,pull,si_fn,conn,cref,cpin,csig)

        for (row, col, pio), dir_nets in sorted(by_site.items()):
            pin = iomap_by_site.get((row, col, pio))
            if pin is None: continue
            ni = dir_nets.get("in")
            no = dir_nets.get("out")
            if ni and no:     direction = "bidir"
            elif ni:          direction = "in"
            else:             direction = "out"
            ann = tsv_by_pin.get(pin)
            label_p = ann[0] if ann else f"pin{pin}"
            fn      = ann[1] if ann else ""
            conf    = ann[2] if ann else 1
            cref    = ann[4] if ann else ""
            cpin_s  = ann[5] if ann else ""
            csig    = ann[6] if ann else ""
            io      = iomap_io.get(pin, ("","","","",""))
            in_conn  = lift.pad_fabric_node(row, col, pio, "in")  in sources
            out_conn = lift.pad_fabric_node(row, col, pio, "out") in sinks
            si_fn    = io[4]
            conn_cls = mx.classify_pin(si_fn, in_conn, out_conn)
            pad_rows_out.append((pin, row, col, pio, direction, label_p, fn, conf,
                                 ni, no, io[1], io[2], io[3], si_fn, conn_cls,
                                 cref, cpin_s, csig))

        for pin, (row, col, pio) in sorted(tsv_sites.items()):
            if pin in iomap_pins: continue
            ann = tsv_by_pin.get(pin, (f"pin{pin}", "", 1, "in", "", "", ""))
            pad_rows_out.append((pin, row, col, pio, ann[3], ann[0], ann[1], ann[2],
                                 None, None, "", "", "", "", "unused",
                                 ann[4], ann[5], ann[6]))

        pad_resolved   = sum(1 for r in pad_rows_out if r[8] or r[9])
        pad_unresolved = [r for r in pad_rows_out if not r[8] and not r[9]]

        pad_map_insert_rows = []
        net_names_insert_rows = []
        for (pin, row, col, pio, direction, label_p, fn, conf,
             ni, no, iostd, drive, pull, si_fn, conn_cls,
             cref, cpin_s, csig) in pad_rows_out:
            pad_map_insert_rows.append({
                "bitstream": bs_id, "pin": pin, "label": label_p,
                "row": row, "col": col, "pio": pio, "direction": direction,
                "net_in": ni, "net_out": no,
                "iostd": iostd or None, "drive": drive or None, "pull": pull or None,
                "si_function": si_fn or None, "conn_class": conn_cls or None,
                "chip_ref": cref or None, "chip_pin": cpin_s or None,
                "chip_signal": csig or None,
            })
            net = ni or no
            if net:
                net_names_insert_rows.append({
                    "bitstream": bs_id, "net": net, "name": label_p,
                    "description": fn,
                    "confidence": ("confirmed" if conf >= 8 else
                                   "estimate" if conf >= 5 else "guess"),
                    "source": "pins_tsv",
                })

        conn.execute(insert(schema.pad_map), pad_map_insert_rows)
        if net_names_insert_rows:
            conn.execute(_insert_or_ignore(schema.net_names), net_names_insert_rows)

        print(f"  {pad_resolved}/{len(pad_rows_out)} pads resolved  "
              f"({len(pad_unresolved)} not routed in this bitstream)")
        if pad_unresolved:
            print(f"  Not routed: {', '.join(r[5] for r in pad_unresolved[:10])}")
        if pad_resolved == 0 and not fuzz:
            die("Zero fabric pads resolved — wrong device/config or machxo2_lift bug")

        # ── fpga_nets.tsv — user net annotations (names + confidence) ─────────
        if nets_tsv:
            print(f"Reading net annotations from {nets_tsv}…")
            net_rows = parse_fpga_nets_tsv(nets_tsv)
            inserted = skipped = 0
            for (net, name, type_, confidence, freq, hpbx, ffc, notes) in net_rows:
                result = conn.execute(
                    _insert_or_ignore(schema.net_names).values(
                        bitstream=bs_id, net=net, name=name,
                        description=notes or None, confidence=confidence,
                        source="fpga_nets_tsv",
                    )
                )
                if result.rowcount:
                    inserted += 1
                else:
                    skipped += 1
            print(f"  {inserted} net names inserted  ({skipped} skipped — already named by pins TSV)")

        # ── efb_ports ─────────────────────────────────────────────────────────
        found_efb = {}
        for (er,ec),t in pc.tile_type.items():
            if t != "CIB_CFG2": continue
            for (r,c,sink,src) in pc.arcs:
                if r != er or c != ec: continue
                m = JF_RE.match(src)
                if m:
                    port = EFB_JF.get(int(m.group(1)), f"JF{m.group(1)}")
                    net  = resolve_net(design, lift, er, ec, sink)
                    if net and port not in found_efb:
                        found_efb[port] = net
                        conn.execute(
                            _insert_or_ignore(schema.efb_ports).values(
                                bitstream=bs_id, port_name=port, net=net,
                            )
                        )

        # EFB output fixed connections: JWBDATO[0-7], JWBACKO, JSPIIRQO, etc.
        # machxo2_lift.apply_efb_fixed_conns() unioned synthetic string nodes
        # (e.g. "JWBDATO0") into the DSU so that FFs whose D-input wires trace
        # back to EFB outputs now get real net names.  We look them up here and
        # insert them as efb_ports so the knowledge layer can reference them.
        for efb_port in sorted(getattr(design, "efb_resolved", ())):
            root = design.dsu.find(efb_port)
            net = design.net_name.get(root)
            if net and efb_port not in found_efb:
                found_efb[efb_port] = net
                conn.execute(
                    _insert_or_ignore(schema.efb_ports).values(
                        bitstream=bs_id, port_name=efb_port, net=net,
                    )
                )

        has_cfg2 = any(t == "CIB_CFG2" for t in pc.tile_type.values())
        missing_efb = REQUIRED_EFB_PORTS - set(found_efb)
        if missing_efb and has_cfg2 and not fuzz:
            die(f"Missing required EFB ports: {sorted(missing_efb)}")
        efb_output_count = sum(1 for p in found_efb if p.startswith("JWB") or p.startswith("JSPI") or p.startswith("JTC") or p.startswith("JPLL"))
        print(f"  EFB ports: {len(found_efb)} total ({efb_output_count} EFB outputs resolved from fixed conns)")

        # ── ebr_ports ─────────────────────────────────────────────────────────
        JA = re.compile(r'^J[AB]\d+$'); JC = re.compile(r'^J[CD]\d+$')
        JX = re.compile(r'^(JCLK|JLSR|JCE|JWE)\d*$')
        ebr_count = 0
        for (er,ec),ttype in pc.tile_type.items():
            if ttype != "EBR1": continue
            block = f"R{er}C{ec}"
            for (r,c,sink,src) in pc.arcs:
                if r != er or c != ec: continue
                net  = resolve_net(design, lift, er, ec, src)
                role = ("write" if JA.match(sink) else
                        "read"  if JC.match(sink) else
                        "ctrl"  if JX.match(sink) else None)
                if role:
                    conn.execute(
                        _insert_or_ignore(schema.ebr_ports).values(
                            bitstream=bs_id, block=block, port=sink, role=role, net=net,
                        )
                    )
                    ebr_count += 1
        print(f"  {ebr_count} EBR port arcs")

        # ── ebr read-side fanout → net_fanout ─────────────────────────────────
        # EBR read nets (JC/JD ports) appear as inputs to LUTs/FFs but are not
        # captured in net_fanout during the normal LUT/FF pass (which only looks
        # at cells, not at what drives their inputs from outside the fabric).
        # Build an index of all EBR read nets, then scan LUTs and FFs for any
        # cell that has one as an input, and insert the missing net_fanout rows.
        ebr_read_nets = {}   # net_name → (block, port)
        for (er, ec), ttype in pc.tile_type.items():
            if ttype != "EBR1": continue
            block = f"R{er}C{ec}"
            for (r, c, sink, src) in pc.arcs:
                if r != er or c != ec: continue
                if not JC.match(sink): continue
                net = resolve_net(design, lift, er, ec, src)
                if net:
                    ebr_read_nets[net] = (block, sink)

        ebr_fanout_rows = []
        for ff in design.ffs:
            for pin, val in (("D", ff["d"]), ("CE", ff["ce"]),
                              ("CLK", ff["clk"]), ("LSR", ff["lsr"])):
                if val in ebr_read_nets:
                    ebr_fanout_rows.append(
                        {"bitstream": bs_id, "net": val, "cell_type": "FF",
                         "cell": ff["name"], "pin": pin, "out_net": ff["q"]}
                    )
        for lt in design.luts:
            for pin, val in (("A", lt["a"]), ("B", lt["b"]),
                              ("C", lt["c"]), ("D", lt["d"])):
                if val in ebr_read_nets:
                    ebr_fanout_rows.append(
                        {"bitstream": bs_id, "net": val, "cell_type": "LUT",
                         "cell": lt["name"], "pin": pin, "out_net": lt["z"]}
                    )
        if ebr_fanout_rows:
            conn.execute(insert(schema.net_fanout), ebr_fanout_rows)
        print(f"  {len(ebr_read_nets)} EBR read nets  "
              f"{len(ebr_fanout_rows)} fanout entries stitched")

        # ── EBR write-side fanout → net_fanout ────────────────────────────────
        # Each EBR write-data net (JA/JB ports) needs net_fanout rows so BFS can
        # traverse through the EBR block to its read-data nets (JC/JD ports).
        # Without this, ADC pad nets that feed EBR write ports appear as dead ends
        # in the reachability graph and chains.py sections 3/4 return empty.
        # Each write net gets one row per read net in the same block (out_net=read
        # net), modelling EBR as a transparent memory for reachability purposes.
        _JA_write = re.compile(r'^J[AB]\d+$')
        _JC_read  = re.compile(r'^J[CD]\d+$')

        # Build per-block write/read net lists from already-populated ebr_ports
        ebr_ports_rows = conn.execute(
            select(
                schema.ebr_ports.c.block,
                schema.ebr_ports.c.port,
                schema.ebr_ports.c.role,
                schema.ebr_ports.c.net,
            ).where(schema.ebr_ports.c.bitstream == bs_id)
        ).fetchall()

        _ebr_by_block: dict = {}
        for block, port, role, net in ebr_ports_rows:
            if not net:
                continue
            entry = _ebr_by_block.setdefault(block, {"write": [], "read": []})
            if role == "write" and _JA_write.match(port):
                entry["write"].append((port, net))
            elif role == "read" and _JC_read.match(port):
                entry["read"].append((port, net))

        ebr_write_fanout = []
        for block, ports in _ebr_by_block.items():
            for w_port, w_net in ports["write"]:
                for _r_port, r_net in ports["read"]:
                    ebr_write_fanout.append(
                        {"bitstream": bs_id, "net": w_net, "cell_type": "EBR",
                         "cell": block, "pin": w_port, "out_net": r_net}
                    )
        if ebr_write_fanout:
            conn.execute(_insert_or_ignore(schema.net_fanout), ebr_write_fanout)
        print(f"  {len(ebr_write_fanout)} EBR write-side fanout entries stitched")

        # ── EBR JQ (read data) → output-FF stitching ─────────────────────────
        # In MachXO2 PDPW8KC/DP8KC, the EBR read data exits via JQ output wires
        # in the adjacent CIB tile (JQ0..JQ7 appearing as arc sources).  These JQ
        # nets are captured in pc.arcs and get DSU net names, but they have no
        # net_fanout entries because they don't appear as LUT/FF inputs — they feed
        # fabric output-register FFs whose DI wire is hardwired from the EBR and is
        # invisible in the arc model (the prjtrellis model leaves those FF D inputs
        # as '1'b0').
        #
        # We identify EBR output FFs as: d='1'b0' AND clk matches any JCLK net of
        # the same EBR block AND located within ±6 rows and ±3 cols of the EBR.
        # Then we insert two sets of fanout rows:
        #   (a) each EBR write net → each JQ read net  (write-to-read transparency)
        #   (b) each JQ net → each output-FF Q net      (JQ output register path)
        #
        # Bit mapping is unknown (hardwired silicon), so this is conservative:
        # every write net reaches every JQ, and every JQ reaches every output FF.
        _JQ_re = re.compile(r'^JQ\d+$')
        _JCLK_re = re.compile(r'^JCLK\d*$')

        # Collect per-EBR block: JCLK nets, JQ nets, write nets
        _ebr_full: dict = {}  # block → {jclk_nets, jq_nets, write_nets}
        for (er, ec), ttype in pc.tile_type.items():
            if ttype != "EBR1":
                continue
            block = f"R{er}C{ec}"
            info = _ebr_full.setdefault(block, {
                "er": er, "ec": ec,
                "jclk_nets": set(), "jq_nets": [], "write_nets": []
            })
            # Collect JCLK nets and write data nets from EBR tile arcs
            for (r, c, sink, src) in pc.arcs:
                if r != er or c != ec:
                    continue
                net = resolve_net(design, lift, er, ec, src)
                if net:
                    if _JCLK_re.match(sink):
                        info["jclk_nets"].add(net)
                    if _JA_write.match(sink):
                        info["write_nets"].append(net)
            # Collect JQ nets from the CIB tile immediately adjacent to the EBR.
            # EBR at (er, ec) has its JQ read-data outputs at (er, ec-1) — the
            # CIB tile to the left.  We restrict to same row (r==er) to avoid
            # picking up JQ wires from right-edge IOLOGIC pads (col=ec+1) which
            # use JQ wires for ADC input pad data, not EBR DOB outputs.
            for (r, c, sink, src) in pc.arcs:
                if r != er or c != ec - 1:
                    continue
                if not _JQ_re.match(src):
                    continue
                k = lift.gkey(r, c, src)
                if k is None:
                    continue
                root = design.dsu.find(k)
                net = design.net_name.get(root)
                if net and net not in info["jq_nets"]:
                    info["jq_nets"].append(net)

        # Find output FFs for each EBR (d='1'b0' + spatially near EBR).
        # In MachXO2 PDPW8KC/DP8KC with OUTREG, the EBR output register FFs are
        # physically placed adjacent to the EBR block.  Their DI input is hardwired
        # from EBR DOB (invisible in prjtrellis arcs), so they appear with d='1'b0'.
        # We cannot match by JCLK because the fabric pipeline registers downstream
        # of the EBR use their own clock (not the EBR read clock).  Instead we use
        # spatial proximity: any FF with d='1'b0' within ±4 rows and ±4 cols of
        # the EBR is treated as a potential output register or downstream pipeline FF.
        _block_to_output_ffs: dict = {}  # block → [ff.q, ...]
        for ff in design.ffs:
            if ff["d"] != "1'b0":
                continue
            # Parse FF row/col from name ff_rNcM_XY  (e.g. ff_r8c20_C1)
            try:
                import re as _re
                m = _re.match(r'^ff_r(\d+)c(\d+)_', ff["name"])
                if not m:
                    continue
                ff_r, ff_c = int(m.group(1)), int(m.group(2))
            except (ValueError, AttributeError):
                continue
            for block, info in _ebr_full.items():
                er, ec = info["er"], info["ec"]
                if abs(ff_r - er) <= 4 and abs(ff_c - ec) <= 4:
                    _block_to_output_ffs.setdefault(block, []).append(ff["q"])

        # Insert fanout rows
        ebr_jq_fanout = []
        for block, info in _ebr_full.items():
            jq_nets    = info["jq_nets"]
            write_nets = info["write_nets"]
            out_ffs    = _block_to_output_ffs.get(block, [])

            # (a) write net → JQ net (EBR memory transparency)
            for w_net in write_nets:
                for jq_net in jq_nets:
                    ebr_jq_fanout.append(
                        {"bitstream": bs_id, "net": w_net, "cell_type": "EBR",
                         "cell": block, "pin": "JQ_src", "out_net": jq_net}
                    )
            # (b) JQ net → output FF Q (output register path)
            for jq_net in jq_nets:
                for ff_q in out_ffs:
                    ebr_jq_fanout.append(
                        {"bitstream": bs_id, "net": jq_net, "cell_type": "EBR",
                         "cell": block, "pin": "JQ_ff", "out_net": ff_q}
                    )

        if ebr_jq_fanout:
            conn.execute(_insert_or_ignore(schema.net_fanout), ebr_jq_fanout)
        n_jq_blocks = sum(1 for b in _ebr_full if _ebr_full[b]["jq_nets"])
        print(f"  {n_jq_blocks} EBR blocks with JQ outputs  "
              f"{len(ebr_jq_fanout)} EBR JQ fanout entries stitched")

        # ── IOLOGIC stitching: fabric net → CIB_PIC JA/JB port → pad ─────────
        # PIC_B* (bottom edge) and PIC_R* / PIC_L* tiles have CIB tiles that
        # contain JA0-JA3 / JB0-JB3 IOLOGIC input ports.  A fabric net drives
        # JA{n} in the CIB tile; the IOLOGIC passes it to the pad in the
        # adjacent PIC tile.  recover_netlist() sees the fabric net but does not
        # follow it through IOLOGIC to the pad net.
        #
        # Mapping: JA_idx / JB_idx → PIO letter: 0→A, 1→B, 2→C, 3→D
        # CIB_PIC_B* tiles: pad is in the row below (row+1), same col
        # PIC_R0 / CIB_PIC_R* tiles: pad is in the same tile (row, col)
        # PIC_L0 / CIB_PIC_L* tiles: pad is in the same tile (row, col)
        #
        # For each JA/JB arc found, look up the pad_map entry for that site+PIO
        # and insert a net_fanout row: fabric_net → pad cell, out_net=pad.net_out.
        # Also patch pad_map.net_out for orphan output pads (fanin=0) that are
        # driven through IOLOGIC.

        _JA_iologic = re.compile(r'^J([AB])(\d)$')
        _pio_letter  = {0: "A", 1: "B", 2: "C", 3: "D"}

        # Load current pad_map indexed by (row, col, pio)
        pad_map_rows_db = conn.execute(
            select(
                schema.pad_map.c.pin,
                schema.pad_map.c.row,
                schema.pad_map.c.col,
                schema.pad_map.c.pio,
                schema.pad_map.c.direction,
                schema.pad_map.c.net_in,
                schema.pad_map.c.net_out,
            ).where(schema.pad_map.c.bitstream == bs_id)
        ).fetchall()

        pad_by_site = {}
        for pin, p_row, p_col, p_pio, p_dir, p_ni, p_no in pad_map_rows_db:
            pad_by_site[(p_row, p_col, p_pio)] = {
                "pin": pin, "dir": p_dir, "net_in": p_ni, "net_out": p_no
            }

        iologic_fanout  = []   # dicts for net_fanout
        boundary_nets   = []   # dicts for nets table
        boundary_map    = {}   # pad_pin -> boundary_net  ("pad_<pin>")

        for (cr, cc), ttype in pc.tile_type.items():
            is_bottom = "PIC_B" in ttype
            is_top    = "PIC_T" in ttype
            is_right  = "PIC_R" in ttype
            is_left   = "PIC_L" in ttype
            if not (is_bottom or is_top or is_right or is_left):
                continue

            for (r, c, sink, src) in pc.arcs:
                if r != cr or c != cc:
                    continue
                m = _JA_iologic.match(sink)
                if not m:
                    continue
                ab, idx_s = m.group(1), int(m.group(2))
                pio = _pio_letter.get(idx_s)
                if pio is None:
                    continue

                fabric_net = resolve_net(design, lift, r, c, src)
                if not fabric_net:
                    continue

                if is_bottom:
                    pad_row, pad_col = r + 1, c
                elif is_top:
                    # Top-edge CIB_PIC_T0: the PIO pad is in the row above (row-1).
                    # Row 0 CIB_PIC_T tiles contain JA/JB arcs; the physical PIO
                    # is in the adjacent PIC_T0 tile one row higher (row=-1 DNE,
                    # but pad_map was built from iomap which uses row 0 for top-edge).
                    pad_row, pad_col = r - 1, c
                else:
                    pad_row, pad_col = r, c

                pad = pad_by_site.get((pad_row, pad_col, pio))
                if pad is None:
                    continue

                pin = pad["pin"]
                if pin not in boundary_map:
                    bnet = f"pad_{pin}"
                    boundary_map[pin] = bnet
                    boundary_nets.append({"bitstream": bs_id, "name": bnet})

                bnet = boundary_map[pin]
                iologic_fanout.append(
                    {"bitstream": bs_id, "net": fabric_net, "cell_type": "PAD",
                     "cell": f"pad_{pin}", "pin": ab + str(idx_s), "out_net": bnet}
                )

        # Insert synthetic pad boundary nets into the nets table so reach.py sees them
        if boundary_nets:
            conn.execute(_insert_or_ignore(schema.nets), boundary_nets)
        if iologic_fanout:
            conn.execute(_insert_or_ignore(schema.net_fanout), iologic_fanout)
        # Update pad_map.net_out for every output pad to its boundary net
        # so queries like "JOIN pad_map ON net_out = reachability.dst" work generically.
        for pin, bnet in boundary_map.items():
            conn.execute(
                update(schema.pad_map)
                .where(schema.pad_map.c.bitstream == bs_id)
                .where(schema.pad_map.c.pin == pin)
                .values(net_out=bnet)
            )
        print(f"  IOLOGIC: {len(iologic_fanout)} fanout entries  "
              f"{len(boundary_nets)} pad boundary nets inserted")

        # ── input-pad H06E routing gap (known limitation) ────────────────────
        # Right-edge (col=21) ADC input pads drive their data onto the E3_H06E0003
        # horizontal bus via the JQ arc.  The H06E bus is a shared 6-hop wire — the
        # arc model records one JQ→H06E arc at the source tile but does NOT record
        # which CIB tiles downstream tap the bus for a specific net.  prjtrellis
        # models this correctly (the arc IS recorded); the gap is that we cannot
        # determine the downstream fanout without Diamond routing reports.
        #
        # A previous spatial heuristic (stitch JQ net → nearby d='1'b0' FFs) was
        # REMOVED because it produced false positives — d='1'b0' FFs near right-edge
        # pads are AWG EBR output registers (clk_h0_awg_wr), not ADC input registers.
        # V07 uses no IOLOGIC input mode on ADC pads; the bitstream config confirms
        # simple INPUT_LVTTL33 with no IOLOGICA.MODE setting.
        #
        # True ADC data path: JQ net → H06E bus → (interior CIB taps not modelled) →
        # LUT 0001000100011110 DDR deserialiser → fabric FFs.  Resolving this requires
        # either Diamond routing reports or a physical signal trace.  Filed in GH #76.
        nf = schema.net_fanout
        pm = schema.pad_map
        unstitched_count = conn.execute(
            select(func.count())
            .select_from(pm)
            .where(pm.c.bitstream == bs_id)
            .where(pm.c.direction.in_(["in", "bidir"]))
            .where(pm.c.net_in.isnot(None))
            .where(
                ~select(nf.c.id)
                .where(nf.c.bitstream == pm.c.bitstream)
                .where(nf.c.net == pm.c.net_in)
                .correlate(pm)
                .exists()
            )
        ).scalar()
        print(f"  Input-pad H06E gap: {unstitched_count} pads with no net_fanout (H06E routing not modelled)")

        # ── clock_domains ─────────────────────────────────────────────────────
        clk_ffs = [{"bitstream": bs_id, "clk_net": ff["clk"], "ff_cell": ff["name"]}
                   for ff in design.ffs
                   if ff["clk"] and not ff["clk"].startswith("1'b")]
        if not fuzz:
            assert_ge("clocked FFs", len(clk_ffs), 50)
        conn.execute(_insert_or_ignore(schema.clock_domains), clk_ffs)
        # Verify at least one clock domain
        n_doms = conn.execute(
            select(func.count(schema.clock_domains.c.clk_net.distinct()))
            .where(schema.clock_domains.c.bitstream == bs_id)
        ).scalar()
        if not fuzz:
            assert_ge("clock domains", n_doms, 1)
        print(f"  {n_doms} clock domains  {len(clk_ffs)} FF-clock entries")

        # ── arcs (raw routing arcs with globalised wire coords) ───────────────
        import re as _re
        _HPBX_SINK = _re.compile(r'^BRANCH_HPBX(\d{4})$')
        arc_rows  = []
        hpbx_rows = []  # dicts for hpbx_branches
        hpbx_seen = set()

        for (r, c, sink, src) in pc.arcs:
            ks = lift.gkey(r, c, sink)
            kd = lift.gkey(r, c, src)

            def _resolve(key):
                if key is None:
                    return None, None, None, None
                root = design.dsu.find(key)
                net  = design.net_name.get(root)
                gx, gy, gid = key
                return net, gx, gy, gid

            sink_net,   sx, sy, sid = _resolve(ks)
            source_net, dx, dy, did = _resolve(kd)

            arc_rows.append({
                "bitstream": bs_id,
                "tile_row": r, "tile_col": c,
                "sink_wire": str(sink), "source_wire": str(src),
                "sink_net": sink_net, "source_net": source_net,
                "sink_gx": sx, "sink_gy": sy, "sink_gid": sid,
                "source_gx": dx, "source_gy": dy, "source_gid": did,
            })

            # Capture HPBX spine taps: BRANCH_HPBXnnnn appearing as sink wire
            m = _HPBX_SINK.match(str(sink))
            if m and sink_net:
                key_hpbx = (r, c, str(sink))
                if key_hpbx not in hpbx_seen:
                    hpbx_seen.add(key_hpbx)
                    hpbx_rows.append({
                        "bitstream": bs_id,
                        "tile_row": r, "tile_col": c,
                        "track": str(sink), "local_net": sink_net,
                    })

        # Batch insert arcs in chunks
        CHUNK = 5000
        for i in range(0, len(arc_rows), CHUNK):
            conn.execute(insert(schema.arcs), arc_rows[i:i+CHUNK])

        if hpbx_rows:
            conn.execute(_insert_or_ignore(schema.hpbx_branches), hpbx_rows)

        print(f"  {len(arc_rows)} routing arcs  {len(hpbx_rows)} HPBX spine taps")

        # ── clock_domain_summary ──────────────────────────────────────────────
        # Aggregate FF counts per clock net and join with HPBX track assignments.
        # HPBX track for a clock net = the track whose BRANCH_HPBXn wire matches
        # the net observed flowing through U_VPTX/G_VPTX → BRANCH_HPBXn arcs.
        # Strategy: any arc where source_wire contains 'VPTX' and sink_wire is
        # BRANCH_HPBXn links the source_net (the HPBX global spine) to the track.
        # We collect (track → {local_nets}) from hpbx_branches, then for each
        # clock domain find which track its net belongs to.
        _VPTX_SRC = _re.compile(r'[UG]_VPTX\d{4}')

        # Build track membership: local_net → track
        net_to_track = {}
        for row_d in hpbx_rows:
            net_to_track.setdefault(row_d["local_net"], row_d["track"])

        # Also capture G_VPTX → BRANCH_HPBX arcs where the SOURCE is VPTX
        # (meaning the source net is the HPBX spine driving the branch)
        for (r, c, sink, src) in pc.arcs:
            if _VPTX_SRC.match(str(src)) and _HPBX_SINK.match(str(sink)):
                ks = lift.gkey(r, c, sink)
                if ks:
                    root = design.dsu.find(ks)
                    net  = design.net_name.get(root)
                    if net:
                        net_to_track.setdefault(net, str(sink))

        from collections import Counter
        clk_counts = Counter(ff["clk"] for ff in design.ffs
                             if ff.get("clk") and not ff["clk"].startswith("1'b"))

        cds_rows = []
        for clk_net, ff_count in clk_counts.items():
            track = net_to_track.get(clk_net)
            cds_rows.append({
                "bitstream": bs_id, "clk_net": clk_net,
                "ff_count": ff_count, "hpbx_track": track,
            })

        conn.execute(_insert_or_ignore(schema.clock_domain_summary), cds_rows)
        print(f"  {len(cds_rows)} clock domain summary rows  "
              f"({sum(1 for r in cds_rows if r['hpbx_track'])} with HPBX track assigned)")

    print(f"\nOK — bitstream {label!r} loaded as id={bs_id}  ({time.time()-t0:.1f}s)")
    return bs_id


def dump_pins(config_path, annotations_path, out_path, device):
    """Scan bitstream + iomap → write a TSV template with correct coordinates.

    Merges pin_annotations.json (by pin number) so signal/chip/note data is
    preserved.  The output is in hantek2d82-pins.tsv column format so it can
    be diffed directly against the existing file.

    Columns:
      pin  row  col  pio  dir  label  function  confidence
      # extra (tab-separated after confidence):
      chip_ref  chip_pin  chip_signal  net_in  net_out  note
    """
    import json

    print(f"Recovering netlist from {config_path}…")
    lift   = mx.MachXO2Lift(device)
    pc     = lift.parse_config(config_path)
    design = lift.recover_netlist(pc)
    max_row = lift.chip.get_max_row()

    # Parse iomap — pin# -> (row, col, pio, dir)
    iomap_path = str(config_path) + ".iomap.tsv"
    if not os.path.exists(iomap_path):
        die(f"iomap not found: {iomap_path}")
    iomap = {}  # pin# -> (row, col, pio, dir)
    with open(iomap_path) as fh:
        fh.readline()
        for line in fh:
            parts = line.strip().split("\t")
            if len(parts) < 5: continue
            pin_s, bank, func, site, dir_s = parts[0], parts[1], parts[2], parts[3], parts[4]
            m = re.match(r"R(\d+)C(\d+):PIO(\w)", site)
            if m:
                iomap[int(pin_s)] = (int(m.group(1)), int(m.group(2)), m.group(3), dir_s)
    print(f"  iomap: {len(iomap)} configured pins")

    # Load annotations
    ann = {}  # pin# -> dict
    if annotations_path and os.path.exists(annotations_path):
        raw = json.load(open(annotations_path))
        for k, v in raw.get("pins", {}).items():
            try: ann[int(k)] = v
            except ValueError: pass
        print(f"  annotations: {len(ann)} pins from {os.path.basename(annotations_path)}")

    # Resolve nets for each iomap pin
    rows = []
    for pin in sorted(iomap):
        row, col, pio, dir_bs = iomap[pin]
        a = ann.get(pin, {})

        if dir_bs == "in":
            ni = mx.pad_net(design, lift, row, col, pio, "in")
            no = None
            direction = "in"
        elif dir_bs == "out":
            ni = None
            no = mx.pad_net(design, lift, row, col, pio, "out")
            direction = "out"
        else:  # inout / bidir
            ni = mx.pad_net(design, lift, row, col, pio, "in")
            no = mx.pad_net(design, lift, row, col, pio, "out")
            direction = "bidir"

        signal    = a.get("signal", "")
        chip_ref  = a.get("chip_ref", "")
        chip_pin  = a.get("chip_pin", "")
        chip_sig  = a.get("chip_signal", "")
        note      = a.get("note", "")
        conf_str  = a.get("confidence", "")
        # map confidence string -> integer
        conf_int  = {"confirmed": 10, "inferred": 8, "estimate": 5,
                     "guess": 3}.get(conf_str, 3)

        label    = signal or f"pin{pin}"
        function = note[:80].replace("\t", " ") if note else ""

        rows.append((pin, row, col, pio, direction, label, function, conf_int,
                     chip_ref, chip_pin, chip_sig,
                     ni or "", no or "", note.replace("\t", " ")))

    # Write TSV
    header = (
        "# Pluribus pin annotation file — Hantek 2D82AUTO / LCMXO2-1200HC-4TG100C TQFP100\n"
        "#\n"
        "# DEVICE METADATA — parsed by load.py\n"
        "# device:   LCMXO2-1200\n"
        "# package:  TQFP100\n"
        "#\n"
        "# Generated by: load.py --dump-pins\n"
        "# Source: bitstream iomap (coordinates) + pin_annotations.json (names)\n"
        "#\n"
        "# COLUMN FORMAT\n"
        "# pin  row  col  pio  dir  label  function  confidence"
        "  chip_ref  chip_pin  chip_signal  net_in  net_out  note\n"
        "# confidence: 3=guess  5=estimate  8=inferred  10=confirmed\n"
        "#\n"
    )
    with open(out_path, "w") as fh:
        fh.write(header)
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    print(f"\nWrote {len(rows)} pins → {out_path}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--label",     help="bitstream label e.g. V07")
    ap.add_argument("--config",    required=True, help="path to .bin.config file")
    ap.add_argument("--pins",      help="path to pins TSV annotation file")
    ap.add_argument("--nets",      help="path to fpga_nets.tsv net annotation file (optional)")
    ap.add_argument("--device",    default="LCMXO2-1200")
    ap.add_argument("--package",   default="TQFP100")
    ap.add_argument("--dump-pins", metavar="OUT_TSV",
                    help="scan bitstream+iomap, merge pin_annotations.json, write template TSV and exit")
    ap.add_argument("--annotations", default=None,
                    help="path to pin_annotations.json (used with --dump-pins)")
    ap.add_argument("--fuzz", action="store_true",
                    help="fuzz mode: skip FF/LUT/net count sanity checks (designs have very few cells)")
    args = ap.parse_args()

    if args.dump_pins:
        dump_pins(args.config, args.annotations, args.dump_pins, args.device)
        return

    if not args.label:
        ap.error("--label is required when not using --dump-pins")
    if not args.pins:
        ap.error("--pins is required when not using --dump-pins")
    load(args.label, args.config, args.pins, args.device, args.package, args.nets,
         fuzz=args.fuzz)


if __name__ == "__main__":
    main()
