#!/usr/bin/env python3
"""Recover GOWIN BSRAM primitive ports that the .gwconfig decode drops.

RUNS UNDER THE OSS-CAD-SUITE PYTHON (apycula), NOT python3.15t — same
constraint as scripts/gowin_unpack.py.

WHY THIS EXISTS (the gap it works around)
-----------------------------------------
`scripts/gowin_unpack.py` emits a `hardip` record per hard-IP bel and fills its
ports from the STATIC tile database:

    portmap = dict(db[row, col].bels[name].portmap)

For BSRAM that lookup fails.  apycula's `parse_tile_()` returns the *placed
instance* name (``BSRAM0`` / ``BSRAM1`` / …), but the static tile db keys the
site as plain ``BSRAM``.  ``db[r, c].bels["BSRAM0"]`` therefore raises KeyError,
the surrounding ``try/except`` swallows it, and the BSRAM record is emitted with
ZERO ports:

    hardip 9 1 BSRAM bel=BSRAM0        <- no CLKA/CEA/WREA/… at all

So every BSRAM control and data port (210 of them per block) is missing from the
pluribus netlist: `ebr_ports` / `ebr_buses` stay empty for the gowin family and
the report prints "0 EBR blocks".  The ports are NOT buses — they are scalar
per-bit entries (CEA, WREA, ADA0..ADA13, DIA0..DIA17, DOB0..DOB17, …), so
nothing about them is intrinsically hard to model; only the name lookup is wrong.

This tool reads the correct ``BSRAM`` site bel and resolves every port wire to
the SAME canonical global node name `gowin_unpack.py` uses (identical alias /
node-stitching path), writing a JSON sidecar that DB-side analysis can join
against `arcs.sink_wire` / `arcs.source_wire`.

It deliberately does NOT modify the core lifter or unpacker — it is an external
bridge, so the recovered ports can be used for analysis while the underlying
decode gap is tracked separately.

Usage:
    gowin_bsram_ports.py --device GW1N-2 --out bsram_ports.json
"""

import argparse
import importlib.util
import json
import os
import sys


def load_unpack_helpers():
    """Import build_alias_map / make_canon from scripts/gowin_unpack.py.

    Its module-level imports are light (argparse/re/sys) — apycula is only
    imported inside unpack() — so this is safe to load here.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "gowin_unpack.py")
    spec = importlib.util.spec_from_file_location("gowin_unpack_helpers", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def recover(device):
    import importlib.resources as ir
    from apycula.chipdb import load_chipdb, wire2global

    gu = load_unpack_helpers()
    db = load_chipdb(str(ir.files("apycula").joinpath(f"{device}.msgpack.xz")))
    aliases = gu.build_alias_map(db, wire2global)
    canon = gu.make_canon(db, wire2global, aliases)

    blocks = []
    for r in range(db.rows):
        for c in range(db.cols):
            for belname, bel in db[r, c].bels.items():
                # the sample-memory site is plain "BSRAM"; skip the AUX tiles
                # (they carry no independent portmap of their own)
                if belname != "BSRAM":
                    continue
                pm = dict(getattr(bel, "portmap", {}) or {})
                ports = {}
                for port, wire in pm.items():
                    wires = wire if isinstance(wire, (list, tuple)) else [wire]
                    ports[port] = [canon(r, c, w) for w in wires]
                blocks.append({
                    "bel": belname, "row": r, "col": c,
                    "tile": f"R{r + 1}C{c + 1}", "ports": ports,
                })
    return blocks


CONTROL_A = ("CLKA", "CEA", "WREA", "OCEA", "RESETA")
CONTROL_B = ("CLKB", "CEB", "WREB", "OCEB", "RESETB")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-d", "--device", default="GW1N-2",
                    help="apycula device name (default GW1N-2)")
    ap.add_argument("-o", "--out", required=True, help="output JSON sidecar")
    args = ap.parse_args()

    blocks = recover(args.device)
    with open(args.out, "w") as fh:
        json.dump(blocks, fh, indent=1)
    print(f"[gowin_bsram_ports] {args.device}: {len(blocks)} BSRAM site(s) "
          f"-> {args.out}")
    for b in sorted(blocks, key=lambda x: (x["row"], x["col"])):
        n = sum(len(v) for v in b["ports"].values())
        print(f"  {b['tile']:8} {n:3} port wires  "
              f"A-side: {[p for p in CONTROL_A if p in b['ports']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
