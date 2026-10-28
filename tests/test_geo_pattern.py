"""Pin-order pattern numbers (scripts/geo_devices/common.py pattern) on a synthetic 8-pins-per-side square."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from geo_devices import common  # noqa: E402

F = common.F
NX = NY = 10
PK = dict(layout="perimeter", n_pins=32, per_side=8, sides=["left", "bottom", "right", "top"])


def row(cell, x, y, bank):
    r = [None] * len(F)
    r[F["ball"]], r[F["bank"]], r[F["side"]], r[F["cell"]] = str(cell + 1), bank, "", cell
    r[F["tile"]] = x * NY + y
    return r


def build():
    rows = []
    for k in range(8):                       # left side, top to bottom, tiles in the same order -> rho +1
        rows.append(row(k, 0, NY - 2 - k, "L"))
    for k in range(8):                       # bottom side, left to right, tile x reversed -> rho -1
        rows.append(row(8 + k, 8 - k, 0, "B"))
    for k, y in enumerate([4, 7, 2, 6, 1, 8, 3, 5]):   # right side, shuffled tiles -> no clear order
        rows.append(row(16 + k, NX - 1, y, "R"))
    for k in range(8):                       # top side, right to left, x falling with k -> rho +1
        rows.append(row(24 + k, 8 - k, NY - 1, "T"))
    return rows


def test_edges():
    rows = build()
    tp = {}
    for i, r in enumerate(rows):
        tp.setdefault(r[F["tile"]], []).append(i)
    pat = common.pattern(PK, None, rows, NX, NY, tp)
    e = {x["edge"]: x for x in pat["edges"]}
    assert e["left"]["rho"] == 1.0 and e["left"]["crossings"] == 0
    assert e["top"]["rho"] == 1.0 and e["top"]["crossings"] == 0
    assert e["bottom"]["rho"] == -1.0 and e["bottom"]["crossings"] == 28 and "reverse order" in e["bottom"]["sentence"]
    assert abs(e["right"]["rho"]) < .8 and "no clear order" in e["right"]["sentence"] and e["right"]["crossings"] > 0
    assert "same order" in e["left"]["sentence"]


def test_banks_and_tile_bank():
    rows = build()
    tp = {r[F["tile"]]: [i] for i, r in enumerate(rows)}
    pat = common.pattern(PK, None, rows, NX, NY, tp)
    b = {x["bank"]: x for x in pat["banks"]}
    assert b["L"]["balls"] == 8 and b["L"]["die"] == {"left": [1, 8]} and b["L"]["pkg"].startswith("pins 1-8")
    assert pat["tile_bank"][str(rows[0][F["tile"]])] == ["L", 0]


def test_spearman():
    assert common.spearman([1, 2, 3, 4], [2, 4, 6, 9]) == 1.0
    assert common.spearman([1, 2, 3, 4], [9, 6, 4, 2]) == -1.0
    assert common.spearman([1, 2], [1, 2]) is None and common.spearman([1, 1, 1], [1, 2, 3]) is None


def test_geo_positions_perimeter():
    rows = build()
    g = common.geo_positions(PK, None, rows, NX, NY)
    assert g[0]["pkg"] == dict(k="p", side="left", i=0, n=8, around=0, total=32)
    assert g[24]["pkg"]["side"] == "top" and g[24]["die"]["edge"] == "top" and g[24]["die"]["l"] == 8 and g[24]["die"]["r"] == 1
