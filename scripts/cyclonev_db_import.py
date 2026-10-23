#!/usr/bin/env python3.15t
"""Import Cyclone V device data into pluribus's SQLite/Postgres DB.

WHY THIS EXISTS
---------------
pluribus treats Lattice tile data as vendored, queryable rows (device-db/),
never as hardcoded logic. This script extends the same model to Altera/Intel
Cyclone V, sourced from Project Mistral (Ravenslofty/mistral).

Mistral's own per-die data (cvd-*.cc, ~540 lines total) is NOT hand-written —
it is generator/ output compiled from plain-text tables under mistral/data/.
That means pluribus can skip Mistral's C++ codegen step entirely and import
straight from the same text Mistral's generator consumes.

Two sources are read here, for different reasons:

  * libmistral/cvd-<die>.cc  — die-level geometry (cram size, frame size,
    pram_sizes, noedcrc_zones, postambles, x_to_bx, column_types). This IS
    the mechanical transliteration target: cv-files.cc's rbf_load/rbf_save
    (the bitstream compression codec) needs exactly these fields, and they
    have no separate plain-text source — generator/nodes.cc derives them by
    combining several raw data/ files (routing + control + package tables)
    in ways out of scope to re-derive this session. Parsed here as a
    regular, mechanical C++ initializer (each of the 7 dies follows the
    identical layout) — not re-run through Mistral's build.

  * data/<die>-pram.txt — PRAM (fixed-block-position) strips. Parsed
    DIRECTLY from Mistral's plain-text generator input (mirroring
    generator/pram.cc's own grammar), never from cvd-*.cc or compiled
    output. This is the data-driven heart of the import: the strip/block/
    position table that generator/pram.cc turns into fixed_block_info /
    dqs16_info C++ structs, landed straight into SQLite instead.

Scope (2026-10-23 session): die geometry + PRAM strips only. The larger
per-node routing tables (data/<die>-r.txt.xz, -l.txt.xz, -p2r.txt, etc. —
cv-bmux.cc/cv-rmux.cc territory) are NOT imported here. See
docs/bluebird.md for what is scoped next.

Usage:
    python3.15t scripts/cyclonev_db_import.py
    python3.15t scripts/cyclonev_db_import.py --die e50f
    python3.15t scripts/cyclonev_db_import.py --mistral-root /mnt/2tb/git/mistral

Logs to ./tmp/logs/cyclonev_db_import.log.
"""
import argparse
import datetime
import logging
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import db
import schema

DEFAULT_MISTRAL_ROOT = "/mnt/2tb/git/mistral"

ALL_DIES = ["e50f", "gt75f", "gt150f", "gt300f", "gx25f", "sx50f", "sx120f"]


def setup_logging():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    log = logging.getLogger("cyclonev_db_import")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fh = logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_db_import.log"))
    sh = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh.setFormatter(fmt)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


# ── cvd-<die>.cc parsing ──────────────────────────────────────────────────────
#
# Every cvd-*.cc file follows the identical layout emitted by mistral's own
# generator (see generator/generator.cc) — a single `die_info` aggregate
# initializer. Rather than hand-write 7 near-duplicate parsers, this pulls each
# field by name out of the initializer text with targeted regexes anchored on
# the comments mistral itself writes before each field (those comments are
# part of the generator's fixed output format, not prose we are relying on).

_INT_LIST_RE = re.compile(r"-?0x[0-9a-fA-F]+|-?\d+")


def _ints_in(text):
    return [int(tok, 0) for tok in _INT_LIST_RE.findall(text)]


def parse_cvd_file(path):
    """Parse one libmistral/cvd-<die>.cc file into a dict of die_info fields."""
    with open(path, "r") as f:
        text = f.read()

    name_m = re.search(r'"\s*(\w+)\s*",\s*\w+,', text)
    if not name_m:
        db.die(f"{path}: could not find die name / die_type_t header line")
    name = name_m.group(1)

    # cram size, tiles size, hps position — three consecutive "N, N,  // comment" lines
    cram_m = re.search(r"(\d+),\s*(\d+),\s*//\s*cram size", text)
    tile_m = re.search(r"(\d+),\s*(\d+),\s*//\s*tiles size", text)
    hps_m = re.search(r"(\d+),\s*(\d+),\s*//\s*hps", text)
    ctrl_m = re.search(r"xycoords\((\d+),\s*(\d+)\)", text)
    if not (cram_m and tile_m and hps_m and ctrl_m):
        db.die(f"{path}: missing cram/tiles/hps/ctrl geometry fields")

    oram_m = re.search(r"//\s*default options\s*\n\s*\{([^}]*)\}", text)
    if not oram_m:
        db.die(f"{path}: missing default_oram block")
    default_oram = _ints_in(oram_m.group(1))
    if len(default_oram) != 12:
        db.die(f"{path}: default_oram has {len(default_oram)} entries, expected 12")

    frame_m = re.search(r"//\s*frame size\s*\n\s*(\d+)", text)
    if not frame_m:
        db.die(f"{path}: missing frame_size")
    frame_size = int(frame_m.group(1))

    pram_m = re.search(r"//\s*pram sizes\s*\n\s*\{([^}]*)\}", text)
    if not pram_m:
        db.die(f"{path}: missing pram_sizes block")
    pram_sizes = _ints_in(pram_m.group(1))

    noedcrc_m = re.search(r"//\s*no edcrc zones\s*\n\s*\{([^}]*)\}", text)
    if not noedcrc_m:
        db.die(f"{path}: missing noedcrc_zones block")
    noedcrc_zones = _ints_in(noedcrc_m.group(1))

    post_m = re.search(r"//\s*postambles\s*\n\s*(\d+),\s*(\d+)", text)
    if not post_m:
        db.die(f"{path}: missing postambles")
    postamble_1, postamble_2 = int(post_m.group(1)), int(post_m.group(2))

    xbx_m = re.search(r"//\s*x to bit x\s*\n\s*\{(.*?)\n\s*\},\s*\n\s*//\s*column types", text, re.S)
    if not xbx_m:
        db.die(f"{path}: missing x_to_bx block")
    x_to_bx = _ints_in(xbx_m.group(1))

    coltypes_m = re.search(r"//\s*column types\s*\n\s*\{(.*?)\n\s*\},", text, re.S)
    if not coltypes_m:
        db.die(f"{path}: missing column_types block")
    column_types = re.findall(r"T_[A-Z0-9]+", coltypes_m.group(1))

    return {
        "name": name,
        "cram_sx": int(cram_m.group(1)), "cram_sy": int(cram_m.group(2)),
        "tile_sx": int(tile_m.group(1)), "tile_sy": int(tile_m.group(2)),
        "hps_x": int(hps_m.group(1)), "hps_y": int(hps_m.group(2)),
        "ctrl_x": int(ctrl_m.group(1)), "ctrl_y": int(ctrl_m.group(2)),
        "frame_size": frame_size,
        "postamble_1": postamble_1, "postamble_2": postamble_2,
        "default_oram": [str(v) for v in default_oram],  # uint64 as decimal strings (JSON-safe)
        "pram_sizes": pram_sizes,
        "noedcrc_zones": noedcrc_zones,
        "x_to_bx": x_to_bx,
        "column_types": column_types,
    }


# ── data/<die>-pram.txt parsing ───────────────────────────────────────────────
#
# Grammar mirrors generator/pram.cc's PRamLoader (hand-written lexer over
# bytes). Each line: "strip.start-end block x.y [instance|- [var]]".
# "-" in the instance slot means "no instance, var follows" (pram.cc: a
# literal '-' byte is consumed and skipped rather than parsed as a digit).
# e.g.:  "00.00944-00983 dll 000.003"
#        "00.01206-01461 dqs16 011.000 0 0"
#        "06.03453-03643 gpio 068.023 - 1"

_PRAM_LINE_RE = re.compile(
    r"^\s*(?P<strip>\d+)\.(?P<start>\d+)-(?P<end>\d+)\s+"
    r"(?P<block>\S+)\s+(?P<x>\d+)\.(?P<y>\d+)"
    r"(?:\s+(?:(?P<instance>\d+)|-))?(?:\s+(?P<var>\d+))?\s*$"
)


def parse_pram_file(path):
    """Parse data/<die>-pram.txt -> list of strip dicts, per generator/pram.cc's grammar."""
    rows = []
    with open(path, "r") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            m = _PRAM_LINE_RE.match(line)
            if not m:
                db.die(f"{path}:{lineno}: unparseable pram line: {line!r}")
            rows.append({
                "strip": int(m.group("strip")),
                "start": int(m.group("start")),
                "end": int(m.group("end")),
                "block": m.group("block"),
                "pos_x": int(m.group("x")),
                "pos_y": int(m.group("y")),
                "instance": int(m.group("instance")) if m.group("instance") else 0,
                "var": int(m.group("var")) if m.group("var") else 0,
            })
    return rows


def import_die(conn, mistral_root, die, log):
    cvd_path = os.path.join(mistral_root, "libmistral", f"cvd-{die}.cc")
    pram_path = os.path.join(mistral_root, "data", f"{die}-pram.txt")
    if not os.path.isfile(cvd_path):
        db.die(f"missing {cvd_path} — is --mistral-root correct?")
    if not os.path.isfile(pram_path):
        db.die(f"missing {pram_path} — is --mistral-root correct?")

    info = parse_cvd_file(cvd_path)
    if info["name"] != die:
        db.die(f"{cvd_path}: die name mismatch, file claims {die!r} but struct says {info['name']!r}")
    if len(info["x_to_bx"]) != info["tile_sx"]:
        db.die(f"{cvd_path}: x_to_bx has {len(info['x_to_bx'])} entries, "
               f"tile_sx says {info['tile_sx']}")
    if len(info["column_types"]) != info["tile_sx"]:
        db.die(f"{cvd_path}: column_types has {len(info['column_types'])} entries, "
               f"tile_sx says {info['tile_sx']}")

    pram_rows = parse_pram_file(pram_path)
    log.info(f"{die}: parsed cram={info['cram_sx']}x{info['cram_sy']} "
              f"tiles={info['tile_sx']}x{info['tile_sy']} frame_size={info['frame_size']} "
              f"pram_strips={len(pram_rows)}")

    from sqlalchemy import delete, insert, select

    # Always-rebuild per die: delete then reinsert, no incremental state.
    existing = conn.execute(select(schema.cv_dies.c.id).where(schema.cv_dies.c.name == die)).fetchone()
    if existing:
        conn.execute(delete(schema.cv_pram_strips).where(schema.cv_pram_strips.c.die == existing[0]))
        conn.execute(delete(schema.cv_dies).where(schema.cv_dies.c.id == existing[0]))

    result = conn.execute(insert(schema.cv_dies).values(
        name=info["name"],
        cram_sx=info["cram_sx"], cram_sy=info["cram_sy"],
        tile_sx=info["tile_sx"], tile_sy=info["tile_sy"],
        hps_x=info["hps_x"], hps_y=info["hps_y"],
        ctrl_x=info["ctrl_x"], ctrl_y=info["ctrl_y"],
        frame_size=info["frame_size"],
        postamble_1=info["postamble_1"], postamble_2=info["postamble_2"],
        default_oram=info["default_oram"],
        pram_sizes=info["pram_sizes"],
        noedcrc_zones=info["noedcrc_zones"],
        x_to_bx=info["x_to_bx"],
        column_types=info["column_types"],
        source_file=f"libmistral/cvd-{die}.cc",
        imported_at=datetime.datetime.now(datetime.timezone.utc),
    ))
    die_id = result.inserted_primary_key[0]

    if pram_rows:
        conn.execute(insert(schema.cv_pram_strips), [
            {**row, "die": die_id} for row in pram_rows
        ])

    log.info(f"{die}: inserted die id={die_id}, {len(pram_rows)} pram strip rows")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--die", choices=ALL_DIES, help="import a single die (default: all 7)")
    ap.add_argument("--mistral-root", default=DEFAULT_MISTRAL_ROOT,
                     help=f"path to the mistral checkout (default: {DEFAULT_MISTRAL_ROOT})")
    args = ap.parse_args()

    log = setup_logging()
    schema.init()

    dies = [args.die] if args.die else ALL_DIES
    log.info(f"importing {len(dies)} die(s) from {args.mistral_root}: {', '.join(dies)}")

    eng = db.engine()
    with eng.connect() as conn:
        for die in dies:
            import_die(conn, args.mistral_root, die, log)
        conn.commit()

    log.info("done")


if __name__ == "__main__":
    main()
