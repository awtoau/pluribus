#!/usr/bin/env python3.15t
"""Cyclone IV: exact map RCF wire name (type, I, tile) -> routing.ddb fan-out record, from forced specimens (#162).

QUESTION: decode, from vendor outputs only (forced RCF path + raw config-bit diff), which ddb record
(direction, template index, dx) the vendor realises for an RCF-named span wire (R4 first, then C16, R24).

PREDICTION (written before any run): when an R4 hop LB -> R4(I at tile T) is forced via RCF input naming, the
vendor realises it at ONE record determined by (I, T's side/column class).  Check: among the fan-out edges k of
the LB source record s into R4-class records, exactly one has asm.ddb group bits (afx_map'd plane cells, no
shift) that are a subset of the raw-diff cells (spec minus base); that record is the answer.  The sweep-2
"-70 plane frames" displacement (CLASS:2h) is predicted to be this naming offset (record at dx = +-2 from the
RCF tile, 2 columns = -(w(c)+w(c-1)) frames), so the unshifted test finds the record at dx +-2 and the shifted
test on the dx 0 record is the same event seen from the wrong record.
REFUTED by: (a) two honoured builds with identical (I, tile class) giving different records; (b) zero or several
unshifted-subset records for a build (reported as an unresolved row, no retry); (c) a record whose group is
a subset only after a shift.

  python3.15t scripts/cycloneiv_r4_name_map.py existing    # re-read the 23 sweep-2 R4 arcs, 0 new builds
Log tmp/logs/cycloneiv_r4_name_map.log.
"""
import argparse
import collections
import json
import logging
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_hop_specimens as H  # noqa: E402

TMP = REPO / "tmp" / "hop_specimens"
log = logging.getLogger("cycloneiv_r4_name_map")


def candidates(G, s, enum_name="R4"):
    """Fan-out records of s in the wire class, with (k, group cells)."""
    fan = G.D.fan_of(s)
    out = []
    for k, d in enumerate(fan.tolist()):
        if G.klass(d) != enum_name:
            continue
        gb = G.group_bits(s, d)
        out.append((k, d, gb[0] if gb else []))
    return out


def resolve(G, s, on, enum_name="R4"):
    """Records whose group cells are a non-empty subset of the flipped cells (unshifted)."""
    on = set(on)
    return [(k, d, g) for k, d, g in candidates(G, s, enum_name) if g and set(g) <= on]


def rec_desc(G, d, tile_vx, tile_vy):
    D = G.D
    T = D.T if hasattr(D, "T") else None
    return {"rec": int(d), "dx": int(G.P.vx[d]) - tile_vx, "dy": int(G.P.vy[d]) - tile_vy, "idx": int(G.Q.index[d]),
            "dir": int(G.Q.direction[d]) if hasattr(G.Q, "direction") else None}


def cmd_existing(a):
    G = H.Graph()
    rows = []
    for f in sorted(TMP.glob("results*.json")):
        res = json.loads(f.read_text())
        for r in res["rows"]:
            if r.get("kind") == "R4" and r.get("honoured") and r.get("class") == "LB" and "on" in r:
                mux = next(m for m in res["muxes"] if m["mux"] == r["mux"])
                rows.append((f.name, r, mux))
    log.info("honoured LB->R4 sweep-2 arcs: %d", len(rows))
    tab = collections.defaultdict(list)
    for fn, r, mux in rows:
        nm_ = mux["mux_name"]                       # ('R4', X, Y, I)
        tvx, tvy = G.vx(nm_[1]), nm_[2]
        got = resolve(G, r["src"], r["on"])
        desc = [rec_desc(G, d, tvx, tvy) | {"k": k, "n": len(g)} for k, d, g in got]
        exact = [x for x in desc if x["dx"] == 0]
        log.info("X%dY%d R4 I=%d from LB idx %d: unshifted-subset records %s", nm_[1], nm_[2], nm_[3], r["src_idx"],
                 [(x["dx"], x["dy"], x["idx"], x["k"]) for x in desc])
        tab[(nm_[3], r["src_idx"])].append((nm_[1], nm_[2], desc))
        onset = set(r["on"])
        sh = []
        for k, d, g in candidates(G, r["src"]):
            for df in (-70, -74):
                if g and {c + df * H.NV for c in g} <= onset:
                    sh.append((rec_desc(G, d, tvx, tvy)["dx"], rec_desc(G, d, tvx, tvy)["idx"], k, df))
        ex = [rec_desc(G, r["mux"], tvx, tvy)["dx"]]
        log.info("   shifted(-70/-74)-subset records (dx, idx, k, df) %s; named exact-tile record dx %s, in fan-out of src: %s, n R4 cand %d",
                 sh, ex, int(r["mux"]) in G.D.fan_of(r["src"]).tolist(), len(candidates(G, r["src"])))
    log.info("keys (I, LB idx): %d", len(tab))


def chains_observed():
    """Tier-A name triples seen in corpus RCFs: {R4 name: (set of LB source names, set of LI dest names)}; no ddb, no decoder."""
    obs = H.observed_edges()                       # dest name -> Counter(src name)
    r4 = collections.defaultdict(lambda: (set(), set()))
    for dn, c in obs.items():
        if dn[0] == "R4":
            for sn in c:
                if sn[0] == "LE_BUFFER":
                    r4[dn][0].add(sn)
        elif dn[0] == "LOCAL_INTERCONNECT":
            for sn in c:
                if sn[0] == "R4":
                    r4[sn][1].add(dn)
    return {k: v for k, v in r4.items() if v[0] and v[1]}


def cmd_chains(a):
    ch = chains_observed()
    bytile = collections.defaultdict(set)
    for (_t, x, y, i) in ch:
        bytile[(x, y)].add(i)
    log.info("R4 names with LB source and LI dest both seen: %d over %d tiles; distinct I overall %d", len(ch), len(bytile),
             len({k[3] for k in ch}))
    best = sorted(bytile.items(), key=lambda kv: -len(kv[1]))[:12]
    for t, v in best:
        log.info("tile X%dY%d: %d I values %s", t[0], t[1], len(v), sorted(v))
    cnt = collections.Counter(i for s in bytile.values() for i in s)
    log.info("tiles per I: %s", dict(sorted(cnt.items())))


PFX = "gxr4"


def pick_tile_arcs(ch, tile, wires=("R4",), want_i=None):
    """One chain (LB name, wire name, LI name) per I at `tile`, picking (LB, LI) pairs that share a base design
    (same u0 / u1 placement) so one base build serves many arcs.  Names only; no ddb."""
    X, Y = tile
    per_i = collections.defaultdict(list)
    for (t, x, y, i), (lbs, lis) in ch.items():
        if (x, y) != (X, Y) or t not in wires or (want_i is not None and i not in want_i):
            continue
        per_i[(t, i)].append((sorted(lbs, key=lambda n: (abs(n[1] - X) + abs(n[2] - Y), n)),
                              sorted(lis, key=lambda n: (abs(n[1] - X) + abs(n[2] - Y), n))))

    def geom(lb, li):
        u0 = (lb[1], lb[2], H.n_of_i(lb[3]))
        n1 = 6 if (u0[0], u0[1], 6) != (li[1], li[2], 6) else 8
        return u0, (li[1], li[2], n1)
    # greedy: base keys ranked by how many I they serve
    opts = {}
    for k, v in per_i.items():
        o = set()
        for lbs, lis in v:
            for lb in lbs[:6]:
                for li in lis[:6]:
                    if li[3] in H.LI_PORT:
                        o.add((lb, li))
        opts[k] = o
    cover = collections.Counter()
    for k, o in opts.items():
        for key in {geom(*x) for x in o}:
            cover[key] += 1
    out = {}
    for k in sorted(opts):
        if not opts[k]:
            continue
        best = max(opts[k], key=lambda x: (cover[geom(*x)], -abs(x[0][1] - X) - abs(x[1][1] - X), x))
        u0, u1 = geom(*best)
        out[k] = {"wire": k[0], "I": k[1], "tile": [X, Y], "lb": list(best[0]), "wire_name": [k[0], X, Y, k[1]], "li": list(best[1]),
                  "u0": list(u0), "u1": list(u1), "port": H.LI_PORT[best[1][3]]}
    return list(out.values())


def base_name(a):
    return f"{PFX}_b_{a['u0'][0]}_{a['u0'][1]}_{a['u0'][2]}__{a['u1'][0]}_{a['u1'][1]}_{a['u1'][2]}"


def spec_name(a):
    return f"{PFX}_s_{a['wire'].lower()}{a['I']}_X{a['tile'][0]}Y{a['tile'][1]}"


def path_of(a):
    return [tuple(a["lb"]), tuple(a["wire_name"]), tuple(a["li"])]


def cmd_plan(a):
    ch = chains_observed()
    tile = tuple(int(v) for v in a.tile.split(","))
    want = None if not a.only_i else {int(v) for v in a.only_i.split(",")}
    arcs = pick_tile_arcs(ch, tile, wires=tuple(a.wires.split(",")), want_i=want)
    bases = {base_name(x) for x in arcs}
    out = Path(a.out or TMP / f"plan_r4map_X{tile[0]}Y{tile[1]}.json")
    out.write_text(json.dumps({"tile": tile, "arcs": arcs}))
    log.info("plan %s: %d arcs (I %s), %d distinct bases => %d builds", out.name, len(arcs), sorted(x["I"] for x in arcs), len(bases),
             len(arcs) + len(bases))


def cmd_build(a):
    plan = json.loads(Path(a.plan).read_text())
    arcs = plan["arcs"]
    jobs = min(a.jobs, 16)
    for x in arcs:
        H.write_design(base_name(x), tuple(x["u0"]), tuple(x["u1"]), None, "")
    bases = sorted({base_name(x) for x in arcs})
    first = arcs[0]
    u0, u1, port = tuple(first["u0"]), tuple(first["u1"]), first["port"]
    path = path_of(first)
    if a.nulls:
        res = H.build_names([base_name(first)], 1)
        if any(res.values()):
            sys.exit(f"base build failed: {res}")
        brcf = (H.CORPUS / base_name(first) / "routing.rcf").read_text()
        nulls = []
        for tag, seed, kind in (("r", 1, "rename"), ("", 2, "seed")):
            for role in ("b", "s"):
                name = f"{PFX}_null_{kind}_{role}"
                rcf = brcf if tag == "" else H.re.sub(r"\bu1\b", "u1" + tag, brcf)
                if role == "s":
                    rcf = H.rcf_text(rcf, path, "u1" + tag, port, "u0_o" + tag)
                H.write_design(name, u0, u1, port if role == "s" else None, tag, rcf=rcf, seed=seed)
                nulls.append(name)
        H.write_design(spec_name(first), u0, u1, port, "", rcf=H.rcf_text(brcf, path, "u1", port, "u0_o"))
        log.info("null builds: %s", H.build_names(nulls + [spec_name(first)], jobs))
        b0, s0 = H.bits(base_name(first)), H.bits(spec_name(first))
        bad = {}
        for kind in ("rename", "seed"):
            for role, ref in (("b", b0), ("s", s0)):
                n = f"{PFX}_null_{kind}_{role}"
                d = len(H.bits(n) ^ ref) if (H.CORPUS / n / "bitstream.rbf").exists() else "no bitstream"
                log.info("null control %-24s vs original: %s differing cells", n, d)
                if d:
                    bad[n] = d
        if bad:
            sys.exit(f"NULL CONTROL FAILED {bad}; nothing else is trusted")
    todo = [b for b in bases if not (H.CORPUS / b / "routing.rcf").exists()]
    log.info("base builds %d: %s", len(todo), {k: v for k, v in H.build_names(todo, jobs).items() if v})
    specs = []
    for x in arcs:
        n = spec_name(x)
        if (H.CORPUS / n / "routing.rcf").exists():
            continue
        brcf = H.CORPUS / base_name(x) / "routing.rcf"
        if not brcf.exists():
            log.info("%s: base missing, skipped", n)
            continue
        H.write_design(n, tuple(x["u0"]), tuple(x["u1"]), x["port"], "", rcf=H.rcf_text(brcf.read_text(), path_of(x), "u1", x["port"], "u0_o"))
        specs.append(n)
    log.info("spec builds %d: %s", len(specs), {k: v for k, v in H.build_names(specs, jobs).items() if v})


def honoured(x):
    r = H.realised(spec_name(x), "")
    if r is None:
        return False, "no route for u0_o in the post-fit RCF"
    els, ds = r
    if els != path_of(x) or ds != [("u1", x["port"])]:
        return False, f"realised {els} {ds}"
    sb, ss = (H.CORPUS / n / "routing.rcf" for n in (base_name(x), spec_name(x)))
    ob = H.re.sub(r"^###.*\n", "", H.other_signals(sb.read_text(), "u0_o"), flags=H.re.M)
    os_ = H.re.sub(r"^###.*\n", "", H.other_signals(ss.read_text(), "u0_o"), flags=H.re.M)
    return (ob == os_), ("" if ob == os_ else "other nets rerouted")


def shifts_fit(g, on, rng=80):
    """Frame shifts df (same v) putting every group cell inside the flipped set; df = 0 listed first."""
    if not g:
        return []
    return sorted((df for df in range(-rng, rng + 1) if all(c + df * H.NV in on for c in g)), key=abs)


def cmd_analyse(a):
    plan = json.loads(Path(a.plan).read_text())
    G = H.Graph()
    rows = []
    for x in plan["arcs"]:
        row = dict(x)
        if not (H.CORPUS / spec_name(x) / "bitstream.rbf").exists():
            rows.append(dict(row, status="not-built"))
            continue
        ok, why = honoured(x)
        B, S_ = H.bits(base_name(x)), H.bits(spec_name(x))
        on, off = sorted(S_ - B), sorted(B - S_)
        row.update(honoured=ok, why=why, on=on, off=off)
        if ok:
            lb = tuple(x["lb"])
            s = G.lb.get((G.vx(lb[1]), lb[2], lb[3]))
            X, Y = x["tile"]
            tvx, tvy = G.vx(X), Y
            onset = set(on)
            cands = []
            for k, d, g in candidates(G, s, x["wire"]):
                fits = shifts_fit(g, onset)
                cands.append({"k": k, "rec": d, "dx": int(G.P.vx[d]) - tvx, "dy": int(G.P.vy[d]) - tvy, "idx": int(G.Q.index[d]),
                              "n": len(g), "fits": fits[:3]})
            li = tuple(x["li"])
            lrec = G.D.li_of.get((G.vx(li[1]), li[2], li[3]))
            for c in cands:
                gb = G.group_bits(c["rec"], lrec) if lrec is not None else None
                c["down_fit"] = shifts_fit(gb[0], onset)[:2] if gb and gb[0] else None
                z = G.D
                c["dir"] = int(z_dir(G, c["rec"]))
            row.update(src=int(s), lrec=lrec, cands=cands)
            fit = [c for c in cands if c["fits"]]
            row["resolved"] = fit[0] if len(fit) == 1 else None
            row["status"] = "resolved" if len(fit) == 1 else f"unresolved({len(fit)} fit)"
        else:
            row["status"] = "not-honoured"
        rows.append(row)
    out = Path(a.plan).with_name(Path(a.plan).stem.replace("plan_", "results_") + ".json")
    out.write_text(json.dumps({"rows": rows}, default=int))
    cnt = collections.Counter(r["status"] for r in rows)
    log.info("analyse %s: %s", out.name, dict(cnt))
    for r in sorted(rows, key=lambda r: (r["wire"], r["I"])):
        res = r.get("resolved")
        log.info("%s I=%2d X%dY%d: %s %s", r["wire"], r["I"], r["tile"][0], r["tile"][1], r["status"],
                 f"-> dx {res['dx']} dy {res['dy']} dir {res['dir']} idx {res['idx']} k {res['k']} fit df {res['fits']} down {res['down_fit']}" if res else
                 (r.get("why") or [(c["dx"], c["idx"], c["fits"]) for c in r.get("cands", ())]))


def z_dir(G, rec):
    import numpy as _np
    global _Z
    try:
        _Z
    except NameError:
        _Z = _np.load(H.REPO / "tmp" / "ddb" / "stingray4_rt_fanout.npz")
    return _Z["direction"][_Z["tpl"][rec]]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("existing", "chains", "plan", "build", "analyse"))
    ap.add_argument("--tile", default="47,45")
    ap.add_argument("--wires", default="R4")
    ap.add_argument("--only-i", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--plan", default=None)
    ap.add_argument("--nulls", action="store_true")
    ap.add_argument("--jobs", type=int, default=16)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_r4_name_map.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    main()
