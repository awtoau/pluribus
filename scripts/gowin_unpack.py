#!/usr/bin/env python3
"""Unpack a GOWIN `.fs` bitstream into a normalized text `.gwconfig`.

RUNS UNDER THE OSS-CAD-SUITE PYTHON (apicula / apycula), NOT python3.15t.

pluribus itself runs free-threaded under python3.15t, but Project Apicula
(apycula) only imports under the oss-cad-suite interpreter (pure-Python
msgpack/CRC fallbacks + the packaged chip databases).  So the GOWIN decode is
a subprocess: this script decodes the bitstream with apycula and emits a
family-neutral text config that the pure-Python 3.15t lifter
(lifters/gowin_lift.py) reads back — apycula is never imported into the
pluribus interpreter.

The decode mirrors `apycula/gowin_unpack.py:main()` exactly:
  * read_bitstream + tile_bitmap
  * parse_tile_(db, r, c, tile, bm, noiostd=False) per tile
  * removeLUTs(bels) + ram16_remove_bels(bels) (the default, non-noalu path)
  * cross-tile net stitching from db.nodes + the SN/EW wire aliases

Every wire is canonicalised to a GLOBAL node name (R{r+1}C{c+1}_{wire} space,
resolved through the Himbaechel node aliases) so the lifter's union-find only
has to union the routing arcs — the hardwired node stitching is already baked
into the names.  This is the same aliasing apycula applies before it writes
its reference Verilog, so the emitted node names match `gowin_unpack -o`.

Output sections (one record per line, '-' for an absent field):
  .device <name>
  .tile   <row0> <col0> <ttyp>
  arc     <row0> <col0> <dst_node> <src_node>
  lut     <row0> <col0> <bel> <init16> A=<node> B=<node> C=<node> D=<node> F=<node>
  dff     <row0> <col0> <bel> <dtype> Q=<node> D=<node> CLK=<node> CE=<node> SR=<node>
  iob     <row0> <col0> <bel> <mode>  I=<node> O=<node> OE=<node> pin=<name>
  hardip  <row0> <col0> <type> <port>=<node> ...   (ALU / MUX / BSRAM / PLL / OSC / ...)

Rows/cols are 0-based (apycula's internal db grid); the R{r+1}C{c+1} names
inside node strings are 1-based (apycula's floorplan convention).

INIT bit-order (verified — see lifters/gowin_lift.py and tests/test_gowin_lift.py):
  apycula stores a LUT4 as the set of INIT bit positions whose fuse is SET,
  which are the ZERO bits of INIT, so INIT = 0xFFFF - sum(1<<f).  The pins are
  I0=A I1=B I2=C I3=D with truth-table address = A + 2B + 4C + 8D, and
  INIT[address] = f(inputs).  That is byte-for-byte the pluribus MSB-first
  convention (`v = int(init_str, 2)`, bit p = f(p)), so init16 = f"{val:016b}"
  needs NO reversal or pin permutation.  Confirmed against blinky-ref.v
  (R10C4 INIT 0x5555, R10C8 INIT 0xEEEE) and against a synthesised known
  function.

Refuses to overwrite an existing output.

Usage: gowin_unpack.py BITSTREAM.fs [OUT.gwconfig] --device GW1N-1
"""

import argparse
import re
import sys


def build_alias_map(db, wire2global):
    """Reproduce apycula main()'s mod.wire_aliases: every Himbaechel node's
    member wires alias to the node's shortest-named wire, plus the SN/EW
    segment aliases.  Returns a flat {name: parent} dict resolved lazily."""
    aliases = {}

    def by_name_len(el):
        return len(el[2])

    for node_desc in db.nodes.values():
        root = None
        for row, col, wire in sorted(node_desc[1], key=by_name_len):
            wname = f"R{row + 1}C{col + 1}_{wire}"
            if root is None:
                root = wname
                continue
            aliases[wname] = root

    for row in range(db.rows):
        for col in range(db.cols):
            for i in (1, 2):
                aliases[wire2global(row + 0, col + 1, db, f"N1{i}1")] = \
                    f"R{row + 1}C{col + 1}_SN{i}0"
                aliases[wire2global(row + 2, col + 1, db, f"S1{i}1")] = \
                    f"R{row + 1}C{col + 1}_SN{i}0"
                aliases[wire2global(row + 1, col + 0, db, f"W1{i}1")] = \
                    f"R{row + 1}C{col + 1}_EW{i}0"
                aliases[wire2global(row + 1, col + 2, db, f"E1{i}1")] = \
                    f"R{row + 1}C{col + 1}_EW{i}0"
    return aliases


def make_canon(db, wire2global, aliases):
    """A resolver: (row0, col0, local_wire) -> canonical global node name."""
    def resolve(name):
        seen = set()
        while name in aliases and name not in seen:
            seen.add(name)
            name = aliases[name]
        return name

    def canon(row0, col0, wire):
        return resolve(wire2global(row0 + 1, col0 + 1, db, wire))

    return canon


# apycula dff/latch kinds whose LSR{idx//2} wire carries an async
# set/reset/preset/clear input (the plain DFF/DFFN and DL/DLN have none).
_KINDS_WITH_LSR = {
    "DFFS", "DFFR", "DFFP", "DFFC", "DFFNS", "DFFNR", "DFFNP", "DFFNC",
    "DLC", "DLNC", "DLP", "DLNP",
}
_LATCH_KINDS = {"DL", "DLN", "DLC", "DLNC", "DLP", "DLNP"}


def unpack(bitstream, device):
    """Decode BITSTREAM for DEVICE, return (lines, counts)."""
    import importlib.resources as ir
    from apycula.chipdb import load_chipdb, tile_bitmap, wire2global
    from apycula.bslib import read_bitstream
    from apycula import gowin_unpack as gu

    gu._device = device
    dbpath = str(ir.files("apycula").joinpath(f"{device}.msgpack.xz"))
    db = load_chipdb(dbpath)

    aliases = build_alias_map(db, wire2global)
    canon = make_canon(db, wire2global, aliases)

    def C(r, c, w):
        # '-' for a wire the bel does not connect
        if w is None:
            return "-"
        return canon(r, c, w)

    bitmap, _hdr, _ftr, _extra = read_bitstream(bitstream)
    bm = tile_bitmap(db, bitmap)

    lines = [f".device {device}"]
    counts = {
        "tiles": 0, "arcs": 0, "luts": 0, "luts_const": 0,
        "dff": {}, "alu": 0, "iob": {}, "hardip": {},
        "latch": 0, "skipped_bels": 0,
    }

    # Process bank tiles first (as apycula main() does — banks establish IO
    # standards), then the rest; both with noiostd=False so IO modes decode.
    bank_positions = set(db.bank_tiles.values())
    ordered = sorted(bm.items(), key=lambda kv: (kv[0] not in bank_positions,
                                                 kv[0]))

    for (row, col), tile in ordered:
        try:
            bels, pips, clock_pips = gu.parse_tile_(
                db, row, col, tile, bm, noiostd=False)
        except Exception as e:                       # pragma: no cover
            print(f"[gowin_unpack] WARN tile ({row},{col}) parse failed: {e}",
                  file=sys.stderr)
            continue
        gu.removeLUTs(bels)
        gu.ram16_remove_bels(bels)

        ttyp = db[row, col].ttyp
        lines.append(f".tile {row} {col} {ttyp}")     # ttyp emitted as string
        counts["tiles"] += 1

        # ---- routing arcs (pips + clock pips) ----
        for dest, src in list(pips.items()) + list(clock_pips.items()):
            lines.append(f"arc {row} {col} {C(row, col, dest)} "
                         f"{C(row, col, src)}")
            counts["arcs"] += 1

        # ---- bels ----
        for name, flags in bels.items():
            flags = set(flags)

            if name.startswith("LUT"):
                idx = name[3:]
                zeros = sorted(f for f in flags if isinstance(f, int))
                val = 0xFFFF - sum(1 << f for f in zeros)
                init16 = f"{val:016b}"
                if val in (0x0000, 0xFFFF):
                    counts["luts_const"] += 1
                    # constant LUT: emit so its F node resolves to the literal
                    lines.append(
                        f"lut {row} {col} {name} {init16} "
                        f"A=- B=- C=- D=- F={C(row, col, f'F{idx}')}")
                    continue
                lines.append(
                    f"lut {row} {col} {name} {init16} "
                    f"A={C(row, col, f'A{idx}')} B={C(row, col, f'B{idx}')} "
                    f"C={C(row, col, f'C{idx}')} D={C(row, col, f'D{idx}')} "
                    f"F={C(row, col, f'F{idx}')}")
                counts["luts"] += 1

            elif name.startswith("DFF"):
                idx = int(name[3])
                sd = "SD" in flags
                flags.discard("SD")
                kind = next((f for f in flags if isinstance(f, str)), None)
                if kind is None or kind == "RAM":
                    counts["skipped_bels"] += 1
                    continue
                if kind in _LATCH_KINDS:
                    counts["latch"] += 1
                    # latch: gate is CLK; represent like a dff for now
                d_wire = f"SEL{idx}" if sd else f"F{idx}"
                sr = C(row, col, f"LSR{idx // 2}") if kind in _KINDS_WITH_LSR else "-"
                lines.append(
                    f"dff {row} {col} {name} {kind} "
                    f"Q={C(row, col, f'Q{idx}')} D={C(row, col, d_wire)} "
                    f"CLK={C(row, col, f'CLK{idx // 2}')} "
                    f"CE={C(row, col, f'CE{idx // 2}')} SR={sr}")
                counts["dff"][kind] = counts["dff"].get(kind, 0) + 1

            elif name.startswith("ALU"):
                idx = name[3:]
                mode = next(iter(flags)) if flags else "?"
                # COUT/SUM both land on F{idx}; that is the node a paired DFF
                # reads as its D input.  Emit inputs + the F output node.
                lines.append(
                    f"hardip {row} {col} ALU idx={idx} mode={mode} "
                    f"F={C(row, col, f'F{idx}')} CIN={C(row, col, f'CIN{idx}')} "
                    f"A={C(row, col, f'A{idx}')} B={C(row, col, f'B{idx}')} "
                    f"C={C(row, col, f'C{idx}')} D={C(row, col, f'D{idx}')}")
                counts["alu"] += 1

            elif name.startswith("IOB"):
                idx = name[-1]
                kinds = flags & {"IBUF", "OBUF", "IOBUF", "TBUF",
                                 "TLVDS_IBUF", "TLVDS_OBUF", "TLVDS_IOBUF",
                                 "TLVDS_TBUF", "ELVDS_IBUF", "ELVDS_OBUF",
                                 "ELVDS_IOBUF", "ELVDS_TBUF", "MIPI_IBUF",
                                 "MIPI_OBUF", "I3C_IOBUF"}
                if not kinds:
                    counts["skipped_bels"] += 1
                    continue
                mode = sorted(kinds)[0]
                try:
                    portmap = dict(db[row, col].bels[name].portmap)
                except Exception:
                    portmap = {}
                i_net = C(row, col, portmap["I"]) if "I" in portmap else "-"
                o_net = C(row, col, portmap["O"]) if "O" in portmap else "-"
                oe_net = C(row, col, portmap["OE"]) if "OE" in portmap else "-"
                try:
                    from apycula import chipdb as _cdb
                    pin = f"{_cdb.loc2pin_name(db, row, col)}{idx}"
                except Exception:
                    pin = f"R{row + 1}C{col + 1}{idx}"
                lines.append(
                    f"iob {row} {col} {name} {mode} "
                    f"I={i_net} O={o_net} OE={oe_net} pin={pin}")
                counts["iob"][mode] = counts["iob"].get(mode, 0) + 1

            else:
                # Generic hard IP: BSRAM / RPLL / PLLVR / OSC* / DSP / BANK /
                # CFG / RAM16 / IOLOGIC / ...  Preserve the bel + its portmap
                # nets so downstream work can model them; not logic-modelled yet.
                htype = re.match(r"[A-Za-z_]+", name).group(0)
                ports = []
                try:
                    portmap = dict(db[row, col].bels[name].portmap)
                except Exception:
                    portmap = {}
                for port, wire in portmap.items():
                    if isinstance(wire, (list, tuple)):
                        continue
                    ports.append(f"{port}={C(row, col, wire)}")
                lines.append(
                    f"hardip {row} {col} {htype} bel={name} "
                    + " ".join(ports))
                counts["hardip"][htype] = counts["hardip"].get(htype, 0) + 1

    return lines, counts


def print_summary(counts):
    print("\n[gowin_unpack] === recovery summary ===")
    print(f"  tiles configured : {counts['tiles']}")
    print(f"  routing arcs     : {counts['arcs']}")
    print(f"  LUT4 (logic)     : {counts['luts']}   "
          f"(constant LUTs: {counts['luts_const']})")
    ndff = sum(counts["dff"].values())
    print(f"  DFF              : {ndff}   {dict(sorted(counts['dff'].items()))}")
    print(f"  ALU (deferred)   : {counts['alu']}")
    niob = sum(counts["iob"].values())
    print(f"  IOB              : {niob}   {dict(sorted(counts['iob'].items()))}")
    if counts["hardip"]:
        print(f"  hard IP          : {dict(sorted(counts['hardip'].items()))}")
    if counts["latch"]:
        print(f"  latches          : {counts['latch']}")
    if counts["skipped_bels"]:
        print(f"  skipped bels     : {counts['skipped_bels']}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bitstream", help="input GOWIN bitstream (.fs)")
    ap.add_argument("out", nargs="?", help="output .gwconfig (default BITSTREAM.gwconfig)")
    ap.add_argument("-d", "--device", default="GW1N-1",
                    help="apycula device name (default GW1N-1)")
    args = ap.parse_args()

    import os
    out_path = args.out if args.out else args.bitstream + ".gwconfig"
    if os.path.exists(out_path):
        print(f"[gowin_unpack] REFUSING to overwrite existing {out_path}\n"
              "         delete it first or pass a different OUT.gwconfig",
              file=sys.stderr)
        return 1

    print(f"[gowin_unpack] decode: {args.bitstream}  device={args.device}")
    lines, counts = unpack(args.bitstream, args.device)
    with open(out_path, "w") as fh:
        fh.write("# pluribus GOWIN gwconfig — decoded by scripts/gowin_unpack.py\n")
        fh.write(f"# device {args.device}\n")
        fh.write("\n".join(lines))
        fh.write("\n")
    print(f"[gowin_unpack] wrote {out_path} ({len(lines)} records)")
    print_summary(counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
