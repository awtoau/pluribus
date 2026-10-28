"""Cyclone IV GX adapter: tile table from tmp/geo/tiles.json, pins from device_pins, BGA matrix package, known-cell image layer."""
import json
import os
import re
import sqlite3
import string
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
GEO = REPO / "tmp/geo"
FAMILY, DEFAULT_DEVICE, DEFAULT_PACKAGE = "cycloneiv", "EP4CGX150", "DF31"
KINDS = ["LAB", "M9K", "MUL", "IOL", "IOR", "IOROW"]
TIERS = ["verified", "evidence", "unknown"]
TILE_FLAGS = ("edge", "spec", "leout")                       # bit 0, 1, 2 of the packed `flag` column
IMG_COLS = ["cells", "set", "sv", "se", "su", "so", "capv", "cape", "s2a", "fa", "w", "tmpl"]
VPITCH, VBAND_LO = 70, 48                                    # tile row band = v in [70 y - 48, 70 y + 21]
GEOM = dict(vpitch=VPITCH, vband_lo=VBAND_LO)
UI = dict(
    kind_groups=[dict(id="LAB", label="LAB", slot=0), dict(id="M9K", label="M9K memory", slot=1),
                 dict(id="MUL", label="Multiplier", slot=2), dict(id="IO", label="IO (ring)", slot=3)],
    kind_group=[0, 1, 2, 3, 3, 3], tier_class=["ver", "evi", "unk"],
    flag_labels=dict(edge="Die-edge tiles", spec="Specimen LABs (ring)", leout="LE-output grids (dot)"),
    set_label="Example-image set bits", io_groups=[3], pkg_layout="bga-matrix", flip_chip=True,
    role_labels=["user I/O", "config", "JTAG", "clock", "transceiver", "reference", "power", "ground", "NC"],
    site_labels=["with die site", "no site yet", "no site expected (supply / NC)"])


def db_path(path=None):
    return path or os.environ.get("PLURIBUS_SQLITE_PATH") or str(REPO / "databases/cycloneiv/gx150.db")


def tiles(opts=None):
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


def pin_where(device, package):
    return "device=?", (device + package,)


def pins(path, device, package, specials, no_site_roles, pin_cols):
    """-> pin layer (row list + deduplicated per-field source dicts).  tile/pair/cell are filled by geo_data."""
    nc_names = {"NC", "DNU"}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    q = ("select pin,pad_number,bank,side,tile_x,tile_y,z,io_site,io_type,func_names,ibis_net,special,bonded,usage_default,source,conflicts "
         "from device_pins where device=? order by pin")
    device += package
    rows, srcs, sidx = [], [], {}
    for (pin, pad, bank, side, x, y, z, site, ty, fn, ibis, sp, bonded, usage, src, conf) in con.execute(q, (device,)):
        if src not in sidx:
            sidx[src] = len(srcs)
            srcs.append(json.loads(src))
        funcs = (json.loads(fn) if fn else None) or []
        names = {f.upper() for f in funcs}
        role = "nc" if names and names <= nc_names else (sp or "none")
        rows.append([pin, pad, bank or "", side or "", x, y, z, site or "", ty or "", funcs, ibis or "",
                     specials.index(role), 1 if bonded else 0, usage or "", sidx[src], (json.loads(conf) if conf else None) or [],
                     0 if role in no_site_roles else 1])
    con.close()
    if not rows:
        raise SystemExit(f"geo_data: no device_pins rows for {device}")
    return dict(device=device, cols=pin_cols, roles=specials, rows=rows, src=srcs)


def package(rows, label):
    """BGA matrix from ball names (letters+digits).  Returns (package dict, grid dict, ball -> matrix cell index)."""
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
    pk = dict(layout="bga-matrix", rows=len(letters), cols=ncol, flip_chip=True)
    return pk, dict(letters=letters, cols=ncol, absent=absent, notes=notes, title=label), cell


def image(tl):
    """Optional image layer from the cache written by scripts/geo_image_overlay.py; None when absent or stale."""
    p = GEO / "image_overlay_data.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    nx, ny = tl["nx"], tl["ny"]
    if (d["nx"], d["ny"]) != (nx, ny) or d["kinds"] != KINDS or len(d["t"]) != nx * ny:
        raise SystemExit("geo_data: image cache does not match the tile grid; rebuild it with scripts/geo_image_overlay.py --image")
    rows = sorted(d["t"], key=lambda t: (t[0], t[1]))
    if any(t[0] * ny + t[1] != i or t[2] != tl["kind"][i] for i, t in enumerate(rows)):
        raise SystemExit("geo_data: image cache tile order or kinds differ from the tile table")
    cols = {c: [t[3 + k] for t in rows] for k, c in enumerate(IMG_COLS)}
    return dict(label="third-party EP4CGX150 image", cols=IMG_COLS, cls=d["cls"], C=d["C"], S=d["S"], tp=d["tp"], **cols)
