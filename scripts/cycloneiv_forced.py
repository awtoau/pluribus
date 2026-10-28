#!/usr/bin/env python3.15t
"""Cyclone IV GX single-hop specimens, RAW cram-plane diff (issue #141). No Dec.active, no asm decode.

Pair = identical cells + placement + pins; specimen has the one net, base leaves the sink pin open.
Diff = set bits only in one plane (cycloneiv_corpus.cram_plane keys).  Optional forced route:
a design may carry src/force.rcf, fed to the fitter via ROUTING_BACK_ANNOTATION_MODE/FILE.

  python3.15t scripts/cycloneiv_forced.py tier --jobs 6      # Tier 0/1 smallest pairs + diff report
Log tmp/logs/cycloneiv_forced.log
"""
import argparse
import datetime
import json
import logging
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_fuzz as fz  # noqa: E402
import toolchain  # noqa: E402

log = logging.getLogger("cycloneiv_forced")
CORPUS = REPO / "corpus" / "cycloneiv"
DEVICE = "EP4CGX150DF31C7"
CELL = ('  cycloneiv_lcell_comb #(.lut_mask(16\'h{mask}), .sum_lutc_input("datac"), .dont_touch("on"))\n'
        "    {name} ({ports});\n")
PORTS = ("dataa", "datab", "datac", "datad")


def verilog(cells, nets):
    """cells: [(name, mask, {port: net})]; nets: wires; the last cell's combout is output y."""
    v = "module top(output y);\n" + "".join(f"  wire {n};\n" for n in nets)
    for i, (nm, mask, conns) in enumerate(cells):
        ports = [f".{p}({n})" for p, n in conns.items()] + [f".combout({'y' if i == len(cells) - 1 else nm + '_o'})"]
        v += CELL.format(mask=mask, name=nm, ports=", ".join(ports))
    return v + "endmodule\n"


def write_design(name, v, qsf, purpose, rcf=None):
    d = CORPUS / name
    if (d / "routing.rcf").exists():
        return
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "src" / "top.v").write_text(v)
    q = list(qsf)
    if rcf:
        (d / "src" / "force.rcf").write_text(rcf)
        q = ["set_global_assignment -name ROUTING_BACK_ANNOTATION_MODE NORMAL",
             "set_global_assignment -name ROUTING_BACK_ANNOTATION_FILE ../src/force.rcf"] + q
    q += ["set_global_assignment -name SEED 1", 'set_global_assignment -name FITTER_EFFORT "FAST FIT"']
    ver = re.search(r"quartus-([\d.]+)", toolchain.quartus_bin())
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "{purpose}"\nexercises = {fz.toml_list(["routing", "forced"])}\n'
        f"qsf = {fz.toml_list(q)}\ndevice = \"{DEVICE}\"\ntool = \"quartus\"\n"
        f'tool_version = "{ver.group(1) if ver else "unknown"}"\nbuilt = "{datetime.date.today().isoformat()}"\n')


def lc(x, y, n):
    return f"LCCOMB_X{x}_Y{y}_N{n}"


def tier_designs():
    out = {}
    pin = "set_location_assignment PIN_B9 -to y"
    # Tier 0: one cell, combout -> own dataa (loop) vs dataa open
    for kind in ("s", "b"):
        out[f"gxt0_{kind}"] = ("module top(output y);\n  cycloneiv_lcell_comb #(.lut_mask(16'hFFFF), "
                               '.sum_lutc_input("datac"), .dont_touch("on"))\n    u0 ('
                               + (".dataa(y), " if kind == "s" else "") + ".combout(y));\nendmodule\n",
                               [f"set_location_assignment {lc(10, 10, 0)} -to u0", pin], "tier0 self-loop")
    # Tier 1: u0 (N0) -> u1.<port>, base leaves it open; sources N0,N2,N4 -> sink N6 etc via varied args
    for port in PORTS:
        for src in (0, 2, 4):
            for kind in ("s", "b"):
                conns = {port: "u0_o"} if kind == "s" else {}
                v = ("module top(output y);\n  wire u0_o;\n"
                     '  cycloneiv_lcell_comb #(.lut_mask(16\'h0000), .sum_lutc_input("datac"), .dont_touch("on"))\n'
                     "    u0 (.combout(u0_o));\n"
                     '  cycloneiv_lcell_comb #(.lut_mask(16\'hFFFF), .sum_lutc_input("datac"), .dont_touch("on"))\n'
                     f"    u1 ({''.join(f'.{p}({n}), ' for p, n in conns.items())}.combout(y));\nendmodule\n")
                out[f"gxt1_{port[-1]}_n{src}_{kind}"] = (
                    v, [f"set_location_assignment {lc(10, 10, src)} -to u0",
                        f"set_location_assignment {lc(10, 10, 6)} -to u1", pin],
                    f"tier1 u0@N{src} -> u1.{port}")
    return out


def bits(name):
    return set(cc.load_plane_only(name).keys.tolist())


def diff(a, b):
    A, B = bits(a), bits(b)
    return sorted(A - B), sorted(B - A)


def build_all(names, jobs):
    def one(n):
        f = fz.build_one(n)
        for sub in ("quartus/db", "quartus/incremental_db"):   # regenerable; the 5k-design sweep hit ENOSPC
            shutil.rmtree(CORPUS / n / sub, ignore_errors=True)
        (CORPUS / n / "quartus" / "build.rbf").unlink(missing_ok=True)
        log.info("%s: %s", n, "ok" if f is None else f"FAIL at {f}")
        return n, f
    with ThreadPoolExecutor(jobs) as ex:
        return dict(ex.map(one, names))


def tier(jobs):
    ds = tier_designs()
    for n, (v, q, p) in ds.items():
        write_design(n, v, q, p)
    res = build_all([n for n in ds if not (CORPUS / n / "routing.rcf").exists()], jobs)
    for n, f in res.items():
        if f:
            log.info("BUILD FAIL %s at %s", n, f)
    rep = {}
    for n in sorted(ds):
        if n.endswith("_s") and (CORPUS / n / "routing.rcf").exists():
            b = n[:-2] + "_b"
            if not (CORPUS / b / "routing.rcf").exists():
                continue
            on, off = diff(n, b)
            rep[n] = {"only_spec": on, "only_base": off}
            log.info("%s: only-spec %d only-base %d", n, len(on), len(off))
    (REPO / "tmp" / "cycloneiv_forced_tier.json").write_text(json.dumps(rep))


LAB = (10, 10)
PFX = "gxll"          # design-name prefix; X10 Y10 keeps the original names


SNK_DX = 0            # sink LAB = (LAB x + SNK_DX, LAB y); 0 = same-LAB LOCAL_LINE grid
SMALL = False         # Tier-0/1 style: sources/sinks N in {0, 2, 4} only


def lab_file(suffix=""):
    if PFX.startswith("gxnb"):
        return REPO / "tmp" / f"cycloneiv_forced_{PFX}{'_small' if SMALL else ''}{suffix}.json"
    return REPO / "tmp" / (f"cycloneiv_forced_lab{'' if PFX == 'gxll' else '_' + PFX[4:]}{suffix}.json")


def pair_designs(pairs):
    """Same-LAB LOCAL_LINE grid: u0@N<src> -> u1@N<snk>, constant masks, base = u1 input open."""
    out = {}
    pin = "set_location_assignment PIN_B9 -to y"
    for src, snk in pairs:
        for kind in ("s", "b"):
            conn = ".dataa(u0_o), " if kind == "s" else ""
            v = ("module top(output y);\n  wire u0_o;\n"
                 '  cycloneiv_lcell_comb #(.lut_mask(16\'h0000), .sum_lutc_input("datac"), .dont_touch("on"))\n'
                 "    u0 (.combout(u0_o));\n"
                 '  cycloneiv_lcell_comb #(.lut_mask(16\'hFFFF), .sum_lutc_input("datac"), .dont_touch("on"))\n'
                 f"    u1 ({conn}.combout(y));\nendmodule\n")
            out[f"{PFX}_{src:02d}_{snk:02d}_{kind}"] = (
                v, [f"set_location_assignment {lc(*LAB, src)} -to u0",
                    f"set_location_assignment {lc(LAB[0] + SNK_DX, LAB[1], snk)} -to u1", pin], f"LOCAL_LINE u0@N{src} -> u1@N{snk}")
    return out


def rcf_hop(name):
    """(LOCAL_LINE I, port) the RCF reports for net u0_o, or None."""
    t = (CORPUS / name / "routing.rcf").read_text()
    m = re.search(r"signal_name = u0_o \{\s*(\w+):X(\d+)Y(\d+)S0I(\d+);\s*dest = \( u1, \w+ \), route_port = (\w+);", t)
    return None if not m else [m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)]


def rcf_path(name):
    """Every RCF element of net u0_o up to its dest (u1, port): ([type, x, y, I], ...) + port."""
    t = (CORPUS / name / "routing.rcf").read_text()
    m = re.search(r"signal_name = u0_o \{\n(.*?)\tdest = \( u1, \w+ \), route_port = (\w+);", t, re.S)
    if not m:
        return None
    els = re.findall(r"\t(\w+):X(\d+)Y(\d+)S0I(\d+);", m.group(1))
    return {"path": [[e[0], int(e[1]), int(e[2]), int(e[3])] for e in els], "port": m.group(2)}


def lab(jobs):
    ns = (0, 2, 4) if SMALL else range(0, 32, 2)
    pairs = [(a, b) for a in ns for b in ns if SNK_DX or a != b]
    ds = pair_designs(pairs)
    for n, (v, q, p) in ds.items():
        write_design(n, v, q, p)
    build_all([n for n in ds if not (CORPUS / n / "routing.rcf").exists()], jobs)
    res = {}
    for a, b in pairs:
        n = f"{PFX}_{a:02d}_{b:02d}"
        if not ((CORPUS / (n + "_s") / "routing.rcf").exists() and (CORPUS / (n + "_b") / "routing.rcf").exists()):
            log.info("MISSING build %s", n)
            continue
        on, off = diff(n + "_s", n + "_b")
        res[n] = {"src": a, "snk": b, "hop": rcf_hop(n + "_s"), "rcf": rcf_path(n + "_s"), "on": on, "off": off}
    lab_file().write_text(json.dumps(res))
    log.info("lab grid: %d / %d pairs diffed", len(res), len(pairs))


def rebuild(frac, seed, jobs):
    """Rebuild a random fraction of the grid (specimen + base); every bit set must be identical."""
    import random
    res = json.loads(lab_file().read_text())
    names = sorted(res)
    pick = random.Random(seed).sample(names, max(1, int(len(names) * frac)))
    build_all([n + k for n in pick for k in ("_s", "_b")], jobs)
    bad = 0
    for n in pick:
        on, off = diff(n + "_s", n + "_b")
        if on != res[n]["on"] or off != res[n]["off"] or rcf_path(n + "_s") != res[n]["rcf"]:
            bad += 1
            log.error("UNSTABLE %s", n)
    log.info("rebuild: %d pairs, %d unstable", len(pick), bad)


def lab_table(res):
    """{(src, snk): (C, D, Q, P)}: C/D depend on source only, Q on sink+port, P on (source, sink)."""
    t = {}
    for v in res.values():
        on = sorted(v["on"])
        c = [b for b in on if b // 10000 == 419]
        d = [b for b in on if b // 10000 == 425]
        rest = [b for b in on if b not in c + d]
        if len(c) != 1 or len(d) != 1 or len(rest) != 2:
            log.error("unexpected band layout %s", on)
            sys.exit(2)
        t[(v["src"], v["snk"])] = {"C": c[0], "D": d[0], "P": rest[0], "Q": rest[1], "port": v["hop"][4]}
    return t


def predict(tab, src, snk):
    """Bit set for a held-out pair from the training table: C/D by source, Q by (sink, port),
    P additive h(src) + g(snk).  A PREDICTION only - the held-out build decides."""
    ref = [(a, b) for (a, b) in tab if a == src]
    c, d, port = tab[ref[0]]["C"], tab[ref[0]]["D"], tab[ref[0]]["port"]
    q = next((t["Q"] for (a, b), t in tab.items() if b == snk and t["port"] == port), None)
    # P = P(src, s0) + P(s', snk) - P(s', s0) over a source s' seen at both sinks
    p = None
    for (a, b) in ref:
        for (a2, b2), t2 in tab.items():
            if a2 != src and b2 == snk and (a2, b) in tab and tab[(a2, b)]["port"] == tab[(a2, snk)]["port"] == port:
                p = tab[(src, b)]["P"] + t2["P"] - tab[(a2, b)]["P"]
                break
        if p is not None:
            break
    return sorted(x for x in (c, d, p, q) if x is not None) if p is not None and q is not None else None


def holdout(frac, seed, jobs):
    import random
    res = json.loads(lab_file().read_text())
    tab = lab_table(res)
    keys = sorted(tab)
    held = random.Random(seed).sample(keys, int(len(keys) * frac))
    train = {k: v for k, v in tab.items() if k not in held}
    pred = {k: predict(train, *k) for k in held}
    names = [f"{PFX}_{a:02d}_{b:02d}" for a, b in held]
    build_all([n + k for n in names for k in ("_s", "_b")], jobs)
    hit = miss = nopred = 0
    for (a, b), n in zip(held, names):
        on, off = diff(n + "_s", n + "_b")
        if pred[(a, b)] is None:
            nopred += 1
            log.info("NO PREDICTION %s", n)
        elif pred[(a, b)] == on and not off:
            hit += 1
        else:
            miss += 1
            log.info("MISS %s predicted %s built %s", n, pred[(a, b)], on)
    log.info("holdout: %d pairs, hit %d, miss %d, no-prediction %d", len(held), hit, miss, nopred)
    lab_file("_table").write_text(
        json.dumps({f"{a},{b}": v for (a, b), v in sorted(tab.items())}))


def compare(labs):
    """Each LAB's grid vs X10 Y10 in (frame, v) coordinates: best single (dframe, dv) offset, then
    count pairs whose bit set equals X10's shifted by it; every other pair is listed."""
    import collections
    nv = cc.load_plane_only("gxll_00_02_s").shape[1]
    ref = json.loads((REPO / "tmp" / "cycloneiv_forced_lab.json").read_text())
    fv = lambda bs: sorted((b // nv, b % nv) for b in bs)   # noqa: E731
    for lb in labs:
        x, y = lb
        f = REPO / "tmp" / f"cycloneiv_forced_lab_{x}x{y}.json"
        res = json.loads(f.read_text())
        offs = collections.Counter()
        for k, v in res.items():
            r = ref.get(k.replace(f"gxll{x}x{y}", "gxll"))
            if r and len(r["on"]) == len(v["on"]):
                for (f1, v1), (f0, v0) in zip(fv(v["on"]), fv(r["on"])):
                    offs[(f1 - f0, v1 - v0)] += 1
        (df, dv), cnt = offs.most_common(1)[0]
        same, bad = 0, []
        for k, v in sorted(res.items()):
            r = ref[k.replace(f"gxll{x}x{y}", "gxll")]
            want = [(a + df, b + dv) for a, b in fv(r["on"])]
            if want == fv(v["on"]) and not v["off"]:
                same += 1
            else:
                bad.append(k)
        hop_same = sum(1 for k, v in res.items() if v["hop"] and v["hop"][3:] == ref[k.replace(f"gxll{x}x{y}", "gxll")]["hop"][3:])
        log.info("LAB X%d Y%d vs X10 Y10: best offset (dframe %d, dv %d) %d bit votes; %d / %d pairs match; "
                 "hop (I, port) identical %d / %d", x, y, df, dv, cnt, same, len(res), hop_same, len(res))
        for k in bad:
            log.info("  NOMATCH %s: LAB %s vs X10Y10 %s", k, fv(res[k]["on"]), fv(ref[k.replace(f"gxll{x}x{y}", "gxll")]["on"]))


def compare_nb(refname, others):
    """Neighbour-LAB grids vs a reference grid (tmp/cycloneiv_forced_<name>.json): best single
    (dframe, dv) offset, matched pairs, every non-match listed, plus RCF path (type, I) equality."""
    import collections
    nv = cc.load_plane_only("gxll_00_02_s").shape[1]
    ld = lambda n: json.loads((REPO / "tmp" / f"cycloneiv_forced_{n}.json").read_text())   # noqa: E731
    fv = lambda bs: sorted((b // nv, b % nv) for b in bs)                                  # noqa: E731
    ref = ld(refname)
    rk = lambda k, pf, rpf: k.replace(pf, rpf, 1)                                          # noqa: E731
    for o in others:
        res = ld(o)
        pf, rpf = o.split("_small")[0], refname.split("_small")[0]
        offs = collections.Counter()
        for k, v in res.items():
            r = ref.get(rk(k, pf, rpf))
            if r and len(r["on"]) == len(v["on"]):
                for (f1, v1), (f0, v0) in zip(fv(v["on"]), fv(r["on"])):
                    offs[(f1 - f0, v1 - v0)] += 1
        (df, dv), cnt = offs.most_common(1)[0]
        same, bad, pathsame = 0, [], 0
        for k, v in sorted(res.items()):
            r = ref[rk(k, pf, rpf)]
            want = [(a + df, b + dv) for a, b in fv(r["on"])]
            if want == fv(v["on"]) and not v["off"]:
                same += 1
            else:
                bad.append(k)
            sig = lambda x: ([(e[0], e[3]) for e in x["path"]], x["port"]) if x else None   # noqa: E731
            pathsame += sig(v["rcf"]) == sig(r["rcf"])
        log.info("%s vs %s: offset (dframe %d, dv %d) %d votes; %d / %d pairs match; RCF (type, I, port) path identical %d / %d",
                 o, refname, df, dv, cnt, same, len(res), pathsame, len(res))
        for k in bad:
            log.info("  NOMATCH %s: %s vs ref %s | paths %s / %s", k, fv(res[k]["on"]), fv(ref[rk(k, pf, rpf)]["on"]),
                     res[k]["rcf"], ref[rk(k, pf, rpf)]["rcf"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("tier", "lab", "rebuild", "holdout", "compare", "compare_nb"))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--lab", default="10,10", help="LAB X,Y for lab/rebuild/holdout")
    ap.add_argument("--dx", type=int, default=0, help="sink LAB column offset (neighbour-LAB grid)")
    ap.add_argument("--small", action="store_true", help="N in {0,2,4} only")
    a = ap.parse_args()
    global LAB, PFX, SNK_DX, SMALL
    LAB = tuple(int(v) for v in a.lab.split(","))
    SNK_DX, SMALL = a.dx, a.small
    PFX = ("gxll" if LAB == (10, 10) else f"gxll{LAB[0]}x{LAB[1]}") if not a.dx else f"gxnb{LAB[0]}x{LAB[1]}d{a.dx}"
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    fz.log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_forced.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
        fz.log.addHandler(h)
    if a.cmd == "tier":
        tier(a.jobs)
    elif a.cmd == "lab":
        lab(a.jobs)
    elif a.cmd == "compare_nb":
        compare_nb("gxnb10x10d1", ["gxnb58x30d1", "gxnb37x60d1", "gxnb100x75d1", "gxnb6x10d2"])
    elif a.cmd == "compare":
        compare([(58, 30), (37, 60), (100, 75)])
    elif a.cmd == "rebuild":
        rebuild(0.1, 20261028, a.jobs)
    else:
        holdout(0.1, 20261029, a.jobs)


if __name__ == "__main__":
    main()
