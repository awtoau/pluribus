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

DEVICE_DIE = {"EP4CE6": "ep4ce6", "EP4CE10": "ep4ce6", "EP3C5": "ep4ce6", "EP3C10": "ep4ce6",
              "EP4CGX150": "ep4cgx150", "EP4CGX110": "ep4cgx150"}


def die_of(device):
    """Part number (any package / speed suffix) -> die name."""
    for k in sorted(DEVICE_DIE, key=len, reverse=True):
        if device.startswith(k):
            return DEVICE_DIE[k]
    raise KeyError(f"no die for device {device}")


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
        # bytes used per bit-lane, lanes in v order (7 first); v = lane-major position
        self.lane_bytes = d.get("lane_bytes", [206] + [207] * 7)

    def v_of(self, bit):
        """frame bit (byte*8 + lane) -> v, or None outside the lane model."""
        byte, lane = divmod(bit, 8)
        order = 7 - lane
        if byte >= self.lane_bytes[order]:
            return None
        return sum(self.lane_bytes[:order]) + byte

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


def build_from_locate(die, locate_json, frame_bytes, devices):
    """Geometry from cycloneiv_le_locate anchors {"x,y": [frame, lane, byte]}.
    - FX[x]: one frame per column (hard error if a column disagrees).
    - Lane sizes: the (top lane, other lanes) byte counts that make v linear in Y over every
      located row; pitch and vy0 from that fit (hard error if none fits)."""
    loc = {tuple(map(int, k.split(","))): tuple(v) for k, v in json.loads(Path(locate_json).read_text()).items()}
    fx = {}
    for (x, y), (f, _l, _b) in loc.items():
        if fx.setdefault(x, f) != f:
            raise SystemExit(f"column X{x}: anchors in frames {fx[x]} and {f}")
    nb = frame_bytes - 2
    best = None
    for top in (nb - 2, nb - 1, nb):
        for lane in (nb - 1, nb):
            sizes = [top] + [lane] * 7
            vy = {}
            for (x, y), (f, ln, b) in loc.items():
                vy.setdefault(y, set()).add(sum(sizes[:7 - ln]) + b)
            if any(len(s) != 1 for s in vy.values()):
                raise SystemExit(f"a row has anchors at several v: {vy}")
            ys = sorted(vy)
            if len(ys) < 2:
                raise SystemExit("need anchors on >= 2 rows")
            vs = {y: next(iter(vy[y])) for y in ys}
            pitch = (vs[ys[-1]] - vs[ys[0]]) // (ys[-1] - ys[0])
            if all(vs[y] == vs[ys[0]] + pitch * (y - ys[0]) for y in ys):
                cand = (sizes, vs[ys[0]] - pitch * ys[0], pitch)
                if best and best != cand:
                    log_amb = f"lane sizes ambiguous: {best} vs {cand}"
                    raise SystemExit(log_amb)
                best = cand
    if best is None:
        raise SystemExit("no lane-size model makes VY linear")
    sizes, vy0, pitch = best
    xs = sorted(fx)
    pitch_f = min(b - a for a, b in zip(xs, xs[1:]) if b == a + 1)
    xmax = max(xs) + 1
    kind = {x: "LAB" for x in xs}
    for x in range(0, xmax + 1):
        if x not in fx:
            left = max((k for k in fx if k < x), default=None)
            fx[x] = fx[left] + pitch_f if left is not None else fx[min(xs)] - pitch_f
            kind[x] = "IOL" if x == 0 else "IOR" if x == xmax else "COL"
    return {"die": die, "devices": devices, "xmax": xmax, "ymax": None, "FX": fx, "col_kind": kind,
            "vy0": vy0, "vpitch": pitch, "lane_bytes": sizes, "no_lab": [],
            "DN": dict(enumerate([0, -3, -8, -11, -16, -19, -24, -27, -38, -41, -46, -49, -54, -57, -62, -65])),
            "dk": {}, "located_tiles": len(loc)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--die", default="ep4ce6")
    ap.add_argument("--locate", help="cycloneiv_le_locate JSON (dies other than ep4ce6)")
    ap.add_argument("--frame-bytes", type=int)
    ap.add_argument("--ymax", type=int)
    ap.add_argument("--devices", default="")
    a = ap.parse_args()
    if a.die == "ep4ce6":
        d = build_ep4ce6()
    else:
        d = build_from_locate(a.die, a.locate, a.frame_bytes, a.devices.split(","))
        d["ymax"] = a.ymax
    out = DATA / f"cycloneiv_{a.die}_geom.json"
    out.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out}: columns {d['col_kind']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
