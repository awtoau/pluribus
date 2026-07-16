#!/usr/bin/env python3
"""Recover the MachXO2 I/O map from the unpacked .config + Trellis iodb.

Produces the `.iomap.tsv` sidecar that load.py reads to map PIO sites to
package pins (pin#, bank, function, direction, IO standard, conn class).

Refuses to overwrite an existing sidecar, so it cannot clobber an iomap
that other work depends on.

Inputs:
  - the named-cell config produced by scripts/trellis_unpack.py. PIO
    sites appear as edge tiles, e.g.

        .tile PB20:PIC_B0
        enum: PIOC.BASE_TYPE INPUT_LVTTL33

    The tile is named by edge position (PB20 = peripheral bottom #20),
    NOT by grid row/col, so we translate `name:type` -> grid (row,col)
    via pytrellis.
  - the Trellis iodb.json for the device. `packages` map
    pin -> {row,col,pio}; `pio_metadata` maps {row,col,pio} ->
    {bank, function}. Both use the grid (row,col).

Usage: fpga_iomap.py CONFIG [IODB_JSON]
Env:   TRELLIS_BUILD / TRELLIS_DBROOT / TRELLIS_DEVICE as usual;
       TRELLIS_PACKAGE pins the package (e.g. TQFP100) instead of
       best-fit auto-detection.

Output: CONFIG.iomap.tsv next to the config (refuses to overwrite).

No hardware, no guessing: every fact comes from the bitstream or the DB.
"""

import json
import os
import re
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Same env vars and defaults the lifter uses — no paths of our own.
from lifters.machxo2_lift import (  # noqa: E402
    DEF_BUILD_DIR, DEF_DBROOT, MachXO2Lift, _correct_pio_iostandard,
)

DEVICE = os.environ.get("TRELLIS_DEVICE", "LCMXO2-1200")
DBROOT = DEF_DBROOT
BUILD_DIR = DEF_BUILD_DIR


# `.tile <NAME>:<TYPE>` -- NAME:TYPE together is the Trellis tile name.
TILE_RE = re.compile(r"^\.tile\s+(\S+)")
# enum lines look like:  enum: PIOA.BASE_TYPE OUTPUT_LVTTL33
ENUM_RE = re.compile(r"^\s*enum:\s+PIO([A-D])\.(\w+)\s+(\S+)")


def tile_grid_map(cache=os.path.join(REPO, "tmp", "lcmxo2_tile_rowcol.json")):
    """Return {tile_name: (row, col)} for every tile.

    Native pure-Python chip geometry (no pytrellis .so); the legacy .so path is
    kept behind PLURIBUS_TRELLIS_BACKEND=so for A/B parity.  Cheap enough that
    the cache is optional, but honoured when present.
    """
    if os.path.exists(cache):
        with open(cache) as fh:
            return {k: tuple(v) for k, v in json.load(fh).items()}

    if os.environ.get("PLURIBUS_TRELLIS_BACKEND", "native") == "so":
        sys.path.insert(0, BUILD_DIR)
        import pytrellis  # noqa: E402
        pytrellis.load_database(DBROOT)
        chip = pytrellis.Chip(DEVICE)
        found = {}
        for r in range(chip.get_max_row() + 1):
            for c in range(chip.get_max_col() + 1):
                try:
                    tiles = chip.get_tiles_by_position(r, c)
                except Exception:
                    tiles = []
                for t in tiles:
                    found[t.info.name] = (r, c)
    else:
        sys.path.insert(0, REPO)
        from native_trellis.geometry import ChipGeometry
        geom = ChipGeometry(DEVICE, DBROOT)
        found = dict(geom.tile_rc)

    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w") as fh:
        json.dump({k: list(v) for k, v in found.items()}, fh)
    return found


def parse_config(path, tile_rc):
    """Return {(row,col,pio): {prop: value}} for every PIO with settings."""
    sites = defaultdict(dict)
    cur = None  # grid (row,col) of the current tile, or None
    with open(path) as fh:
        for line in fh:
            m = TILE_RE.match(line)
            if m:
                cur = tile_rc.get(m.group(1))
                continue
            if cur is None:
                continue
            e = ENUM_RE.match(line)
            if e:
                pio, prop, val = e.group(1), e.group(2), e.group(3)
                sites[(cur[0], cur[1], pio)][prop] = val
    return sites


# The Trellis zero-state of an untouched PIC PIO -- VERIFIED against an empty
# MachXO2-1200 design: an unconfigured pad decodes to exactly these three
# enums with NO BASE_TYPE line.
#
# IMPORTANT: a non-default BASE_TYPE only proves the IO *buffer* was configured
# -- NOT that the pad carries a signal. Usage is decided by the routing (see
# the fabric/hardip/unrouted classification in main()).
DEFAULT_PROPS = {("DRIVE", "8"), ("OPENDRAIN", "OFF"), ("PULLMODE", "FAILSAFE")}


def is_configured(props):
    """True if a pad's IO buffer carries any bit beyond the DRIVE-8 default.

    This says only that the buffer was touched, not that the pad is connected.
    """
    return bool(set(props.items()) - DEFAULT_PROPS)


def direction(props):
    bt = props.get("BASE_TYPE")
    if bt:
        if bt.startswith("INPUT"):
            return "in"
        if bt.startswith("OUTPUT"):
            return "out"
        if bt.startswith("BIDIR"):
            return "inout"
    # No BASE_TYPE but non-default bits set: a hard-IP / config-port pad
    # (MCLK, SPI, ...) whose direction the IO enums alone don't pin down.
    return "?"


# Pad-function names that denote a DEDICATED hard-IP connection routed off the
# normal fabric (PLL, sysCONFIG/SPI, JTAG, hard-I2C) -- a configured buffer on
# one of these is genuinely in use even without a fabric arc. A `PCLK*` name,
# by contrast, is only a clock CAPABILITY of an ordinary pad: it proves
# nothing about use, so those are reported separately ("clk?").
DEDICATED_FUNC = ("GPLL", "MCLK", "CCLK", "SPISO", "SISPI", "CSSPIN",
                  "SDA", "SCL", "JTAG", "DONE", "INITN", "PROGRAMN",
                  "TMS", "TCK", "TDI", "TDO")


def func_class(func):
    """'hardip' for a dedicated off-fabric function, 'clk?' for clock-capable
    only, else None."""
    f = func.upper()
    if f == "SN" or any(k in f for k in DEDICATED_FUNC):
        return "hardip"
    if "PCLK" in f:
        return "clk?"
    return None


def main():
    if len(sys.argv) < 2:
        print("usage: fpga_iomap.py CONFIG [IODB_JSON]", file=sys.stderr)
        return 2
    cfg = sys.argv[1]
    iodb_path = sys.argv[2] if len(sys.argv) > 2 else (
        f"{DBROOT}/MachXO2/{DEVICE}/iodb.json")

    out_tsv = cfg + ".iomap.tsv"
    if os.path.exists(out_tsv):
        print(f"REFUSING to overwrite existing {out_tsv}\n"
              "delete it first if regeneration is intended", file=sys.stderr)
        return 1

    tile_rc = tile_grid_map()
    sites = parse_config(cfg, tile_rc)
    iodb = json.load(open(iodb_path))
    packages = iodb["packages"]
    meta = iodb.get("pio_metadata", [])

    # site -> {bank, function} from pio_metadata
    meta_by_site = {}
    for m in meta:
        meta_by_site[(m["row"], m["col"], m["pio"])] = m

    # A pad is "really used" if it carries ANY non-default IO setting -- see
    # is_configured(). Configured output pads often have no BASE_TYPE line
    # (only DRIVE/OPENDRAIN), so a BASE_TYPE-only test loses them.
    used = {site: props for site, props in sites.items()
            if is_configured(props)}
    used_sites = set(used)

    # --- pick the package: the one whose pin map covers the most used sites --
    print(f"PIO sites with settings: {len(sites)}")
    print(f"used (non-default) PIO sites: {len(used_sites)}")
    print("\npackage coverage of used sites:")
    best_pkg, best_score = None, (-1, 0)
    pkg_site_index = {}
    for pkg, pins in packages.items():
        site_to_pin = {}
        for pin, loc in pins.items():
            site_to_pin[(loc["row"], loc["col"], loc["pio"])] = pin
        pkg_site_index[pkg] = site_to_pin
        cov = len(used_sites & set(site_to_pin))
        miss = len(used_sites - set(site_to_pin))
        print(f"  {pkg:10s} pins={len(pins):4d}  "
              f"covers={cov:3d}/{len(used_sites)}  uncovered={miss}")
        # prefer most coverage, then the smallest package achieving it
        score = (cov, -len(pins))
        if score > best_score:
            best_score, best_pkg = score, pkg

    # The physical part is fixed per board; auto best-fit can drift to a
    # larger package once more pads are recovered. TRELLIS_PACKAGE pins it.
    force_pkg = os.environ.get("TRELLIS_PACKAGE")
    if force_pkg:
        if force_pkg not in pkg_site_index:
            sys.exit(f"TRELLIS_PACKAGE={force_pkg} not in {list(packages)}")
        chosen = force_pkg
        cov = len(used_sites & set(pkg_site_index[chosen]))
        print(f"\n==> forced package: {chosen} "
              f"(covers {cov}/{len(used_sites)} used sites; "
              f"{len(used_sites)-cov} configured sites have no {chosen} pin)")
    else:
        chosen = best_pkg
        print(f"\n==> best-fit package: {chosen} "
              f"(covers {best_score[0]}/{len(used_sites)} used sites)")

    site_to_pin = pkg_site_index[chosen]

    # --- routing-grounded usage ---------------------------------------------
    # A configured IO buffer is NOT proof the pad carries a signal. The ground
    # truth is the recovered routing: an input pad is used iff its JQ joint
    # node is an arc SOURCE (its data is routed into the fabric); an output
    # pad is used iff its JA joint node is an arc SINK (a fabric net drives
    # it). Pads that are configured but touch no arc -- and have no dedicated
    # hard-IP function (PLL/I2C/sysCONFIG/clock, which connect off-fabric) --
    # are "unrouted": present in the bitstream but not wired to logic here.
    lift = MachXO2Lift(DEVICE)
    pc_lift = lift.parse_config(cfg)
    rt_sources, rt_sinks = lift.arc_endpoint_sets(pc_lift)

    rows = []
    for site, pin in site_to_pin.items():
        row, col, pio = site
        props = sites.get(site, {})
        m = meta_by_site.get(site, {})
        func = m.get("function", "")
        jq = lift.pad_fabric_node(row, col, pio, "in")
        ja = lift.pad_fabric_node(row, col, pio, "out")
        routed_in = jq in rt_sources
        routed_out = ja in rt_sinks
        fk = func_class(func)

        if routed_out:
            dir_, conn = "out", "fabric"
        elif routed_in:
            dir_, conn = "in", "fabric"
        elif is_configured(props) and fk == "hardip":
            dir_, conn = direction(props), "hardip"
        elif is_configured(props) and fk == "clk?":
            dir_, conn = direction(props), "clk?"
        elif is_configured(props):
            dir_, conn = direction(props), "unrouted"
        else:
            continue  # idle, unconfigured pad

        # Apply local workaround for prjtrellis PULLMODE/BASE_TYPE overlap
        # bug: LVTTL33 outputs with PULLMODE=NONE decode as OUTPUT_MIPI or
        # SSTL25_I because the NONE bits overlap with those BASE_TYPE
        # encodings in the MachXO2 Trellis database.  See
        # _correct_pio_iostandard() in lifters/machxo2_lift.py.
        props_corrected = _correct_pio_iostandard(props)
        rows.append({
            "pin": pin,
            "bank": m.get("bank", "?"),
            "function": func,
            "site": f"R{row}C{col}:PIO{pio}",
            "dir": dir_,
            "conn": conn,
            "iostd": props_corrected.get("BASE_TYPE", ""),
            "drive": props_corrected.get("DRIVE", ""),
            "pull": props_corrected.get("PULLMODE", ""),
        })

    rows.sort(key=lambda r: (str(r["bank"]), int(r["pin"])))
    hdr = ["pin", "bank", "function", "site", "dir", "conn",
           "iostd", "drive", "pull"]
    with open(out_tsv, "w") as fh:
        fh.write("\t".join(hdr) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[h]) for h in hdr) + "\n")

    fabric = [r for r in rows if r["conn"] == "fabric"]
    hardip = [r for r in rows if r["conn"] == "hardip"]
    clkcap = [r for r in rows if r["conn"] == "clk?"]
    unrouted = [r for r in rows if r["conn"] == "unrouted"]
    print(f"\nI/O map ({len(rows)} pads) -> {out_tsv}")
    print(f"  fabric-connected (real signals): {len(fabric)}  "
          f"| hard-IP (PLL/config/I2C): {len(hardip)}  "
          f"| clock-capable (unconfirmed): {len(clkcap)}  "
          f"| configured-but-UNROUTED: {len(unrouted)}\n")
    print(f"{'pin':>5} {'bk':>2} {'function':<14} {'site':<14} "
          f"{'dir':<5} {'conn':<9} {'iostd':<16} {'drv':>3} {'pull'}")
    for r in rows:
        print(f"{str(r['pin']):>5} {str(r['bank']):>2} {r['function']:<14} "
              f"{r['site']:<14} {r['dir']:<5} {r['conn']:<9} {r['iostd']:<16} "
              f"{str(r['drive']):>3} {r['pull']}")

    tally = defaultdict(int)
    for r in rows:
        tally[(r["conn"], r["dir"])] += 1
    print("\nconn/dir tally:", dict(tally))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
