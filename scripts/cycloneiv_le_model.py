#!/usr/bin/env python3.15t
"""EP4CE6 LE LUT-mask address model, built only from Cyclone IV fuzz oracle runs
(tmp/cycloneiv/fuzz_analysis.json from cycloneiv_fuzz_analyze.py).

- Frame-bit layout: bit index b = byte*8 + lane (LSB-first).  Vertical position v: lane 7 first
  (bytes 0..205), then lanes 6..0 (bytes 0..206 each): v = byte (lane 7), else
  206 + (6 - lane) * 207 + byte.  Lane 7 = 206 bytes was found from 4 failing held-out designs
  (rows whose LAB crosses from lane 6 into lane 7); those sites are training data from then on.
- Separable: frame = FX[X] - df(k); v = VY[Y] + DN[N] + dv(k).
  FX from the X sweep (Y18 N0), VY from the Y sweep (X1 N0), DN from the N sweep (X1 Y18),
  df/dv/inversion per mask bit k from the one-hot site LCCOMB_X1_Y18_N0.
- dv mirrors (sign flip) when N/2 is odd: found when the first version mispredicted 8/16 bits at
  LCCOMB_X1_Y18_N2, so that site is training data for the mirror rule, not held-out.
- Held-out: the other fuzz sites and the ho_* builds (scored by simulation, not here).

  python3.15t scripts/cycloneiv_le_model.py   # prints the tables + the held-out bit-map check
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LANE = 207
TOP = 206   # lane 7 holds one byte less: a held-out miss at X19_Y3_N20 / X33_Y3_N22 (1 byte off)
TRAIN_SITE = "LCCOMB_X1_Y18_N0"


def v_of(bit):
    byte, lane = divmod(bit, 8)
    size = TOP if lane == 7 else LANE
    if byte >= size:
        raise ValueError(f"bit {bit}: byte {byte} >= {size} in lane {lane}")
    return byte if lane == 7 else TOP + (6 - lane) * LANE + byte


def bit_of(v):
    if 0 <= v < TOP:
        return v * 8 + 7
    q, byte = divmod(v - TOP, LANE)
    if not 0 <= q <= 6:
        raise ValueError(f"v {v} outside the frame")
    return byte * 8 + (6 - q)


def site_xyn(site):
    m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)$", site)
    return tuple(int(g) for g in m.groups())


class Model:
    def __init__(self, analysis):
        sweep = analysis["site_sweep"]
        k0 = {}
        for site, r in sweep.items():
            if "vo_masks" not in r or r["vo_masks"][0] != "0001" or len(r["only_first"]) != 1:
                continue
            k0[site_xyn(site)] = tuple(r["only_first"][0])
        self.FX = {x: f for (x, y, n), (f, _b) in k0.items() if y == 18 and n == 0}
        self.VY = {y: v_of(b) for (x, y, n), (_f, b) in k0.items() if x == 1 and n == 0}
        base = v_of(k0[(1, 18, 0)][1])
        self.DN = {n: v_of(b) - base for (x, y, n), (_f, b) in k0.items() if x == 1 and y == 18}
        train = next(r for r in analysis["lut"] if r["site"] == TRAIN_SITE)["bitmap"]
        f0, b0, _ = train["0"][0]
        self.dk = {}
        for k in range(16):
            f, b, inv = train[str(k)][0]
            self.dk[k] = (f - f0, v_of(b) - v_of(b0), inv)

    def lut_bits(self, site):
        """{k: [[frame, bit, inverted]]} for an LE site, or None if a table lacks X/Y/N."""
        x, y, n = site_xyn(site)
        if x not in self.FX or y not in self.VY or n not in self.DN:
            return None
        out = {}
        mirror = -1 if (n // 2) % 2 else 1   # odd LE of a pair: second bit above, not below
        for k, (df, dv, inv) in self.dk.items():
            out[str(k)] = [[self.FX[x] + df, bit_of(self.VY[y] + self.DN[n] + mirror * dv), inv]]
        return out


def main():
    a = json.loads((REPO / "tmp" / "cycloneiv" / "fuzz_analysis.json").read_text())
    m = Model(a)
    print("FX (frame of mask bit 0 at N0, by X):", dict(sorted(m.FX.items())))
    print("VY (v of mask bit 0 at X1 N0, by Y):", dict(sorted(m.VY.items())))
    print("DN (v offset by N):", dict(sorted(m.DN.items())))
    print("per-k (frame delta, v delta, inverted):", m.dk)
    good = bad = 0
    for r in a["lut"]:
        if r["site"] == TRAIN_SITE or not r.get("bitmap"):
            continue
        pred = m.lut_bits(r["site"])
        role = "training for the mirror rule" if r["site"] == "LCCOMB_X1_Y18_N2" else "held-out"
        hit = 0
        for k in range(16):
            obs = r["bitmap"][str(k)]
            if pred and pred[str(k)] == obs:
                hit += 1
            else:
                print(f"  {r['site']} k{k}: model {pred and pred[str(k)]} measured {obs}")
        print(f"{role} site {r['site']}: model == measured {hit} / 16")
        if role == "held-out":
            good, bad = good + hit, bad + 16 - hit
    print(f"held-out bit-map positions: model == measured {good} / {good + bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
