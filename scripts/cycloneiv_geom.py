#!/usr/bin/env python3.15t
"""Cyclone IV die geometry: tile anchors in the CRAM (frame, v) plane.  Device-driven: one JSON per
die in lifters/data/cycloneiv_<die>_geom.json; code never hard-codes a die.

- anchor(X, Y) = (frame of LE mask bit 0 at N0, v of it), for LAB tiles (cycloneiv_le_model).
- Non-LAB columns (IO, M9K, multiplier) get the anchor their position implies (left neighbour + the
  LAB column pitch); routing tables are keyed by column kind, so only consistency matters.
- Rows: VY linear in Y over the whole die (measured on LAB rows), extended to the IO rows.

  python3.15t scripts/cycloneiv_geom.py --die ep4ce6     # (re)write the JSON from the LE fuzz
"""
import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "lifters" / "data"

DEVICE_DIE = {"EP4CE6E22C8": "ep4ce6", "EP4CE6": "ep4ce6", "EP4CE10": "ep4ce6", "EP3C5": "ep4ce6",
              "EP3C10": "ep4ce6"}


class Geom:
    def __init__(self, d):
        self.d = d
        self.die = d["die"]
        self.FX = {int(k): v for k, v in d["FX"].items()}
        self.kind = {int(k): v for k, v in d["col_kind"].items()}
        self.vy0, self.vpitch = d["vy0"], d["vpitch"]
        self.xmax, self.ymax = d["xmax"], d["ymax"]
        self.DN = {int(k): v for k, v in d["DN"].items()}
        self.dk = {int(k): tuple(v) for k, v in d["dk"].items()}
        self.no_lab = {tuple(t) for t in d.get("no_lab", [])}

    def anchor(self, x, y):
        return self.FX[x], self.vy0 + self.vpitch * y

    def col_kind(self, x):
        return self.kind[x]

    def row_kind(self, y):
        return "IOB" if y == 0 else "IOT" if y == self.ymax else "CORE"

    def tile_class(self, x, y):
        return f"{self.col_kind(x)}/{self.row_kind(y)}"

    def is_lab(self, x, y):
        return self.kind[x] == "LAB" and 0 < y < self.ymax and (x, y) not in self.no_lab


@lru_cache(maxsize=None)
def load(die):
    return Geom(json.loads((DATA / f"cycloneiv_{die}_geom.json").read_text()))


def build_ep4ce6():
    sys.path.insert(0, str(REPO / "scripts"))
    import cycloneiv_le_model as lm
    a = json.loads((REPO / "tmp" / "cycloneiv" / "fuzz_analysis.json").read_text())
    m = lm.Model(a)
    xmax, ymax = 34, 24
    fx, kind = {}, {}
    for x in range(1, xmax):
        if x in m.FX:
            fx[x], kind[x] = m.FX[x], "LAB"
    # non-LAB columns: named by the gap they leave (frames, measured in the X sweep)
    for x in range(0, xmax + 1):
        if x in fx:
            continue
        left = max((k for k in fx if k < x), default=None)
        fx[x] = (fx[left] + 35) if left is not None else fx[min(fx)] - 35
    gap_kind = {0: "IOL", xmax: "IOR"}
    for x in fx:
        if x not in kind:
            kind[x] = gap_kind.get(x) or ("M9K" if fx[x + 1] - fx[x - 1] > 200 else "MUL")
    vy = {y: v for y, v in m.VY.items()}
    pitch = (vy[23] - vy[1]) // 22
    if any(vy[y] != vy[1] + pitch * (y - 1) for y in vy):
        raise SystemExit("VY not linear")
    d = {"die": "ep4ce6", "devices": ["EP4CE6", "EP4CE10", "EP3C5", "EP3C10"],
         "xmax": xmax, "ymax": ymax, "FX": fx, "col_kind": kind,
         "vy0": vy[1] - pitch, "vpitch": pitch,
         "no_lab": [[1, y] for y in range(12, 17)],
         "DN": m.DN, "dk": m.dk}
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--die", default="ep4ce6")
    a = ap.parse_args()
    d = {"ep4ce6": build_ep4ce6}[a.die]()
    out = DATA / f"cycloneiv_{a.die}_geom.json"
    out.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out}: columns {d['col_kind']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
