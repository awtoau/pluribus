#!/usr/bin/env python3.15t
"""Cyclone IV GX LAB control-line specimens (clock / ena / aclr / sclr / sload / asdata), RAW cram diff (#141).

Pair = base + specimen differing in ONE thing; answer = set bits only in one plane, as (frame, v).
No Dec.active / asm decode. Design prefix gxct_<lab>_<set>_<id>[_b|_s]; lab a=X10Y10 b=X58Y30 c=X37Y60 d=X100Y75.
Control signals feed one far FF (other LAB) in both builds, so the pin / clock-tree side is the same.
Evidence rows go to the family DB (evidence_io.record_specimen); bitstreams are pruned after the diff.

  python3.15t scripts/cycloneiv_ctrl.py gen     <sets> [--labs a,b,c,d]
  python3.15t scripts/cycloneiv_ctrl.py build   <sets> [--labs ..] [--jobs N]
  python3.15t scripts/cycloneiv_ctrl.py diff    <sets> [--labs ..]      # diff -> DB, then prune
  python3.15t scripts/cycloneiv_ctrl.py rebuild <sets> --frac 0.1       # rebuild a fraction, bits must be identical
  python3.15t scripts/cycloneiv_ctrl.py compare <sets>                  # per pair: other LABs vs lab a, one (frame, v) offset
Sets: clk clkpin ena aclr sclr sload asdata pos pos2 idle.   Log tmp/logs/cycloneiv_ctrl.log
"""
import argparse
import collections
import datetime
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(Path(__file__).resolve().parent.parent / "databases" / "cycloneiv" / "gx150.db"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_fuzz as fz  # noqa: E402
import toolchain  # noqa: E402

log = logging.getLogger("cycloneiv_ctrl")
CORPUS = REPO / "corpus" / "cycloneiv"
DEVICE = "EP4CGX150DF31C7"
FAMILY, DEV = "cycloneiv", "EP4CGX150"
DB_PATH = REPO / "databases" / "cycloneiv" / "gx150.db"
LABS = {"a": (10, 10), "b": (58, 30), "c": (37, 60), "d": (100, 75)}
FAR = {"a": (58, 30), "b": (10, 10), "c": (10, 10), "d": (10, 10)}   # far FF LAB: never the LAB under test
PIN = {"D": "A11", "D2": "A15", "A": "W15", "B": "V15", "E": "A15", "E2": "AA17", "C": "AD22", "C2": "AJ16", "S": "AK13",
       "S2": "AK16", "L": "B15", "L2": "K15", "M": "L15"}
OUT_PINS = ["B9", "A13", "A14", "A16", "A18", "A19", "B13", "B16", "C16", "C17", "C18", "C19"]
LOG_OF_FIRST = 4          # keep full bitstreams for the first 4 pairs of each set
DISK_FLOOR_GB = 12


def ff(le, **ctl):
    d = {"le": le, "clk": "A"}
    d.update(ctl)
    return d


def lab_ff_name(k):
    return f"r{k}"


SRC_ORDER = ["KA", "KB", "E", "E2", "C", "C2", "S", "L", "M"]   # local LUT sources of the control nets
SRC_MASK = {"KA": "AAAA", "KB": "5555", "E": "8888", "E2": "7777", "C": "6666", "C2": "9999", "S": "EEEE",
            "L": "1111", "M": "CCCC"}


def src_le(cfg, sig):
    """LE of the source LUT of control net `sig`: layout 1 counts down from LE15, layout 2 up from LE0."""
    i = cfg["srcs"].index(sig)
    return 15 - i if cfg.get("layout", 1) == 1 else i


def far_ctl(cfg):
    """Far FFs consume every local source so the source LUTs (and their routes) are in base and specimen alike."""
    srcs = cfg.get("srcs", [])
    ctl1 = {"clk": "KB" if "KB" in srcs else "KA" if "KA" in srcs else "B"}
    for key, sig in (("ena", "E"), ("clrn", "C"), ("sclr", "S"), ("sload", "L"), ("asdata", "M")):
        if sig in srcs:
            ctl1[key] = sig
    ctl2 = {"clk": "KA" if "KA" in srcs else "A"}
    for key, sig in (("ena", "E2"), ("clrn", "C2")):
        if sig in srcs:
            ctl2[key] = sig
    if "KB" in srcs and "KA" in srcs:
        ctl2["clk"] = "KA"
    return ctl1, ctl2


def verilog(cfg):
    """cfg: {'ffs': [ff...], 'srcs': [control sources], 'layout', 'luts': [le...] chain, 'chainff'}; far FFs always."""
    pins, body, outs = set(), [], []
    srcs = cfg.get("srcs", [])
    f1, f2 = far_ctl(cfg)

    def ffinst(nm, d, ctl, q):
        ports = [f".d({d})", f".q({q})"]
        for key in ("clk", "ena", "clrn", "sclr", "sload", "asdata"):
            v = ctl.get(key)
            if v:
                n = v.lstrip("~")
                if n in ("A", "B"):
                    pins.add(n)
                ports.append(f".{'clrn' if key == 'clrn' else key}({v})")
        return f'  dffeas #(.power_up("low"), .is_wysiwyg("true")) {nm} ({", ".join(ports)});'

    lutf = ('  cycloneiv_lcell_comb #(.lut_mask(16\'h{m}), .sum_lutc_input("datac"), .dont_touch("on"))\n'
            "    {nm} (.dataa({a}), {b}.combout({o}));")
    pins.add("D")
    if srcs:
        pins.add("D2")
    for sg in srcs:
        body.append(f"  wire {sg};")
        body.append(lutf.format(m=SRC_MASK[sg], nm=f"s{sg}", a="D", b=".datab(D2), ", o=sg))
    prev = "D"
    for k in cfg.get("luts", []):          # LUT-only (or LUT+FF when chainff) chain through D
        nm = f"u{k}"
        body.append(f"  wire {nm}_o;")
        body.append(lutf.format(m="AAAA", nm=nm, a=prev, b="", o=f"{nm}_o"))
        prev = f"{nm}_o"
        if cfg.get("chainff"):
            body.append(f"  wire {nm}_q;")
            body.append(ffinst(f"f{k}", prev, {"clk": "KA"}, f"{nm}_q"))
            prev = f"{nm}_q"
    if cfg.get("luts"):
        outs.append(("yc", prev))
    for fcfg in cfg.get("ffs", []):
        k = fcfg["le"]
        body.append(f"  wire l{k}_o, q{k};")
        body.append(lutf.format(m="AAAA", nm=f"l{k}", a="D", b="", o=f"l{k}_o"))
        body.append(ffinst(f"r{k}", f"l{k}_o", fcfg, f"q{k}"))
        outs.append((f"y{k}", f"q{k}"))
    body.append("  wire fl_o, fq1, fq2;")
    body.append(lutf.format(m="AAAA", nm="fl", a="D", b="", o="fl_o"))
    body.append(ffinst("far1", "fl_o", f1, "fq1"))
    body.append(ffinst("far2", "fl_o", f2, "fq2"))
    outs += [("yf1", "fq1"), ("yf2", "fq2")]
    ins = ", ".join(sorted(pins))
    ports = ", ".join(f"output {o}" for o, _ in outs)
    v = f"module top(input {ins}, {ports});\n" + "\n".join(body) + "\n"
    v += "".join(f"  assign {o} = {n};\n" for o, n in outs) + "endmodule\n"
    return v, sorted(pins), [o for o, _ in outs]


def design_files(lab, cfg):
    v, pins, outs = verilog(cfg)
    x, y = LABS[lab]
    fx, fy = FAR[lab]
    q = []
    for k in [f["le"] for f in cfg.get("ffs", [])]:
        q += [f"set_location_assignment LCCOMB_X{x}_Y{y}_N{2 * k} -to l{k}",
              f"set_location_assignment FF_X{x}_Y{y}_N{2 * k + 1} -to r{k}"]
    for sg in cfg.get("srcs", []):
        q.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{2 * src_le(cfg, sg)} -to s{sg}")
    for k in cfg.get("luts", []):
        q.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{2 * k} -to u{k}")
        if cfg.get("chainff"):
            q.append(f"set_location_assignment FF_X{x}_Y{y}_N{2 * k + 1} -to f{k}")
    q += [f"set_location_assignment LCCOMB_X{fx}_Y{fy}_N0 -to fl",
          f"set_location_assignment FF_X{fx}_Y{fy}_N1 -to far1",
          f"set_location_assignment FF_X{fx}_Y{fy + 2}_N1 -to far2"]
    q += [f"set_location_assignment PIN_{PIN[s]} -to {s}" for s in pins if s in PIN]
    q += [f"set_location_assignment PIN_{OUT_PINS[i]} -to {o}" for i, o in enumerate(outs)]
    return v, q


def write_design(name, v, qsf, purpose, rcf=None):
    d = CORPUS / name
    if (d / "routing.rcf").exists() or (d / "bitstream.rbf").exists():
        return
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "src" / "top.v").write_text(v)
    q = list(qsf)
    if rcf:        # the base build's own routing pins every shared net; only the new connection routes freely
        (d / "src" / "force.rcf").write_text(rcf)
        q = ["set_global_assignment -name ROUTING_BACK_ANNOTATION_MODE NORMAL",
             "set_global_assignment -name ROUTING_BACK_ANNOTATION_FILE ../src/force.rcf"] + q
    q = q + ["set_global_assignment -name AUTO_GLOBAL_CLOCK OFF",
                     "set_global_assignment -name AUTO_GLOBAL_REGISTER_CONTROLS OFF",
                     "set_global_assignment -name SEED 1", 'set_global_assignment -name FITTER_EFFORT "FAST FIT"']
    ver = re.search(r"quartus-([\d.]+)", toolchain.quartus_bin())
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "{purpose}"\nexercises = {fz.toml_list(["ctrl"])}\n'
        f"qsf = {fz.toml_list(q)}\ndevice = \"{DEVICE}\"\ntool = \"quartus\"\n"
        f'tool_version = "{ver.group(1) if ver else "unknown"}"\nbuilt = "{datetime.date.today().isoformat()}"\n')


# ── experiment definitions: pairs (set, id, base_key, base_cfg, spec_cfg) ─────────────────────────────

def pairs_of(sets):
    P = []

    def add(s, i, bk, base, spec):
        P.append({"set": s, "id": i, "basekey": bk, "base": base, "spec": spec})

    def cfg(ffs, srcs, **kw):
        return dict({"ffs": ffs, "srcs": srcs}, **kw)

    for s in sets:
        if s == "clk":       # LAB clock line from local sources KA / KB
            S = ["KA", "KB"]
            add(s, "KB", "1", cfg([ff(0, clk="KA")], S), cfg([ff(0, clk="KB")], S))
            b2 = cfg([ff(0, clk="KA"), ff(1, clk="KA")], S)
            add(s, "ff1KB", "2", b2, cfg([ff(0, clk="KA"), ff(1, clk="KB")], S))
            add(s, "bothKB", "2", b2, cfg([ff(0, clk="KB"), ff(1, clk="KB")], S))
        elif s == "clkpin":   # dedicated clock pins A / B (global network side) and ~clk
            b1 = {"ffs": [ff(0)], "srcs": []}
            add(s, "B", "1", b1, {"ffs": [ff(0, clk="B")], "srcs": []})
            add(s, "inv", "1", b1, {"ffs": [ff(0, clk="~A")], "srcs": []})
            b2 = {"ffs": [ff(0), ff(1)], "srcs": []}
            add(s, "ff1B", "2", b2, {"ffs": [ff(0), ff(1, clk="B")], "srcs": []})
        elif s in ("ena", "aclr", "sclr", "sload"):
            key, sig, sig2 = {"ena": ("ena", "E", "E2"), "aclr": ("clrn", "C", "C2"), "sclr": ("sclr", "S", None),
                              "sload": ("sload", "L", None)}[s]
            S = ["KA", sig] + ([sig2] if sig2 else []) + (["M"] if s == "sload" else [])
            extra = {"asdata": "M"} if s == "sload" else {}
            c = lambda *ffs: cfg(list(ffs), S)   # noqa: E731
            f0 = lambda **k: ff(0, clk="KA", **k)   # noqa: E731
            f1 = lambda **k: ff(1, clk="KA", **k)   # noqa: E731
            add(s, "one", "1", c(f0()), c(f0(**{key: sig}, **extra)))
            b2 = c(f0(**{key: sig}, **extra), f1())
            add(s, "same", "2", b2, c(f0(**{key: sig}, **extra), f1(**{key: sig}, **extra)))
            if sig2:      # sclr / sload: one per LAB (fitter legality), no second line
                add(s, "line2", "3", c(f0(**{key: sig}, **extra), f1(**{key: sig}, **extra)),
                    c(f0(**{key: sig}, **extra), f1(**{key: sig2}, **extra)))
        elif s == "asdata":
            S = ["KA", "L", "M", "E"]    # asdata source M -> E (asdata is mandatory once sload is used)
            add(s, "ME", "1", cfg([ff(0, clk="KA", sload="L", asdata="M")], S), cfg([ff(0, clk="KA", sload="L", asdata="E")], S))
        elif s in ("pos", "pos2"):
            S = ["KA", "KB", "E", "C", "S", "L", "M"]
            lay = 1 if s == "pos" else 2
            ks = range(0, 8) if s == "pos" else range(8, 16)      # layout 1 sources at LE15..9, layout 2 at LE0..6
            c = lambda f: cfg([f], S, layout=lay)   # noqa: E731
            for k in ks:
                b = c(ff(k, clk="KA"))
                add(s, f"{k:02d}clkKB", f"{k:02d}", b, c(ff(k, clk="KB")))
                add(s, f"{k:02d}ena", f"{k:02d}", b, c(ff(k, clk="KA", ena="E")))
                add(s, f"{k:02d}aclr", f"{k:02d}", b, c(ff(k, clk="KA", clrn="C")))
                add(s, f"{k:02d}sclr", f"{k:02d}", b, c(ff(k, clk="KA", sclr="S")))
                add(s, f"{k:02d}sload", f"{k:02d}", b, c(ff(k, clk="KA", sload="L", asdata="M")))
        elif s == "idle":
            S = ["KA"]
            empty = {"luts": [], "srcs": S}
            for n in range(1, 16):
                lut = {"luts": list(range(n)), "srcs": S}
                fff = {"luts": list(range(n)), "chainff": True, "srcs": S}
                add(s, f"lut{n:02d}", "e", empty, lut)
                add(s, f"ff{n:02d}", "e", empty, fff)
                add(s, f"lutff{n:02d}", f"l{n:02d}", lut, fff)
        else:
            raise SystemExit(f"unknown set {s}")
    return P


def names(lab, p):
    return f"gxct_{lab}_{p['set']}_b{p['basekey']}", f"gxct_{lab}_{p['set']}_{p['id']}"


def gen(sets, labs, phase="base"):
    """phase base: write base designs; phase spec: write specs seeded with their base's routing.rcf."""
    n = 0
    for lab in labs:
        for p in pairs_of(sets):
            bn, sn = names(lab, p)
            if phase == "base":
                v, q = design_files(lab, p["base"])
                write_design(bn, v, q, f"LAB control base {p['set']}/{p['basekey']} at lab {lab}")
            else:
                rcf_f = CORPUS / bn / "routing.rcf"
                if not rcf_f.exists():
                    log.info("no base rcf for %s", bn)
                    continue
                v, q = design_files(lab, p["spec"])
                write_design(sn, v, q, f"LAB control specimen {p['set']}/{p['id']} at lab {lab}", rcf=rcf_f.read_text())
            n += 1
    log.info("gen %s: %d designs", phase, n)


def all_designs(sets, labs, which):
    out = []
    for lab in labs:
        for p in pairs_of(sets):
            nm = names(lab, p)[0 if which == "base" else 1]
            if nm not in out:
                out.append(nm)
    return out


def free_gb():
    return shutil.disk_usage(REPO).free / 2**30


def build_one(n):
    d = CORPUS / n
    if (d / "bitstream.rbf").exists():
        return n, None
    f = fz.build_one(n)
    for sub in ("quartus/db", "quartus/incremental_db", "quartus"):
        shutil.rmtree(d / sub, ignore_errors=True)
    log.info("%s: %s", n, "ok" if f is None else f"FAIL at {f}")
    return n, f


def build(sets, labs, jobs):
    import build_pool
    for phase in ("base", "spec"):
        gen(sets, labs, phase)
        todo = [n for n in all_designs(sets, labs, phase) if not (CORPUS / n / "bitstream.rbf").exists()
                and (CORPUS / n / "design.toml").exists()]
        log.info("build %s: %d designs, disk free %.1f GB", phase, len(todo), free_gb())
        res = build_pool.map_adaptive(build_one, todo, per_job_gb=1.5, max_workers=jobs, disk_floor_gb=DISK_FLOOR_GB)
        fails = [n for n, f in res if f]
        log.info("build %s done: %d ok, %d fail %s", phase, len(res) - len(fails), len(fails), fails[:10])


def plane_keys(name):
    return set(cc.load_plane_only(name).keys.tolist())


def nv():
    return cc.load_plane_only(next(p.name for p in sorted(CORPUS.glob("gxct_*")) if (p / "bitstream.rbf").exists())).shape[1]


def prune(name, keep_full):
    d = CORPUS / name
    if keep_full:
        return
    for f in ("bitstream.rbf", "postfit.vo", "fit.rpt", "build.pin"):
        (d / f).unlink(missing_ok=True)
    shutil.rmtree(d / "logs", ignore_errors=True)


def connect():
    import db
    return db.engine()


def head():
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()


def diff(sets, labs):
    from provenance import evidence_io as E
    eng = connect()
    commit = head()
    NV = None
    for lab in labs:
        for s in sets:
            ps = [p for p in pairs_of([s])]
            for i, p in enumerate(ps):
                bn, sn = names(lab, p)
                if not (CORPUS / bn / "bitstream.rbf").exists() or not (CORPUS / sn / "bitstream.rbf").exists():
                    continue
                A, B = plane_keys(sn), plane_keys(bn)
                NV = NV or cc.load_plane_only(sn).shape[1]
                on, off = sorted(A - B), sorted(B - A)
                meta = {"set": s, "id": p["id"], "lab": lab, "xy": list(LABS[lab]), "base_name": bn}
                with eng.begin() as conn:
                    E.ensure_family(conn, FAMILY)
                    from provenance import corpus as CO
                    E.record_specimen(conn, FAMILY, DEV, f"ctrl_{lab}_{s}_{p['id']}", bn, on, off, meta,
                                      f"cycloneiv_ctrl:{s}:{lab}", "scripts/cycloneiv_ctrl.py", commit, NV,
                                      build_base=CO.build_id(conn, FAMILY, bn), build_spec=CO.build_id(conn, FAMILY, sn))
                log.info("%s/%s@%s: only-spec %d only-base %d  %s", s, p["id"], lab, len(on), len(off),
                         [(b // NV, b % NV) for b in on][:12])
    log.info("diff: recorded")


def prune_all(sets, labs):
    for lab in labs:
        for s in sets:
            seen = set()
            for i, p in enumerate(pairs_of([s])):
                bn, sn = names(lab, p)
                for nm in (bn, sn):
                    if nm in seen:
                        continue
                    seen.add(nm)
                    prune(nm, keep_full=len(seen) <= 2 * LOG_OF_FIRST and lab == "a")


def rows(sets, labs):
    """{(lab,set,id): (on, off)} from the DB (flat indices)."""
    import sqlite3
    from provenance import evidence_io as E
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    out = {}
    for lab in labs:
        for s in sets:
            for (nm, sb, bb) in c.execute("SELECT name,bits_spec,bits_base FROM evidence WHERE kind='specimen-pair' "
                                          "AND source_ref=?", (f"cycloneiv_ctrl:{s}:{lab}",)):
                out[(lab, s, nm.split("_", 3)[3])] = (E.unpack(sb).tolist(), E.unpack(bb).tolist())
    return out


def compare(sets):
    """Per set and lab: best single (frame, v) offset by vote over all onset pairs vs lab a; reports
    matched / (matched + missing + extra) over only-spec and only-base bits (no equal-count assumption)."""
    NVv = 6368
    fv = lambda bs: sorted((b // NVv, b % NVv) for b in bs)   # noqa: E731
    R = rows(sets, list(LABS))
    for s in sets:
        for lab in "bcd":
            keys = sorted(k for k in R if k[0] == lab and k[1] == s and ("a",) + k[1:] in R)
            offs = collections.Counter()
            for k in keys:
                for (f0, v0) in fv(R[("a",) + k[1:]][0]):
                    for (f1, v1) in fv(R[k][0]):
                        offs[(f1 - f0, v1 - v0)] += 1
            if not offs:
                log.info("compare %s lab %s: no comparable pairs", s, lab)
                continue
            (df, dv), cnt = offs.most_common(1)[0]
            M = X = Y = 0
            for k in keys:
                for side in (0, 1):
                    a = {(f + df, v + dv) for f, v in fv(R[("a",) + k[1:]][side])}
                    b = set(fv(R[k][side]))
                    M += len(a & b); X += len(a - b); Y += len(b - a)
                    if a != b:
                        log.info("  NOMATCH %s %s: missing %s extra %s", k, ("spec", "base")[side],
                                 sorted(a - b)[:6], sorted(b - a)[:6])
            log.info("compare %s lab %s vs a: offset (dframe %d, dv %d) %d votes; bits matched %d / (%d + %d missing + %d extra) = %.1f%%",
                     s, lab, df, dv, cnt, M, M, X, Y, 100.0 * M / max(1, M + X + Y))


def rebuild(sets, labs, frac, seed, jobs):
    import build_pool
    from provenance import evidence_io as E   # noqa: F401
    R = rows(sets, labs)
    keys = sorted(R)
    pick = random.Random(seed).sample(keys, max(1, int(len(keys) * frac)))
    ps = {(lab, p["set"], p["id"]): p for lab in labs for p in pairs_of(sets)}
    todo = []
    for k in pick:
        for nm in names(k[0], ps[k]):
            d = CORPUS / nm
            (d / "bitstream.rbf").unlink(missing_ok=True)
            for sub in ("routing.rcf",):
                (d / sub).unlink(missing_ok=True)
            todo.append(nm)
    todo = list(dict.fromkeys(todo))
    build_pool.map_adaptive(build_one, todo, per_job_gb=1.5, max_workers=jobs, disk_floor_gb=DISK_FLOOR_GB)
    bad = 0
    for k in pick:
        bn, sn = names(k[0], ps[k])
        if not (CORPUS / sn / "bitstream.rbf").exists() or not (CORPUS / bn / "bitstream.rbf").exists():
            log.error("REBUILD FAIL %s", k)
            bad += 1
            continue
        A, B = plane_keys(sn), plane_keys(bn)
        if sorted(A - B) != R[k][0] or sorted(B - A) != R[k][1]:
            bad += 1
            log.error("UNSTABLE %s", k)
    log.info("rebuild: %d pairs, %d unstable", len(pick), bad)
    for nm in todo:
        prune(nm, keep_full=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("gen", "build", "diff", "prune", "rebuild", "compare"))
    ap.add_argument("sets")
    ap.add_argument("--labs", default="a,b,c,d")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 8) - 2))
    ap.add_argument("--frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=20261029)
    a = ap.parse_args()
    sets, labs = a.sets.split(","), a.labs.split(",")
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    for lg in (log, fz.log):
        lg.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_ctrl.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
        fz.log.addHandler(h)
    if a.cmd == "gen":
        gen(sets, labs)
    elif a.cmd == "build":
        build(sets, labs, a.jobs)
    elif a.cmd == "diff":
        diff(sets, labs)
    elif a.cmd == "prune":
        prune_all(sets, labs)
    elif a.cmd == "rebuild":
        rebuild(sets, labs, a.frac, a.seed, a.jobs)
    else:
        compare(sets)


if __name__ == "__main__":
    main()
