#!/usr/bin/env python3.15t
"""Single data layer for the geo explorer (scripts/geo_explorer.py): tiles + pins + package grid + image layer -> ONE payload.

  python3.15t scripts/geo_data.py                       # build + check, print the summary
  python3.15t scripts/geo_data.py --export tmp/geo/data # also write payload.json + one JSON file per layer
  python3.15t scripts/geo_data.py --geojson             # also write tmp/geo/die.geojson
Sources (read-only): tmp/geo/tiles.json (scripts/geo_tiles.py), table device_pins of the SQLite DB (scripts/pins_register.py),
optional tmp/geo/image_overlay_data.json (scripts/geo_image_overlay.py).  Schema: docs/geo-data.md.
"""
import argparse
import json
import os
import re
import sqlite3
import string
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import geo_devices  # noqa: E402
from geo_devices import common  # noqa: E402

GEO = REPO / "tmp/geo"
SCHEMA = 2
FAMILY, DEVICE, PACKAGE = "cycloneiv", "EP4CGX150", "DF31"
SPECIALS = ["none", "config", "jtag", "clock", "transceiver", "reference", "power", "ground", "nc"]
# Role = DB `special`, except a ball whose only vendor name is NC/DNU -> "nc" (the DB has no NC special).
# Die site expected = a role that is a pad on the die: user I/O, clock, reference, config, JTAG, transceiver.
# Not expected = power / ground / nc: package-only supply or unconnected balls with no I/O cell.
NO_SITE_ROLES = ("power", "ground", "nc")
PIN_COLS = ["ball", "pad", "bank", "side", "x", "y", "z", "site", "type", "names", "ibis", "role", "bonded", "usage",
            "src", "conflicts", "expected", "tile", "pair", "cell"]


def diff_pairs(rows):
    """Differential partners: vendor names ending p/n after a digit or '_', same base, both present -> {i: j, j: i}."""
    pb = {}
    for i, r in enumerate(rows):
        for f in r[9]:
            m = re.fullmatch(r"(.*[0-9_])([pPnN])", f)
            if m and len(m.group(1)) >= 3:
                pb.setdefault(m.group(1).upper(), {})[m.group(2).upper()] = i
    pair = {}
    for o in pb.values():
        if "P" in o and "N" in o and o["P"] != o["N"]:
            pair[o["P"]], pair[o["N"]] = o["N"], o["P"]
    return pair


def build(device=None, package=None, path=None, image=True, family=FAMILY, opts=None):
    ad = geo_devices.adapter(family)
    device, package = device or ad.DEFAULT_DEVICE, package or ad.DEFAULT_PACKAGE
    tiles = ad.tiles(opts)
    design = tiles.pop("_design", None)
    pins = ad.pins(ad.db_path(path), device, package, SPECIALS, NO_SITE_ROLES, PIN_COLS)
    rows, ny = pins["rows"], tiles["ny"]
    pair = ad.pairs(rows) if hasattr(ad, "pairs") else diff_pairs(rows)
    pk, grid, cell = ad.package(rows, f"{device} {package} package ({len(rows)} balls)")
    pk["name"] = package
    tile_pins = {}
    for i, r in enumerate(rows):
        t = r[4] * ny + r[5] if r[4] is not None else -1
        if t >= 0 and not (0 <= r[4] < tiles["nx"] and 0 <= r[5] < ny):
            raise SystemExit(f"geo_data: pin {r[0]} site X{r[4]} Y{r[5]} is outside the die")
        r += [t, pair.get(i, -1), cell[r[0]]]
        if t >= 0:
            tile_pins.setdefault(t, []).append(i)
    for a in tile_pins.values():
        a.sort(key=lambda i: (rows[i][6], rows[i][0]))
    pins["geo"] = common.geo_positions(pk, grid, rows, tiles["nx"], ny)
    if opts and opts.get("board"):
        board, bsrc = common.load_board(opts["board"], package)
        if board:
            pins["board"] = [board.get(r[0]) for r in rows]
            pins["board_source"] = bsrc
    pat = common.pattern(pk, grid, rows, tiles["nx"], ny, tile_pins)
    ui = dict(ad.UI)
    if ui.get("tier_class") is None:
        ui["tier_class"] = ad.tier_class(tiles)
    pl = dict(schema=SCHEMA, family=family, device=device, package=pk, geom=ad.GEOM,
              tiles=tiles, pins=pins, grid=grid, xref=dict(tile_pins={str(k): v for k, v in sorted(tile_pins.items())}),
              image=ad.image(tiles) if image and hasattr(ad, "image") else None, ui=ui, pattern=pat)
    if design:
        pl["design"] = design
    return pl


def check(payload, path=None):
    """Counts in the payload must equal an independent DB query (the page headline numbers)."""
    ad = geo_devices.adapter(payload["family"])
    p = payload["pins"]["rows"]
    where, args = ad.pin_where(payload["device"], payload["package"]["name"])
    con = sqlite3.connect(f"file:{ad.db_path(path)}?mode=ro", uri=True)
    tot, site = con.execute(f"select count(*), sum(tile_x is not null) from device_pins where {where}", args).fetchone()
    con.close()
    assert tot == len(p) and site == sum(r[4] is not None for r in p), "payload counts differ from the DB"
    assert sum(len(v) for v in payload["xref"]["tile_pins"].values()) == site
    return counts(payload)


def counts(payload):
    p = payload["pins"]["rows"]
    site = sum(r[4] is not None for r in p)
    nex = sum(r[4] is None and not r[16] for r in p)
    return dict(balls=len(p), site=site, yet=len(p) - site - nex, expected_none=nex)


def dump(payload):
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def export(payload, out):
    out.mkdir(parents=True, exist_ok=True)
    (out / "payload.json").write_text(dump(payload))
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            (out / f"{k}.json").write_text(json.dumps(v, separators=(",", ":"), ensure_ascii=False))


def geojson(payload, out):
    t = payload["tiles"]
    ny = t["ny"]
    feats = []
    for i in range(t["nx"] * ny):
        x, y = divmod(i, ny)
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]]},
                      "properties": dict(x=x, y=y, kind=t["kinds"][t["kind"][i]], tier=t["tiers"][t["tier"][i]], cells=t["cells"][i], ver=t["ver"][i],
                                         set=t["set"][i], edge=t["flag"][i] & 1)})
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db")
    ap.add_argument("--family", default=FAMILY, choices=geo_devices.FAMILIES)
    ap.add_argument("--device", default=None, help="default: the family's default device")
    ap.add_argument("--package", default=None)
    ap.add_argument("--board", default=None, help="boards/<name>: design-layer config and board pin names")
    ap.add_argument("--design", default=None, help="Trellis .config for the design layer (default: board, else corpus example)")
    ap.add_argument("--no-image", action="store_true", help="leave the image layer out")
    ap.add_argument("--export", metavar="DIR")
    ap.add_argument("--geojson", action="store_true")
    a = ap.parse_args()
    pl = build(a.device, a.package, a.db, not a.no_image, a.family, dict(board=a.board, design=a.design))
    c = check(pl, a.db)
    sizes = {k: len(json.dumps(v, separators=(",", ":"))) for k, v in pl.items() if isinstance(v, (dict, list))}
    print(f"{pl['device']} {pl['package']['name']}: {c}; image layer {'present' if pl['image'] else 'absent'}; "
          f"{len(dump(pl)) / 1e6:.2f} MB JSON " + " ".join(f"{k}={v / 1e3:.0f}kB" for k, v in sizes.items()))
    if a.export:
        export(pl, Path(a.export))
    if a.geojson:
        GEO.mkdir(parents=True, exist_ok=True)
        geojson(pl, GEO / "die.geojson")


if __name__ == "__main__":
    main()
