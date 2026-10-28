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
GEO = REPO / "tmp/geo"
SCHEMA = 1
DEVICE, PACKAGE = "EP4CGX150", "DF31"
KINDS = ["LAB", "M9K", "MUL", "IOL", "IOR", "IOROW"]
TIERS = ["verified", "evidence", "unknown"]
SPECIALS = ["none", "config", "jtag", "clock", "transceiver", "reference", "power", "ground", "nc"]
# Role = DB `special`, except a ball whose only vendor name is NC/DNU -> "nc" (the DB has no NC special).
# Die site expected = a role that is a pad on the die: user I/O, clock, reference, config, JTAG, transceiver.
# Not expected = power / ground / nc: package-only supply or unconnected balls with no I/O cell.
NO_SITE_ROLES = ("power", "ground", "nc")
NC_NAMES = {"NC", "DNU"}
TILE_FLAGS = ("edge", "spec", "leout")                       # bit 0, 1, 2 of the packed `flag` column
PIN_COLS = ["ball", "pad", "bank", "side", "x", "y", "z", "site", "type", "names", "ibis", "role", "bonded", "usage",
            "src", "conflicts", "expected", "tile", "pair", "cell"]
IMG_COLS = ["cells", "set", "sv", "se", "su", "so", "capv", "cape", "s2a", "fa", "w", "tmpl"]
VPITCH, VBAND_LO = 70, 48                                    # tile row band = v in [70 y - 48, 70 y + 21]


def db_path(path=None):
    return path or os.environ.get("PLURIBUS_SQLITE_PATH") or str(REPO / "databases/cycloneiv/gx150.db")


def role_of(special, funcs):
    names = {f.upper() for f in funcs}
    if names and names <= NC_NAMES:
        return "nc"
    return special or "none"


# ---------------------------------------------------------------------------------------------
# layers
# ---------------------------------------------------------------------------------------------
def load_tiles():
    """Columnar tile table.  Tile index i = x * ny + y (all nx*ny tiles present, checked)."""
    p = GEO / "tiles.json"
    if not p.exists():
        raise SystemExit(f"geo_data: {p.name} missing; run scripts/geo_tiles.py --image <image> first")
    d = json.loads(p.read_text())
    nx, ny = d["xmax"] + 1, d["ymax"] + 1
    rows = sorted(d["tiles"], key=lambda t: (t["x"], t["y"]))
    if len(rows) != nx * ny or any(t["x"] * ny + t["y"] != i for i, t in enumerate(rows)):
        raise SystemExit("geo_data: tile table is not a complete nx*ny grid")
    cols = {"kind": [KINDS.index(t["kind"]) for t in rows], "tier": [TIERS.index(t["tier"]) for t in rows]}
    for k in ("cells", "ver", "set"):
        cols[k] = [t[k] for t in rows]
    cols["flag"] = [sum(int(bool(t[f])) << b for b, f in enumerate(TILE_FLAGS)) for t in rows]
    return dict(die=d["die"], nx=nx, ny=ny, kinds=KINDS, tiers=TIERS, flags=list(TILE_FLAGS), **cols)


def load_pins(path, device):
    """-> pin layer (row list + deduplicated per-field source dicts).  Row layout = PIN_COLS; tile/pair/cell filled by build()."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    q = ("select pin,pad_number,bank,side,tile_x,tile_y,z,io_site,io_type,func_names,ibis_net,special,bonded,usage_default,source,conflicts "
         "from device_pins where device=? order by pin")
    rows, srcs, sidx = [], [], {}
    for (pin, pad, bank, side, x, y, z, site, ty, fn, ibis, sp, bonded, usage, src, conf) in con.execute(q, (device,)):
        if src not in sidx:
            sidx[src] = len(srcs)
            srcs.append(json.loads(src))
        funcs = (json.loads(fn) if fn else None) or []
        role = role_of(sp, funcs)
        rows.append([pin, pad, bank or "", side or "", x, y, z, site or "", ty or "", funcs, ibis or "",
                     SPECIALS.index(role), 1 if bonded else 0, usage or "", sidx[src], (json.loads(conf) if conf else None) or [],
                     0 if role in NO_SITE_ROLES else 1])
    con.close()
    if not rows:
        raise SystemExit(f"geo_data: no device_pins rows for {device}")
    return dict(device=device, cols=PIN_COLS, roles=SPECIALS, rows=rows, src=srcs)


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


def package_grid(rows, label):
    """Matrix of the BGA from ball names (letters+digits).  Returns (grid dict, ball -> matrix cell index)."""
    balls = {}
    for r in rows:
        m = re.fullmatch(r"([A-Z]+)(\d+)", r[0])
        if not m:
            raise SystemExit(f"geo_data: ball name {r[0]!r} is not letters+digits")
        balls[r[0]] = (m.group(1), int(m.group(2)))
    letters = sorted({b[0] for b in balls.values()}, key=lambda s: (len(s), s))
    ncol = max(b[1] for b in balls.values())
    singles = [c for c in string.ascii_uppercase if c not in letters]
    dbl = sorted(l[1] for l in letters if len(l) == 2)
    dbl_missing = [c for c in string.ascii_uppercase[: string.ascii_uppercase.index(dbl[-1]) + 1] if c not in dbl]
    absent = [f"{l}{c}" for l in letters for c in range(1, ncol + 1) if f"{l}{c}" not in balls]
    notes = [
        f"{len(rows)} balls in the table; matrix {len(letters)} rows x {ncol} columns = {len(letters) * ncol} positions.",
        "Row letters present: " + " ".join(letters) + ". Omitted: " + " ".join(singles) + " and " + ", ".join("A" + c for c in dbl_missing) + " (letters FBGA drawings skip because they read as digits).",
        "Positions with no pin in the table: " + (", ".join(absent) or "none") + ".",
        "Bottom view = ball side as seen from the PCB (A1 top-left). Top view = the same grid mirrored left-right, not rotated.",
        "Differential pairs come from vendor names ending p/n after a digit or underscore with a matching partner (e.g. DIFFIO_B1p / DIFFIO_B1n).",
        "Roles: power, ground and NC balls have no die site expected; all others should have one.",
    ]
    cell = {b: letters.index(l) * ncol + (c - 1) for b, (l, c) in balls.items()}
    return dict(letters=letters, cols=ncol, absent=absent, notes=notes, title=label), cell


def load_image(tiles):
    """Optional image layer from the cache written by scripts/geo_image_overlay.py; None when absent or stale."""
    p = GEO / "image_overlay_data.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    nx, ny = tiles["nx"], tiles["ny"]
    if (d["nx"], d["ny"]) != (nx, ny) or d["kinds"] != KINDS or len(d["t"]) != nx * ny:
        raise SystemExit("geo_data: image cache does not match the tile grid; rebuild it with scripts/geo_image_overlay.py --image")
    rows = sorted(d["t"], key=lambda t: (t[0], t[1]))
    if any(t[0] * ny + t[1] != i or t[2] != tiles["kind"][i] for i, t in enumerate(rows)):
        raise SystemExit("geo_data: image cache tile order or kinds differ from the tile table")
    cols = {c: [t[3 + k] for t in rows] for k, c in enumerate(IMG_COLS)}
    return dict(label="third-party EP4CGX150 image", cols=IMG_COLS, cls=d["cls"], C=d["C"], S=d["S"], tp=d["tp"], **cols)


def build(device=DEVICE, package=PACKAGE, path=None, image=True):
    tiles = load_tiles()
    pins = load_pins(db_path(path), device + package)
    rows, ny = pins["rows"], tiles["ny"]
    pair = diff_pairs(rows)
    grid, cell = package_grid(rows, f"{device} {package} package ({len(rows)} balls)")
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
    return dict(schema=SCHEMA, device=device, package=package, geom=dict(vpitch=VPITCH, vband_lo=VBAND_LO),
                tiles=tiles, pins=pins, grid=grid, xref=dict(tile_pins={str(k): v for k, v in sorted(tile_pins.items())}),
                image=load_image(tiles) if image else None)


def check(payload, path=None):
    """Counts in the payload must equal an independent DB query (the page headline numbers)."""
    p = payload["pins"]["rows"]
    con = sqlite3.connect(f"file:{db_path(path)}?mode=ro", uri=True)
    tot, site = con.execute("select count(*), sum(tile_x is not null) from device_pins where device=?", (payload["device"] + payload["package"],)).fetchone()
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
                      "properties": dict(x=x, y=y, kind=KINDS[t["kind"][i]], tier=TIERS[t["tier"][i]], cells=t["cells"][i], ver=t["ver"][i],
                                         set=t["set"][i], edge=t["flag"][i] & 1)})
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db")
    ap.add_argument("--device", default=DEVICE)
    ap.add_argument("--package", default=PACKAGE)
    ap.add_argument("--no-image", action="store_true", help="leave the image layer out")
    ap.add_argument("--export", metavar="DIR")
    ap.add_argument("--geojson", action="store_true")
    a = ap.parse_args()
    pl = build(a.device, a.package, a.db, not a.no_image)
    c = check(pl, a.db)
    sizes = {k: len(json.dumps(v, separators=(",", ":"))) for k, v in pl.items() if isinstance(v, (dict, list))}
    print(f"{pl['device']}{pl['package']}: {c}; image layer {'present' if pl['image'] else 'absent'}; "
          f"{len(dump(pl)) / 1e6:.2f} MB JSON " + " ".join(f"{k}={v / 1e3:.0f}kB" for k, v in sizes.items()))
    if a.export:
        export(pl, Path(a.export))
    if a.geojson:
        GEO.mkdir(parents=True, exist_ok=True)
        geojson(pl, GEO / "die.geojson")


if __name__ == "__main__":
    main()
