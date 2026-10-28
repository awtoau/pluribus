#!/usr/bin/env python3.15t
"""Fill device_pins for MachXO2 from the vendored IO database (device-db/MachXO2/<dev>/iodb.json).

  python3.15t scripts/pins_register_machxo2.py [--device LCMXO2-1200] [--packages TQFP100,...] [--board boards/aw2-2d82auto] [--db P]
Sources (per-field `source` kept, disagreements flagged in `conflicts`, never resolved):
  iodb       packages[pkg][pin] -> row, col, pio; pio_metadata[(row,col,pio)] -> bank, function, +/- grouping
  board_pins optional cross-check: the board's pins.tsv (pin, row, col, pio); only agreement is recorded, labels are NOT copied
Pins of a TQFP/QFP/QFN package that the IO database does not list are inserted with bonded NULL, special NULL
("unlisted": supply / config / NC, not covered by the vendored data).  Tile coordinates: x = col, y = max_row - row (row 0 = top).
Always-rebuild per (family, device).  Log: tmp/logs/pins_register_machxo2.log
"""
import argparse
import datetime
import json
import logging
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import dbtools  # noqa: E402

FAMILY = "machxo2"
DB = REPO / "device-db"
JTAG = re.compile(r"^(TCK|TMS|TDI|TDO|JTAGENB)$")
CONFIG = re.compile(r"PROGRAMN|INITN|^DONE$|^SN$|SISPI|SPISO|CCLK|CSSPIN|MCLK")
CLOCK = re.compile(r"PCLK|GPLL|CLKI")
log = logging.getLogger("pins_register_machxo2")


def special_of(names):
    for rx, kind in ((JTAG, "jtag"), (CONFIG, "config"), (CLOCK, "clock")):
        if any(rx.search(n) for n in names):
            return kind
    return "none"


def side_of(row, col, max_row, max_col):
    return "top" if row == 0 else "bottom" if row == max_row else "left" if col == 0 else "right" if col == max_col else None


def n_pins_of(package):
    m = re.fullmatch(r"(?:TQFP|QFP|QFN)(\d+)", package)
    return int(m.group(1)) if m else None


def read_board_pins(tsv):
    """pins.tsv -> {pin: (row, col, pio)} (columns pin, row, col, pio; '#' lines skipped)."""
    out = {}
    for ln in Path(tsv).read_text().splitlines():
        if ln.startswith("#") or not ln.strip():
            continue
        c = ln.split("\t")
        if len(c) >= 4 and c[0].isdigit():
            out[c[0]] = (int(c[1]), int(c[2]), c[3])
    return out


def build_rows(device, package, iodb, dev_geom, board_pins):
    max_row, max_col = dev_geom["max_row"], dev_geom["max_col"]
    meta = {(m["row"], m["col"], m["pio"]): m for m in iodb["pio_metadata"]}
    listed = iodb["packages"][package]
    rows = []
    pins = sorted(set(listed) | {str(i) for i in range(1, (n_pins_of(package) or 0) + 1)}, key=lambda s: (len(s), s))
    for pin in pins:
        base = dict(family=FAMILY, device=device, part=device, package=package, opns=None, pin=pin, pad_number=None,
                    updated_at=datetime.datetime.now().astimezone())
        rec = listed.get(pin)
        if rec is None:
            rows.append(dict(base, bank=None, side=None, tile_x=None, tile_y=None, z=None, io_site=None, io_type=None,
                             func_names=[], ibis_net=None, special=None, bonded=None, usage_default=None,
                             source={"pin": ["package-name"]}, conflicts=None))
            continue
        row, col, pio = rec["row"], rec["col"], rec["pio"]
        m = meta.get((row, col, pio), {})
        names = [n for n in (m.get("function") or "").split("/") if n]
        src = {f: ["iodb"] for f in ("bank", "side", "tile_x", "tile_y", "z", "io_site", "io_type", "func_names", "special", "bonded")}
        src["pin"] = ["iodb"]
        conflicts = []
        bp = board_pins.get(pin)
        if bp is not None:
            if bp == (row, col, pio):
                src["tile_x"].append("board_pins")
                src["tile_y"].append("board_pins")
                src["z"].append("board_pins")
            else:
                conflicts.append({"field": "tile_x", "values": {"iodb": [row, col, pio], "board_pins": list(bp)}})
        rows.append(dict(base, bank=str(m["bank"]) if "bank" in m else None, side=side_of(row, col, max_row, max_col),
                         tile_x=col, tile_y=max_row - row, z="ABCD".index(pio), io_site=f"R{row}C{col}:PIO{pio}", io_type="PIO",
                         func_names=names, ibis_net=None, special=special_of(names), bonded=True, usage_default=None,
                         source=src, conflicts=conflicts or None))
    return rows


def register(db_file, device, packages, board_pins):
    import schema as S
    from sqlalchemy import create_engine
    from provenance import evidence_io as E
    from sqlalchemy import delete, insert
    iodb = json.loads((DB / "MachXO2" / device / "iodb.json").read_text())
    fam = next(f for f in json.loads((DB / "devices.json").read_text())["families"].values() if device in f["devices"])
    geom = fam["devices"][device]
    packages = packages or sorted(iodb["packages"])
    eng = create_engine(f"sqlite:///{db_file}")   # explicit file: db.engine() binds to $PLURIBUS_SQLITE_PATH at import
    S.device_pins.create(eng, checkfirst=True)
    total = 0
    with eng.begin() as conn:
        E.ensure_family(conn, FAMILY)
        conn.execute(delete(S.device_pins).where((S.device_pins.c.family == FAMILY) & (S.device_pins.c.device == device)))
        ev = E.record_decode(conn, FAMILY, device, f"device_pins from the vendored IO database ({len(packages)} packages)",
                             {"iodb": f"device-db/MachXO2/{device}/iodb.json", "packages": packages},
                             E.git_head(REPO), "scripts/pins_register_machxo2.py", generator="scripts/pins_register_machxo2.py")
        for pkg in packages:
            rows = build_rows(device, pkg, iodb, geom, board_pins.get(pkg, {}))
            for r in rows:
                r["evidence_id"] = ev
            conn.execute(insert(S.device_pins), rows)
            log.info("%-9s pins %3d  in iodb %3d  unlisted %3d  board-confirmed %3d  conflicts %d", pkg, len(rows),
                     sum(r["bonded"] is True for r in rows), sum(r["bonded"] is None for r in rows),
                     sum("board_pins" in r["source"].get("tile_x", []) for r in rows), sum(bool(r["conflicts"]) for r in rows))
            total += len(rows)
    log.info("%s %s: %d device_pins rows", FAMILY, device, total)
    return total


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/pins_register_machxo2.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="LCMXO2-1200")
    ap.add_argument("--packages", default=None, help="comma list; default every package of the device")
    ap.add_argument("--board", default=None, help="boards/<name> dir: cross-check its pins.tsv for the board's package")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    board_pins = {}
    if a.board:
        bd = Path(a.board)
        cfg = tomllib.loads((bd / "board.toml").read_text())
        if cfg["board"]["device"] == a.device:
            board_pins[cfg["board"]["package"]] = read_board_pins(bd / cfg["files"]["pins_tsv"])
    register(a.db or dbtools.family_db(FAMILY), a.device, a.packages.split(",") if a.packages else None, board_pins)
    return 0


if __name__ == "__main__":
    sys.exit(main())
