"""MachXO2 adapter (docs/geo-adapters.md): tile grid from the vendored routing database, pins from device_pins
(scripts/pins_register_machxo2.py), tiers from the family provenance claims, design layer from an unpacked .config."""
import json
import os
import re
import sqlite3
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
FAMILY, DEFAULT_DEVICE, DEFAULT_PACKAGE = "machxo2", "LCMXO2-1200", "TQFP100"
DBROOT = REPO / "device-db"
KINDS = ["SLICE", "PIO", "PIO-DUMMY", "EBR", "HARD", "CIB", "CLOCK", "CORNER", "OTHER"]
GROUPS = [dict(id="SLICE", label="Slice (PLC)", slot=0), dict(id="EBR", label="EBR memory", slot=1),
          dict(id="HARD", label="PLL / DLL / config / OSC", slot=2), dict(id="IO", label="PIO (pads)", slot=3),
          dict(id="CIB", label="CIB only (routing)", slot=4), dict(id="MISC", label="Clock spine / corner / other", slot=5)]
KIND_GROUP = [0, 3, 3, 1, 2, 4, 5, 5, 5]
GEOM = {}
UI = dict(kind_groups=GROUPS, kind_group=KIND_GROUP, tier_class=None, flag_labels=dict(edge="Die-edge positions"),
          set_label="Design features set", io_groups=[3], pkg_layout="perimeter", flip_chip=False,
          role_labels=["user I/O", "config", "JTAG", "clock", "transceiver", "reference", "power", "ground", "NC",
                       "not in IO database"],
          site_labels=["with die site", "no site known (pin not in the IO database)", "no site expected"])
_cache = {}


def db_path(path=None):
    if path:
        return path
    import dbtools
    return dbtools.family_db(FAMILY)


def pin_where(device, package):
    return "family='machxo2' and device=? and package=?", (device, package)


def _kind(types):
    ty = [t for t in types]
    def has(f):
        return any(f(t) for t in ty)
    if has(lambda t: t.startswith("EBR") and not t.startswith("CIB")):
        return "EBR"
    if has(lambda t: t.startswith(("CFG", "GPLL", "DQSDLL")) or "OSC" in t):
        return "HARD"
    if has(lambda t: t == "PLC"):
        return "SLICE"
    if has(lambda t: t.startswith("PIC_") and "DUMMY" in t):
        return "PIO-DUMMY"
    if has(lambda t: t.startswith("PIC_") or t.startswith(("LLC", "ULC", "LRC", "URC")) is False and t.startswith("PIC")):
        return "PIO"
    if has(lambda t: t.startswith(("LLC", "ULC", "LRC", "URC"))):
        return "CORNER"
    if has(lambda t: t.startswith("CENTER")):
        return "CLOCK"
    if has(lambda t: t.startswith("CIB_")):
        return "CIB"
    if has(lambda t: "DUMMY" in t or t.startswith("B_DUMMY") or t.startswith("T_DUMMY")):
        return "PIO-DUMMY"
    return "OTHER"


def grid(device=DEFAULT_DEVICE):
    """-> (max_row, max_col, {(row, col): [(tile name, type)]}); cached."""
    if device not in _cache:
        sys.path.insert(0, str(REPO))
        from native_trellis import pytrellis_compat as pt
        pt.load_database(str(DBROOT))
        ch = pt.Chip(device)
        mr, mc = ch.get_max_row(), ch.get_max_col()
        _cache[device] = (mr, mc, {(r, c): [(t.info.name, t.info.type) for t in ch.get_tiles_by_position(r, c)]
                                   for r in range(mr + 1) for c in range(mc + 1)})
    return _cache[device]


def design_source(opts=None):
    """-> (config path, label, source) of the design layer, or None.  Board config first, else an in-repo corpus example."""
    opts = opts or {}
    if opts.get("design"):
        return Path(opts["design"]), opts.get("design_label", "design"), "--design"
    b = opts.get("board")
    if b:
        cfg = tomllib.loads((Path(b) / "board.toml").read_text())
        found = [(Path(b) / spec["config"]).resolve() for spec in cfg.get("bitstreams", {}).values()]
        found = [p for p in found if p.exists()]
        if found:   # the last listed bitstream = the newest
            return found[-1], "the real design, unpacked config", "board"
    ex = sorted((REPO / "corpus/machxo2/constructs").glob("*/*.config"))
    ex = [p for p in ex if "adder_v01_16" in str(p)] or ex
    return (ex[0], f"EXAMPLE only: in-repo corpus design {ex[0].parent.name} (no real-design lift available)", "corpus") if ex else None


def parse_design(path, names):
    """Per-position counts from a Trellis .config: {(row,col): dict(lut, ff, feat)}.  `names` = {tile name:type -> (row, col)}."""
    out, cur = {}, None
    tile_re = re.compile(r"^\.tile\s+(\S+)")
    for ln in Path(path).read_text().splitlines():
        m = tile_re.match(ln)
        if m:
            cur = names.get(m.group(1))
            continue
        if cur is None or not ln or ln[0] == ".":
            continue
        d = out.setdefault(cur, dict(lut=0, ff=0, feat=0))
        if ln.startswith(("arc:", "word:", "enum:", "unknown:")):
            d["feat"] += 1
        if ln.startswith("word: SLICE") and ".INIT " in ln and "1" in ln.split()[-1]:
            d["lut"] += 1
        if ln.startswith("enum: SLICE") and ".REGSET " in ln:
            d["ff"] += 1
    return out


def tiles(opts=None):
    mr, mc, g = grid()
    nx, ny = mc + 1, mr + 1
    tg = json.loads((DBROOT / "MachXO2" / DEFAULT_DEVICE / "tilegrid.json").read_text())
    size = {k: v["rows"] * v["cols"] for k, v in tg.items()}
    claims = {}
    p = db_path()
    if Path(p).exists():
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            for key, tier in con.execute("select subject_key, tier from claims where family='machxo2' and device=? and space='tile-bit'",
                                         (DEFAULT_DEVICE,)):
                claims[key.removeprefix("tiletype:")] = tier
        except sqlite3.OperationalError:
            pass
        con.close()
    tier_names = sorted(set(claims.values())) + ["no claim"]
    design = design_source(opts)
    dz = parse_design(design[0], {n: rc for rc, ts in g.items() for n, t in ts}) if design else {}
    cols = {k: [0] * (nx * ny) for k in ("kind", "tier", "cells", "ver", "set", "flag")}
    dcols = {k: [0] * (nx * ny) for k in ("lut", "ff", "feat")}
    for (r, c), ts in g.items():
        i = c * ny + (mr - r)
        cols["kind"][i] = KINDS.index(_kind([t for _, t in ts]))
        cl = [claims[t] for _, t in ts if t in claims]
        cols["tier"][i] = tier_names.index(cl[0]) if cl else len(tier_names) - 1
        cols["cells"][i] = sum(size.get(n, 0) for n, t in ts)
        cols["ver"][i] = sum(size.get(n, 0) for n, t in ts if t in claims)
        cols["flag"][i] = int(r in (0, mr) or c in (0, mc))
        d = dz.get((r, c))
        if d:
            for k in dcols:
                dcols[k][i] = d[k]
            cols["set"][i] = d["feat"]
    out = dict(die=DEFAULT_DEVICE, nx=nx, ny=ny, kinds=KINDS, tiers=tier_names, flags=["edge"], **cols)
    out["_design"] = None if not design else dict(label=design[1], source=design[2], cols=dcols)
    return out


def tier_class(tl):
    return ["ver" if t != "no claim" else "unk" for t in tl["tiers"]]


def pins(path, device, package, specials, no_site_roles, pin_cols):
    roles = specials + ["unlisted"]
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    q = ("select pin,pad_number,bank,side,tile_x,tile_y,z,io_site,io_type,func_names,ibis_net,special,bonded,usage_default,source,conflicts "
         "from device_pins where family='machxo2' and device=? and package=?")
    rows, srcs, sidx = [], [], {}
    for (pin, pad, bank, side, x, y, z, site, ty, fn, ibis, sp, bonded, usage, src, conf) in sorted(con.execute(q, (device, package)).fetchall(),
                                                                                                    key=lambda r: int(r[0])):
        if src not in sidx:
            sidx[src] = len(srcs)
            srcs.append(json.loads(src))
        role = "unlisted" if bonded is None else (sp or "none")
        rows.append([pin, pad, bank or "", side or "", x, y, z, site or "", ty or "", (json.loads(fn) if fn else None) or [], ibis or "",
                     roles.index(role), 1 if bonded else 0, usage or "", sidx[src], (json.loads(conf) if conf else None) or [],
                     0 if role in tuple(no_site_roles) + ("unlisted",) else 1])
    con.close()
    if not rows:
        raise SystemExit(f"geo_data: no device_pins rows for {device} {package}; run scripts/pins_register_machxo2.py")
    return dict(device=device, cols=pin_cols, roles=roles, rows=rows, src=srcs)


def package(rows, label):
    n = len(rows)
    if n % 4 or not re.fullmatch(r"\d+", rows[0][0]):
        raise SystemExit("geo_data: machxo2 adapter supports perimeter packages (TQFP/QFP/QFN) only")
    pk = dict(layout="perimeter", n_pins=n, per_side=n // 4, sides=["left", "bottom", "right", "top"], pin1="top-left", flip_chip=False,
              notes=[f"{n} pins, {n // 4} per side, numbered counter-clockwise from the top view; pin 1 at the top-left corner.",
                     "Pins the IO database does not list are drawn hollow grey (supply / config / NC not covered by the vendored data)."])
    return pk, None, {r[0]: int(r[0]) - 1 for r in rows}


def pairs(rows):
    """Differential partners: pad letters A/B and C/D of the same PIO tile."""
    at = {(r[4], r[5], r[6]): i for i, r in enumerate(rows) if r[4] is not None}
    out = {}
    for (x, y, z), i in at.items():
        j = at.get((x, y, z ^ 1))
        if j is not None and z % 2 == 0:
            out[i], out[j] = j, i
    return out


def design(tl):
    d = tl.pop("_design", None)
    return d
