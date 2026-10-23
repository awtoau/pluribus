#!/usr/bin/env python3.15t
"""Generate coverage-driven MachXO2 designs (tracked): corpus/machxo2/coverage/<name>/{src,design.toml,placement.lpf}.

Each lane = input pad -> FD1S3AX f1 (LOCATEd slice) -> FD1S3AX f2 (LOCATEd slice) -> output pad.
Pins and slice sites are chosen per profile so signals must cross chip edges and tile types:
  perm   random pins, random sites         lr/rl/tb/bt  inputs on one edge, outputs on the opposite,
  rowline  one row, left pin -> far cols -> right pin          sites in the half far from both pads
  edgeR/edgeL/edgeT/edgeB  pads and sites all on one edge region (H06E right-edge / stub rules)
Pin -> (row, col) from device-db iodb.json (TQFP100); PLC tiles from tilegrid.json.
Usage: python3.15t scripts/machxo2_coverage_gen.py
"""
import json
import os
import random

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "corpus", "machxo2", "coverage")
DB = os.path.join(REPO, "device-db", "MachXO2", "LCMXO2-1200")
CLK_PIN = "88"  # as in the existing fuzz corpus (top edge)

pins = json.load(open(os.path.join(DB, "iodb.json")))["packages"]["TQFP100"]
grid = json.load(open(os.path.join(DB, "tilegrid.json")))
SITES = []
for k, v in grid.items():
    if v["type"] == "PLC":
        rc = k.split(":")[0]
        for s in "ABCD":
            SITES.append(rc + s)
MAXC = max(int(p["col"]) for p in pins.values())
MAXR = max(int(p["row"]) for p in pins.values())


def edge(p):
    if p["col"] == 0:
        return "L"
    if p["col"] >= MAXC - 1:
        return "R"
    if p["row"] == 0:
        return "T"
    return "B"


def pins_on(e):
    return sorted(k for k, p in pins.items() if edge(p) == e and k != CLK_PIN)


def site_rc(s):
    r, c = s[1:-1].split("C")
    return int(r), int(c)


def sites_where(pred):
    return [s for s in SITES if pred(*site_rc(s))]


def emit(name, profile, ins, outs, s1, s2, seed):
    n = min(len(ins), len(outs), len(s1), len(s2))
    d = os.path.join(OUT, name)
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    v = ["module top (clk,"]
    v.append("  " + ", ".join(f"din_{i}" for i in range(n)) + ",")
    v.append("  " + ", ".join(f"dout_{i}" for i in range(n)) + ");")
    v.append("  input clk;")
    v.append("  input " + ", ".join(f"din_{i}" for i in range(n)) + ";")
    v.append("  output " + ", ".join(f"dout_{i}" for i in range(n)) + ";")
    for i in range(n):
        v.append(f"  wire m_{i};")
        v.append(f'  FD1S3AX #(.GSR("DISABLED")) f1_{i} (.D(din_{i}), .CK(clk), .Q(m_{i}));')
        v.append(f'  FD1S3AX #(.GSR("DISABLED")) f2_{i} (.D(m_{i}), .CK(clk), .Q(dout_{i}));')
    v.append("endmodule")
    open(os.path.join(d, "src", "top.v"), "w").write("\n".join(v) + "\n")
    lp = [f'LOCATE COMP "clk" SITE "{CLK_PIN}";', 'IOBUF PORT "clk" IO_TYPE=LVCMOS33;']
    for i in range(n):
        lp += [f'LOCATE COMP "din_{i}" SITE "{ins[i]}";', f'IOBUF PORT "din_{i}" IO_TYPE=LVCMOS33;',
               f'LOCATE COMP "dout_{i}" SITE "{outs[i]}";', f'IOBUF PORT "dout_{i}" IO_TYPE=LVCMOS33;',
               f'LOCATE COMP "f1_{i}" SITE "{s1[i]}";', f'LOCATE COMP "f2_{i}" SITE "{s2[i]}";']
    open(os.path.join(d, "placement.lpf"), "w").write("\n".join(lp) + "\n")
    open(os.path.join(d, "design.toml"), "w").write(
        f'top = "top"\npurpose = "coverage design, profile {profile}"\nprofile = "{profile}"\n'
        f'seed = {seed}\nlanes = {n}\n')
    return name


def pick(rng, pool, n):
    pool = list(pool)
    rng.shuffle(pool)
    return pool[:n]


def main():
    os.makedirs(OUT, exist_ok=True)
    names = []
    allp = sorted(k for k in pins if k != CLK_PIN)
    half = lambda lo: sites_where(lambda r, c: (c <= 11) == lo)
    for k in range(6):
        rng = random.Random(100 + k)
        p = allp[:]
        rng.shuffle(p)
        n = len(p) // 2
        names.append(emit(f"perm_{k}", "perm", p[:n], p[n:2 * n], pick(rng, SITES, n), pick(rng, SITES, n), 100 + k))
    cross = {"lr": ("L", "R", False, True), "rl": ("R", "L", True, False),
             "tb": ("T", "B", None, None), "bt": ("B", "T", None, None)}
    for prof, (a, b, _, _) in cross.items():
        for k in range(4):
            rng = random.Random(200 + k + 10 * list(cross).index(prof))
            pa, pb = pins_on(a), pins_on(b)
            n = min(len(pa), len(pb))
            rng.shuffle(pa); rng.shuffle(pb)
            if prof in ("lr", "rl"):
                far1 = sites_where(lambda r, c: (c > 11) == (a == "L"))
                far2 = sites_where(lambda r, c: (c > 11) == (a == "L"))
            else:
                far1 = sites_where(lambda r, c: (r > 6) == (a == "T"))
                far2 = sites_where(lambda r, c: (r > 6) == (a == "T"))
            names.append(emit(f"{prof}_{k}", prof, pa[:n], pb[:n], pick(rng, far1, n), pick(rng, far2, n), 200 + k))
    # edge-local profiles: pads and sites in the same edge region (stub / mirror rules)
    region = {"edgeR": ("R", lambda r, c: c >= 18), "edgeL": ("L", lambda r, c: c <= 5),
              "edgeT": ("T", lambda r, c: r <= 3), "edgeB": ("B", lambda r, c: r >= 10)}
    for prof, (e, pr) in region.items():
        for k in range(6):
            rng = random.Random(300 + k)
            pe = pins_on(e)
            rng.shuffle(pe)
            # inputs from the edge, outputs to other edges so lanes leave the region and return
            other = [x for x in allp if x not in pe]
            rng.shuffle(other)
            n = min(len(pe), 20)
            reg = sites_where(pr)
            outs = pe[n:2 * n] if (k % 2 and len(pe) >= 2 * n) else other[:n]
            names.append(emit(f"{prof}_{k}", prof, pe[:n], outs, pick(rng, reg, n), pick(rng, reg, n), 300 + k))
    # one-row lines: left pin -> far-column slices -> right pin along a single row
    for r in range(2, 12):
        rng = random.Random(400 + r)
        rowsites = sites_where(lambda rr, c: rr == r)
        pl = [k for k in pins_on("L") if pins[k]["row"] == r] or pins_on("L")[:2]
        n = min(8, len(rowsites))
        pr_ = pins_on("R")
        names.append(emit(f"rowline_{r}", "rowline", (pins_on("L") * 3)[:0] or pins_on("L")[:min(n, len(pins_on("L")))],
                          pr_[:min(n, len(pr_))], pick(rng, rowsites, n), pick(rng, rowsites, n), 400 + r))
    print(len(names), "designs")


if __name__ == "__main__":
    main()
