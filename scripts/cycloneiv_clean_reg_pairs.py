#!/usr/bin/env python3.15t
"""Register-used pair diffs for the clean tracer (#165).  Exact labels: each build pair differs in ONE named feature (FF present at LE site s).

Sites: 5 LABs (4 corner LABs of the legal-LAB grid + 1 seeded centre LAB), per LAB LE 0-4 = type A, 5-9 = type C, 10-14 = type D, LE 15 anchor.
  type A  LCCOMB at N=2le feeds the chain; base: combout -> next stage; spec: combout -> dffeas at N=2le+1 (D) -> next stage.  FF added to a LUT LE.
  type D  as A, and the LUT output also feeds the stage after next (`datab`): spec uses both the FF output and the LUT output of the LE.
  type C  base: LE empty, wire passes; spec: dffeas at N=2le+1 with asdata = wire, sload = 1 (no LUT).  FF-only LE.
  anchor  LCCOMB + dffeas in LE 15 of every LAB in every build: the LAB clock line / clock mux stays identical across builds.
Design t (0..6) contains the FF at feature site i iff bit t of (i + 1); base contains none.  A cell that differs between base and design t
carries bit t of code(i); a cell is an FF-presence cell of site i iff its code equals code(i) exactly.
Black box: quartus_map / fit / asm / cpf only (build_project of cycloneiv_clean_lut_specimens.py).

  python3.15t scripts/cycloneiv_clean_reg_pairs.py build [--jobs 4]
  python3.15t scripts/cycloneiv_clean_reg_pairs.py analyse        # -> tmp/cycloneiv_clean/reg_pairs/observed.json
Log: tmp/logs/cycloneiv_clean_reg_pairs.log
"""
import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_lut_specimens as LS  # noqa: E402

OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "reg_pairs")
SEED = 165
BITS = 7                           # 70 feature sites + 1 -> code < 128
# measured on the 1,023-LUT specimens (map ~20 s, fit ~20 s, asm ~4 s, cpf ~1 s): 3x measured, stall guard in cycloneiv_fuzz.run
LS.LIMITS = {"quartus_map": 60, "quartus_fit": 120, "quartus_asm": 30, "quartus_eda": 30, "quartus_cpf": 10}
log = logging.getLogger("reg_pairs")


def pick_labs():
    labs = sorted(tuple(x) for x in json.load(open(LS.LABS))["labs"])
    xs, ys = [l[0] for l in labs], [l[1] for l in labs]
    corners = []
    for cx, cy in ((min(xs), min(ys)), (min(xs), max(ys)), (max(xs), min(ys)), (max(xs), max(ys))):
        corners.append(min(labs, key=lambda l: (l[0] - cx) ** 2 + (l[1] - cy) ** 2))
    mid = [l for l in labs if abs(l[0] - np.mean(xs)) < 25 and abs(l[1] - np.mean(ys)) < 20]
    centre = mid[int(np.random.default_rng(SEED).integers(len(mid)))]
    return corners + [centre]


def sites():
    """[(x, y, le, kind)] feature sites in code order, plus anchors."""
    feat, anchors = [], []
    for x, y in pick_labs():
        feat += [(x, y, le, "A") for le in range(5)] + [(x, y, le, "C") for le in range(5, 10)] + [(x, y, le, "D") for le in range(10, 15)]
        anchors.append((x, y, 15))
    return feat, anchors


def verilog(feat, anchors, t):
    L = ["module top(input clk, a, b, c, d, output y);"]
    wires, body, qsf = [], [], []
    cur, side = "a", "b"
    n = 0

    def nxt():
        nonlocal n
        n += 1
        wires.append(f"w{n}")
        return f"w{n}"
    for i, (x, y, le, kind) in enumerate(feat):
        has = t is not None and (((i + 1) >> t) & 1)
        if kind in "AD":
            comb = nxt()
            body.append(f"cycloneive_lcell_comb #(.lut_mask(16'h0001), .sum_lutc_input(\"datac\"), .dont_touch(\"on\")) "
                        f"l{i} (.dataa({cur}), .datab({side}), .datac(c), .datad(d), .combout({comb}));")
            side = comb if kind == "D" else "b"
            qsf.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{2 * le} -to l{i}")
            if has:
                q = nxt()
                body.append(f"dffeas #(.power_up(\"low\")) f{i} (.d({comb}), .clk(clk), .q({q}));")
                qsf.append(f"set_location_assignment FF_X{x}_Y{y}_N{2 * le + 1} -to f{i}")
                comb = q
            cur = comb
        elif has:
            q = nxt()
            body.append(f"dffeas #(.power_up(\"low\")) f{i} (.d(1'b0), .clk(clk), .asdata({cur}), .sload(1'b1), .q({q}));")
            qsf.append(f"set_location_assignment FF_X{x}_Y{y}_N{2 * le + 1} -to f{i}")
            cur = q
    for j, (x, y, le) in enumerate(anchors):
        comb, q = nxt(), nxt()
        body.append(f"cycloneive_lcell_comb #(.lut_mask(16'h0001), .sum_lutc_input(\"datac\"), .dont_touch(\"on\")) "
                    f"al{j} (.dataa({cur}), .datab(b), .datac(c), .datad(d), .combout({comb}));")
        body.append(f"dffeas #(.power_up(\"low\")) af{j} (.d({comb}), .clk(clk), .q({q}));")
        qsf.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{2 * le} -to al{j}")
        qsf.append(f"set_location_assignment FF_X{x}_Y{y}_N{2 * le + 1} -to af{j}")
        cur = q
    L += [f"  wire {w};" for w in wires] + ["  " + b for b in body] + [f"  assign y = {cur};", "endmodule"]
    return "\n".join(L) + "\n", qsf


def build_one(name, feat, anchors, t):
    v, qsf = verilog(feat, anchors, t)
    return LS.build_project(os.path.join(OUT, name), name, v, qsf, vo=True)


def cmd_build(a):
    feat, anchors = sites()
    json.dump({"feat": feat, "anchors": anchors}, open(os.path.join(OUT, "sites.json"), "w"))
    jobs = [("base", None)] + [(f"t{t}", t) for t in range(BITS)]
    import heavy_guard
    with heavy_guard.lease(a.jobs * heavy_guard.JOB_GB["quartus_chain_cyc4"], "cyc4_reg_pairs", log), ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(lambda j: build_one(j[0], feat, anchors, j[1]), jobs))
    for n, s in res:
        log.info("%s: %s", n, f"FAILED at {s}" if s else "ok")
    if any(s for _, s in res):
        raise SystemExit("failed builds")


def le_cells():
    """{field key: int64 [labs, 16] rbf cell} of every single-bit LE_* group of the LAB block (LUT function / input muxes included as ranges)."""
    from lifters.cycloneiv_clean import fields as F, plane as P, tracer as T
    import cycloneiv_clean_dirt as D
    lut = T.Lut()
    w = lut.walk
    bs = F.bases(w, 18)
    tab = P.load_tables()
    out = {}
    for f in F.fields(w, D.enum_tables(), block_types={18}):
        if not f.name.startswith("LE_"):
            continue
        offs = [F.valid_offsets(f.sites[0][p]) for p in range(len(f.sites[0]))]
        for p in range(len(offs)):
            for b in range(len(offs[p])):
                try:
                    ad = np.stack([F.absolute(bs, np.array([f.sites[le][p][b]], np.int64) if False else F.valid_offsets(f.sites[le][p])[b:b + 1])[:, 0]
                                   for le in range(16)], axis=1)
                except Exception:
                    continue
                r, j, k = P.sof_to_rbf(ad.ravel(), tab)
                out[f"{f.name}#{f.gi}/p{p}/b{b}"] = (r * P.BITS_PER_FRAME + (j - 1) * P.LANES + k).reshape(ad.shape)
    return lut, out


# LE fields that carry the register / output configuration (single-bit groups); LUT function and input muxes are reported as counts only
KEY = ("LE_REG_OUT_YGR", "LE_USE_SYNC_CLEAR", "LE_USE_SYNC_LOAD", "LE_USE_REG_CASCADE_ARM", "LE_USE_REGISTER_FEEDBACK", "LE_CLOCK_SELECT",
       "LE_CLEAR_SELECT", "LE_USE_CARRY")


def cmd_analyse(a):
    """Pair table: for every (feature site, design t) the vo ground truth of the LE in base and in t, and the LE cells that differ."""
    import collections
    import cycloneiv_clean_gate as G
    from lifters.cycloneiv_clean import tracer as T
    S = json.load(open(os.path.join(OUT, "sites.json")))
    feat = S["feat"]
    lut, cells = le_cells()
    names = ["base"] + [f"t{t}" for t in range(BITS)]
    plane = {n: T.plane_bits(os.path.join(OUT, n, "build.rbf")) for n in names}
    gt = {}
    for n in names:
        _, lcs, ffs = G.parse_vo(os.path.join(OUT, n, "postfit.vo"))
        gt[n] = ({(x, y, nn) for (x, y, nn) in lcs}, {(x, y, nn) for (x, y, nn) in ffs.values()})
    trans, rows = collections.Counter(), []
    for i, (x, y, le, kind) in enumerate(feat):
        lab = lut.lab(x, y)
        for t in range(BITS):
            n = f"t{t}"
            sb = (( x, y, le) in gt["base"][0], (x, y, le) in gt["base"][1])
            st = ((x, y, le) in gt[n][0], (x, y, le) in gt[n][1])
            if sb == st:
                continue
            diff = {}
            for key, c in cells.items():
                cell = int(c[lab, le])
                if plane[n][cell] != plane["base"][cell]:
                    diff[key] = (int(plane["base"][cell]), int(plane[n][cell]))
            lutfn = sum(1 for k in diff if k.startswith("LE_LUT_FUNCTION"))
            inp = sum(1 for k in diff if k.startswith("LE_LUT_INPUT"))
            sig = tuple(sorted((k.split("#")[0] + ("#" + k.split("#")[1].split("/")[0] if "YGR" in k else ""), v) for k, v in diff.items()
                               if k.startswith(KEY)))
            trans[(kind, "lc,ff base=%s t=%s" % (sb, st), sig, "lutfn_flips=%d" % lutfn)] += 1
            rows.append(dict(i=i, t=t, kind=kind, base=sb, spec=st, diff=diff))
    json.dump(rows, open(os.path.join(OUT, "observed.json"), "w"))
    log.info("pair rows (site, design) whose vo state differs from base: %d", len(rows))
    for k, v in sorted(trans.items(), key=lambda kv: (kv[0][0], -kv[1])):
        log.info("%3d  %s", v, k)
    # LE state table of every LE of the specimen LABs in every design: (ff, lc) x (YGR bits, sync bits, lut cells nonzero)
    tab = collections.Counter()
    for n in names:
        bits = plane[n]
        for (x, y, _, _) in {(f[0], f[1], 0, 0) for f in feat}:
            lab = lut.lab(x, y)
            for le in range(16):
                ygr = tuple(int(bits[cells[f"LE_REG_OUT_YGR#{g}/p0/b0"][lab, le]]) for g in range(3))
                sy = tuple(int(bits[cells[k + "#-1/p0/b0"][lab, le]]) for k in ("LE_USE_SYNC_CLEAR", "LE_USE_SYNC_LOAD"))
                lz = int(bits[lut.cell[lab, le]].sum() > 0)
                tab[((x, y, le) in gt[n][1], (x, y, le) in gt[n][0], ygr, sy, lz)] += 1
    log.info("LE state table over all LEs of the 5 specimen LABs x %d designs: (ff, lccomb, YGR, SYNC clr/load, lut cells set) -> count", len(names))
    for k, v in sorted(tab.items(), key=lambda kv: (kv[0][:2], -kv[1])):
        log.info("%5d  %s", v, k)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_reg_pairs.log"), mode="a")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build")
    b.add_argument("--jobs", type=int, default=4)
    b.set_defaults(f=cmd_build)
    sp.add_parser("analyse").set_defaults(f=cmd_analyse)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
