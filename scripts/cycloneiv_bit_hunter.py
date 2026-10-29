#!/usr/bin/env python3.15t
"""Cyclone IV single-cell hunter (#141): find bitstream pairs that differ by exactly ONE configuration cell.

Base design pinned in LAB X10Y10 (u0 -> u1, LOCAL_LINE + port forced by RCF); every variant changes ONE
knob (params below).  Full cram planes are cached as diff-from-base; all pairs are compared by symmetric
difference; pairs at distance 2-3 are split by in-between variants (adaptive).  Raw plane diffs only: no decoder.

  cycloneiv_bit_hunter.py calib            # base + 16 LUT-mask variants, report cells per variant
  cycloneiv_bit_hunter.py batch1           # all knobs
  cycloneiv_bit_hunter.py adapt [--budget 100] [--depth 3]
  cycloneiv_bit_hunter.py report           # pairs at distance 1/2/3, hit rate per knob -> tmp/bit_hunter/summary.json
  cycloneiv_bit_hunter.py record           # distance-1 pairs -> evidence rows (source_ref bit_hunter:<knob>)
Cache tmp/bit_hunter/ (not in git).  Log tmp/logs/cycloneiv_bit_hunter.log
"""
import argparse
import collections
import hashlib
import json
import logging
import os
import shutil
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(REPO / "databases" / "cycloneiv" / "gx150.db"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_forced as cf  # noqa: E402
import cycloneiv_fuzz as fz  # noqa: E402
import cycloneiv_lab_modes as lm  # noqa: E402

log = logging.getLogger("cycloneiv_bit_hunter")
CORPUS = cf.CORPUS
TMP = REPO / "tmp" / "bit_hunter"
VARS = TMP / "variants.json"
PLANES = TMP / "planes"
NV = 6368
PINS = {"ina": "A11", "y": "B9"}
GENERATOR = "scripts/cycloneiv_bit_hunter.py"
DISK_FLOOR_GB = 12.0
PORTS = "ABCD"


SRC_MASK = {"KA": "AAAA", "KB": "5555", "E": "8888", "C": "6666", "S": "EEEE", "L": "1111", "M": "CCCC"}
SRC_LE = {"KA": 16, "KB": 18, "E": 20, "C": 22, "S": 24, "L": 26, "M": 28}   # LCCOMB N of each control-source LUT (same LAB as the test LE)
CTL = ("clk", "ena", "clr", "sclr", "sload", "asdata")


def base_params():
    """Family A base: u0 -> u1 over a forced LOCAL_LINE, nothing else in the LAB."""
    lp = lm.legal_ports()
    port = "A" if "A" in lp.get(0, ()) else sorted(lp[0])[0]
    return {"fam": "A", "lab": [10, 10], "src": 0, "snk": 2, "port": port, "smask": "0000", "kmask": "0000",
            "slutc": "datac", "klutc": "datac", "tie": ""}


def base_b(lab=(10, 10)):
    """Family B base: ONE test LE (LUT only) + idle control-source LUTs (dangling outputs) in the same LAB."""
    return {"fam": "B", "lab": list(lab), "le": 1, "kmask": "0000", "klutc": "datac", "tie": "", "ff": 0, "pw": "low",
            "clk": "KA", "ena": "", "clr": "", "sclr": "", "sload": "", "asdata": ""}


def fam_base(p):
    return base_params() if p["fam"] == "A" else base_b(p["lab"])


def pname(p):
    return "gxbh_" + hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:10]


CELL = ('  cycloneiv_lcell_comb #(.lut_mask(16\'h{m}), .sum_lutc_input("{c}"), .dont_touch("on"))\n'
        "    {n} ({ports});\n")


def tied(tie):
    """port -> expression: every port on ina (Quartus rejects a mask depending on an unconnected port), tie knob = constant."""
    return {c: (f"1'b{tie[1]}" if tie[:1] == c else "ina") for c in PORTS}


def verilog(p):
    if p["fam"] == "A":
        bare = p.get("bare")      # bare: unused ports unconnected (mask must ignore them: constants only)
        t = tied(p["tie"])
        if p.get("dn"):       # distinct input pin per LUT port: the fitter cannot swap ports without changing a net
            t = {c: "in" + c.lower() for c in PORTS}
        sink = ", ".join([f".data{p['port'].lower()}(u0_o)"] + ([] if bare else [f".data{c.lower()}({t[c]})" for c in PORTS if c != p["port"]])) + ", .combout(y)"
        src = ", ".join(([] if bare else [f".data{c.lower()}({'in' + c.lower() if p.get('dn') else 'ina'})" for c in PORTS]) + [".combout(u0_o)"])
        v = ("module top(input ina, input inb, input inc, input ind, output y);" if p.get("dn") else "module top(input ina, output y);") + "\n  wire u0_o;\n" + CELL.format(m=p["smask"], c=p["slutc"], n="u0", ports=src)
        v += CELL.format(m=p["kmask"], c=p["klutc"], n="u1", ports=sink)
        if p.get("k2"):      # second sink drives pin y2 (a dangling cell is swept); port "" = placed but unconnected
            p2 = p["k2"][1]
            s2 = ", ".join(([f".data{p2.lower()}(u0_o)"] if p2 else []) + ([] if bare else [f".data{c.lower()}(ina)" for c in PORTS if c != p2]) + [".combout(y2)"])
            v = v.replace("output y)", "output y, output y2)") + CELL.format(m="FFFF", c="datac", n="u2", ports=s2)
        return v + "endmodule\n"
    t = tied(p["tie"])
    g = lambda k, d=None: p.get(k, d)   # noqa: E731  optional knobs: absent = default, so existing variant names stay valid
    nm = g("nm", "")
    for c in g("open", ""):
        t[c] = ""
    ta = g("sa", "ina")
    if ta != "ina" and t["A"] == "ina":
        t["A"] = ta
    gclk = g("gclk", None) is not None
    if g("pins"):         # control nets from input pins: in the base each pin already feeds a test-LUT port
        t["B"], t["C"], t["D"] = "enap", "clrp", "sclp"
    ports = "input ina" + (", input enap, input clrp, input sclp" if g("pins") else "") + (", input clkp" if p["clk"] == "PIN" else "") + ", output y" + (", output y2" if g("out") == "both" else "")
    v = f"module top({ports});\n  wire t_o, q;\n"
    for sg, m in SRC_MASK.items():     # control sources exist in every build; output dangles until a control knob uses it
        v += f"  wire {sg};\n" + CELL.format(m=m, c="datac", n=f"s{sg}{nm}", ports=", ".join(f".data{c.lower()}(ina)" for c in PORTS) + f", .combout({sg})")
    if p["le"]:
        pl = ", ".join(f".data{c.lower()}({t[c]})" for c in PORTS if t[c])
        v += CELL.format(m=p["kmask"], c=p["klutc"], n=f"t{nm}", ports=pl + ", .combout(t_o)")
    else:
        v += "  assign t_o = ina;\n"
    if g("fan", 1) == 2:
        v += CELL.format(m="FFFF", c="datac", n=f"ld{nm}", ports=".dataa(t_o), .datab(ina), .datac(ina), .datad(ina), .combout()")
    clk = "clkp" if p["clk"] == "PIN" else p["clk"]
    if p["ff"]:
        ctl = "".join(f", .{k}({p[kk]})" for k, kk in (("ena", "ena"), ("clrn", "clr"), ("sclr", "sclr"), ("sload", "sload"), ("asdata", "asdata")) if p[kk])
        d = ".d(t_o)" if g("ffsrc", "lut") == "lut" else ".d(1'b0), .asdata(t_o), .sload(1'b1)"
        v += f'  dffeas #(.power_up("{p["pw"]}"), .is_wysiwyg("true")) r{nm} ({d}, .clk({clk}), .q(q){ctl});\n'
        v += "  assign y = q;\n" if g("out", "ff") != "both" else "  assign y = t_o;\n  assign y2 = q;\n"
    else:
        v += "  assign y = t_o;\n"
    return v + "endmodule\n"


def qsf(p):
    lab = tuple(p["lab"])
    lc = lambda n: f"LCCOMB_X{lab[0]}_Y{lab[1]}_N{n}"   # noqa: E731
    if p["fam"] == "A":
        q = [f"set_location_assignment {lc(p['src'])} -to u0", f"set_location_assignment {lc(p['snk'])} -to u1"]
        if p.get("k2"):
            q.append(f"set_location_assignment {lc(p['k2'][0])} -to u2")
    else:
        nm = p.get("nm", "")
        k = p.get("slot", 0)
        q = [f"set_location_assignment {lc(SRC_LE[sg])} -to s{sg}{nm}" for sg in SRC_MASK]
        if p["le"]:
            q.append(f"set_location_assignment {lc(2 * k)} -to t{nm}")
        if p["ff"]:
            q.append(f"set_location_assignment FF_X{lab[0]}_Y{lab[1]}_N{2 * k + 1} -to r{nm}")
        if p.get("fan", 1) == 2:
            q.append(f"set_location_assignment {lc(30)} -to ld{nm}")
    q += [f"set_location_assignment PIN_{v} -to {k}" for k, v in PINS.items()]
    if p.get("k2"):
        q.append("set_location_assignment PIN_A13 -to y2")
    if p.get("dn"):
        q += ["set_location_assignment PIN_A15 -to inb", "set_location_assignment PIN_AA17 -to inc", "set_location_assignment PIN_AK13 -to ind"]
    if p.get("pins"):
        q += ["set_location_assignment PIN_A15 -to enap", "set_location_assignment PIN_AA17 -to clrp", "set_location_assignment PIN_AK13 -to sclp"]
    if p.get("clk") == "PIN":
        q.append("set_location_assignment PIN_W15 -to clkp")
    if p.get("out") == "both":
        q.append("set_location_assignment PIN_A13 -to y2")
    q += ["set_global_assignment -name AUTO_GLOBAL_CLOCK " + ("ON" if p.get("gclk") else "OFF"), "set_global_assignment -name AUTO_GLOBAL_REGISTER_CONTROLS OFF"]
    if p["fam"] == "A" or not p.get("boot"):
        q += ["set_global_assignment -name ROUTING_BACK_ANNOTATION_MODE NORMAL",
              "set_global_assignment -name ROUTING_BACK_ANNOTATION_FILE ../src/force.rcf"]
    return q + [f"set_global_assignment -name SEED {p.get('seed', 1)}", 'set_global_assignment -name FITTER_EFFORT "FAST FIT"']


def base_rcf_path(lab, pins=False):
    return TMP / f"base_b{'_pins' if pins else ''}_{lab[0]}x{lab[1]}.rcf"


def boot_of(p):
    """The free-fit build whose routing back-annotates family-B variant p."""
    b = {**base_b(p["lab"]), "ff": 1, "pins": 1} if p.get("pins") else base_b(p["lab"])
    return {**b, "boot": 1}


def write_design(p):
    n = pname(p)
    d = CORPUS / n
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "src" / "top.v").write_text(verilog(p))
    if p["fam"] == "A":
        dests = [("u1", p["port"])] + ([("u2", p["k2"][1])] if p.get("k2") and p["k2"][1] else [])
        (d / "src" / "force.rcf").write_text(lm.rcf_multi(tuple(p["lab"]), lm.ll_of_src()[p["src"]], dests))
    elif not p.get("boot"):
        (d / "src" / "force.rcf").write_text(base_rcf_path(p["lab"], bool(p.get("pins"))).read_text())   # base routing pins every shared net
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "bit_hunter {n}"\nexercises = {fz.toml_list(["bit_hunter"])}\n'
        f"qsf = {fz.toml_list(qsf(p))}\ndevice = \"{cf.DEVICE}\"\ntool = \"quartus\"\n"
        f'tool_version = "25.1"\nbuilt = "{__import__("datetime").date.today().isoformat()}"\n')
    return n


def honoured(n, p):
    if p["fam"] == "B":
        return (CORPUS / n / "routing.rcf").exists()
    f = CORPUS / n / "routing.rcf"
    if not f.exists():
        return False
    import re
    m = re.search(r"signal_name = u0_o \{\n(.*?)\n\}", f.read_text(), re.S)
    if not m:
        return False
    lls = set(re.findall(r"LOCAL_LINE:X\d+Y\d+S0I(\d+)", m.group(1)))
    dests = re.findall(r"dest = \( (\w+), DATA(\w) \)", m.group(1))
    want = sorted([("u1", p["port"])] + ([("u2", p["k2"][1])] if p.get("k2") and p["k2"][1] else []))
    return lls == {str(lm.ll_of_src()[p["src"]])} and sorted(dests) == want


def prune(n):
    d = CORPUS / n
    for sub in ("quartus", "logs"):
        shutil.rmtree(d / sub, ignore_errors=True)
    for fn in ("postfit.vo", "fit.rpt", "build.pin", "bitstream.rbf"):
        (d / fn).unlink(missing_ok=True)


def load_vars():
    return json.loads(VARS.read_text()) if VARS.exists() else {}


def save_vars(v):
    TMP.mkdir(parents=True, exist_ok=True)
    tmp = VARS.with_suffix(".tmp")
    tmp.write_text(json.dumps(v, indent=0))
    tmp.replace(VARS)


def build_variant(p):
    """Build, extract the plane keys to the cache, prune.  Returns the variant record."""
    n = write_design(p)
    f = fz.build_one(n)
    if f:
        log.info("%s: build FAIL at %s params %s", n, f, p)
        shutil.rmtree(CORPUS / n / "quartus", ignore_errors=True)
        return {"name": n, "params": p, "status": "build-fail", "step": f}
    ok = honoured(n, p)
    if p["fam"] == "B" and p.get("boot") and ok:
        shutil.copyfile(CORPUS / n / "routing.rcf", base_rcf_path(p["lab"], bool(p.get("pins"))))
    keys = np.asarray(cc.load_plane_only(n).keys, np.int64)
    prune(n)
    PLANES.mkdir(parents=True, exist_ok=True)
    np.save(PLANES / f"{n}.full.npy", keys)       # replaced by diff-from-base in compact()
    log.info("%s: %d keys, forced honoured %s, params %s", n, len(keys), ok, p)
    return {"name": n, "params": p, "status": "ok" if ok else "refused", "n_keys": int(len(keys))}


def run_variants(plist, jobs):
    import build_pool
    vs = load_vars()
    todo, seen = [], set()
    for p in plist:
        n = pname(p)
        if n not in vs and n not in seen:
            todo.append(p)
            seen.add(n)
    log.info("%d variants requested, %d to build", len(plist), len(todo))
    need, seen_b = [], set()
    for p in todo:
        if p["fam"] == "B" and not p.get("boot"):
            bp = boot_of(p)
            if pname(bp) not in seen_b and not base_rcf_path(bp["lab"], bool(bp.get("pins"))).exists():
                seen_b.add(pname(bp))
                need.append(bp)
    if need:     # every family-B variant is back-annotated with its LAB's base routing: build the bases first
        for p in need:
            r = build_variant(p)
            vs[r["name"]] = r
            if r["status"] != "ok":
                sys.exit(f"family-B base failed: {r}")
        save_vars(vs)
        todo = [p for p in todo if pname(p) not in vs]
    if shutil.disk_usage(REPO).free / 2**30 < DISK_FLOOR_GB:
        sys.exit("disk floor")
    res = build_pool.map_adaptive(build_variant, todo, per_job_gb=2.5, max_workers=jobs or 10, disk_floor_gb=DISK_FLOOR_GB)
    vs = load_vars()
    for r in res:
        vs[r["name"]] = r
    save_vars(vs)
    compact()
    return [r for r in res]


def compact():
    """Full key arrays -> diff-from-base arrays (A = keys only in variant, R = keys only in base)."""
    vs = load_vars()
    bn = pname(base_params())
    bf = PLANES / f"{bn}.full.npy"
    if bf.exists():
        np.save(PLANES / "base.npy", np.load(bf))
        bf.unlink()
    if not (PLANES / "base.npy").exists():
        return
    base = np.load(PLANES / "base.npy")
    for f in list(PLANES.glob("*.full.npy")):
        k = np.load(f)
        np.savez_compressed(PLANES / f.name.replace(".full.npy", ".diff.npz"),
                            A=np.setdiff1d(k, base, assume_unique=True), R=np.setdiff1d(base, k, assume_unique=True))
        f.unlink()
    log.info("cache compacted: %d variant diffs", len(list(PLANES.glob("*.diff.npz"))))


def tagged(n):
    if n == pname(base_params()):
        return frozenset()
    z = np.load(PLANES / f"{n}.diff.npz")
    return frozenset((z["A"] * 2).tolist()) | frozenset((z["R"] * 2 + 1).tolist())


def okvars():
    return {n: v for n, v in load_vars().items() if v["status"] == "ok" and (n == pname(base_params()) or (PLANES / f"{n}.diff.npz").exists())}


def distances(maxd=3):
    vs = okvars()
    names = sorted(vs)
    D = {n: tagged(n) for n in names}
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if abs(len(D[a]) - len(D[b])) > maxd:
                continue
            d = len(D[a] ^ D[b])
            if d <= maxd:
                out.append((d, a, b))
    return sorted(out), D


def knob_of(pa, pb):
    ks = [k for k in sorted(set(pa) | set(pb)) if pa.get(k) != pb.get(k)]
    return "+".join(ks) if ks else "none"


# ---- variant generation -------------------------------------------------------------------------

def batch1():
    b = base_params()
    lp = lm.legal_ports()
    out = [dict(b)]

    def v(**kw):
        out.append({**b, **kw})
    for k in range(16):
        v(kmask=f"{1 << k:04X}")
    for k in range(16):
        v(smask=f"{1 << k:04X}")
    for m in ("0003", "0005", "0011", "0101", "000F", "0055", "00FF", "5555", "AAAA", "FFFF", "0033", "0F0F", "0007", "0015", "001F", "0111"):
        v(kmask=m)
    for s in range(0, 32, 2):
        if s != b["snk"] and s != b["src"] and b["port"] in lp.get(s, ()):
            v(src=s)
    for s in range(0, 32, 2):
        if s != b["snk"] and s != b["src"]:
            v(snk=s)
    for pt in sorted(lp.get(b["src"], ())):
        if pt != b["port"]:
            v(port=pt)
    for pt in PORTS:
        if pt != b["port"]:
            for val in "01":
                v(tie=pt + val)
    v(slutc="cin")
    v(klutc="cin")
    srcs = [s for s in (4, 8, 12, 16, 20, 24, 28) if b["port"] in lp.get(s, ())]
    for s in srcs:
        for k in (6, 10, 14, 18, 22, 26, 30):
            if s != k:
                v(src=s, snk=k)
    for m in ("0001", "0003", "0007", "000F", "001F", "003F", "007F", "00FF"):
        out.append({**b, "kmask": m, "smask": "0001"})
    for k in range(16):
        out.append({**b, "kmask": "5555", "smask": f"{1 << k:04X}"})
    for k in range(16):
        out.append({**b, "kmask": f"{(0x5555 ^ (1 << k)):04X}"})
    # family B: one test LE + idle same-LAB control sources
    c = base_b()

    def w(**kw):
        out.append({**c, **kw})
    out.append(dict(c))
    w(le=0)
    for k in range(16):
        w(kmask=f"{1 << k:04X}")
    for m in ("0003", "0005", "000F", "00FF", "5555", "AAAA", "FFFF"):
        w(kmask=m)
    for pt in PORTS:
        for val in "01":
            w(tie=pt + val)
    w(klutc="cin")
    f1 = {"ff": 1}
    w(**f1)
    w(**f1, pw="high")
    w(**f1, clk="KB")
    w(**f1, clk="~KA")
    w(**f1, ena="E")
    w(**f1, clr="C")
    w(**f1, sclr="S")
    w(**f1, sload="L", asdata="M")
    w(**f1, sload="L", asdata="E")
    w(**f1, ena="E", clr="C")
    w(**f1, ena="E", sclr="S")
    w(**f1, clr="C", sclr="S")
    w(**f1, ena="~E")
    w(**f1, clr="~C")
    w(**f1, sclr="~S")
    w(**f1, sload="~L", asdata="M")
    w(**f1, clk="~KB")
    # Dan's cheap one-change tests (same base routing back-annotated in both builds)
    for k in (1, 7, 15):
        w(slot=k)
        w(**f1, slot=k)
    w(**f1, out="both")
    w(**f1, ffsrc="asdata")
    w(**f1, clr="S")
    for pt in PORTS:
        w(open=pt)
    for tie in ("A0", "A1", "B0"):
        w(kmask="AAAA", tie=tie)
    w(kmask="AAAA")
    w(**f1, clk="PIN")
    w(**f1, clk="PIN", gclk=1)
    w(fan=2)
    w(sa="KB")
    return out


def batch2():
    """Splitters for the multi-cell control diffs: ena/aclr/sclr absent -> constant -> same-LAB signal, other sources, FF clocked from a pin."""
    c = {**base_b(), "ff": 1}
    out = []
    for key, sig, other in (("ena", "E", "KB"), ("clr", "C", "KB"), ("sclr", "S", "KB")):
        for val in ("1'b1", "1'b0", "ina", other):
            out.append({**c, key: val})
        out.append({**c, key: sig})
    out += [{**c, "clk": "KB", "ena": "E"}, {**c, "clk": "~KA", "ena": "E"}, {**c, "clk": "PIN"}, {**c, "clk": "~KB"},
            {**c, "clk": "ina"}, {**c, "clk": "E"}, {**c, "clk": "C"}]
    return out


def batch3():
    """Big saturating batch: family-A (src, snk, port) grid (LOCAL_LINE; diff-of-diffs split the 4-cell sets) + control nets from every source LE."""
    b = base_params()
    lp = lm.legal_ports()
    out = []
    for s in range(0, 32, 2):
        for k in range(0, 32, 2):
            if s != k:
                for pt in sorted(lp.get(s, ())):
                    out.append({**b, "src": s, "snk": k, "port": pt})
    c = {**base_b(), "ff": 1}
    for sg in SRC_MASK:
        for key in ("ena", "clr", "sclr"):
            out.append({**c, key: sg})
        if sg != "KA":
            out.append({**c, "clk": sg})
            out.append({**c, "clk": "~" + sg})
    for k in range(0, 16):
        out.append({**base_b(), "slot": k})
        out.append({**c, "slot": k})
    return out


ALL_LABS = [(10, 10), (58, 30), (37, 60), (100, 75)]


def init_pairs(labs=ALL_LABS):
    """(base, variant, meta): LUT-INIT bit b of every LE k per LAB.  LE 0 via the source mask (src 0), LE k >= 2 via the sink mask."""
    out = []
    for lab in labs:
        b = {**base_params(), "lab": list(lab)}
        for bit in range(16):
            out.append((b, {**b, "smask": f"{1 << bit:04X}"}, {"lab": lab, "le": 0, "bit": bit}))
        for k in range(2, 32, 2):
            bk = {**b, "snk": k}
            for bit in range(16):
                out.append((bk, {**bk, "kmask": f"{1 << bit:04X}"}, {"lab": lab, "le": k // 2, "bit": bit}))
    return out


def clk_pairs(labs=ALL_LABS):
    out = []
    for lab in labs:
        c = {**base_b(lab), "ff": 1}
        out.append((c, {**c, "clk": "~KA"}, {"lab": lab, "what": "clk_polarity"}))
    return out


def round2a():
    return [p for pr in init_pairs() + clk_pairs() for p in pr[:2]]


def round2b():
    """LOCAL_LINE with unconnected ports (bare) + a second sink on the same local line."""
    b = {**base_params(), "bare": 1, "kmask": "0000"}
    lp = lm.legal_ports()
    out = []
    for s in range(0, 32, 2):
        for k in range(0, 32, 2):
            if s != k:
                for pt in sorted(lp.get(s, ())):
                    out.append({**b, "src": s, "snk": k, "port": pt})
    for s in range(0, 32, 4):
        pt = sorted(lp.get(s, ()))[0]
        k1 = 30 if s != 30 else 28
        base = {**b, "src": s, "snk": k1, "port": pt}
        for k2 in range(0, 32, 2):
            if k2 not in (s, k1):
                for p2 in [""] + sorted(lp.get(s, ())):
                    out.append({**base, "k2": [k2, p2]})
    return out


def law():
    """LUT-INIT cell position per (LAB, LE, bit) vs X10Y10 after the naive FX/vy translation; mismatches grouped."""
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of(cf.DEVICE))
    ok = okvars()
    cell = {}
    for pb, pv, m in init_pairs():
        nb, nv = pname(pb), pname(pv)
        if nb in ok and nv in ok:
            cs = pair_cells(tagged(nv), tagged(nb))
            if len(cs) == 1:
                fr, v = divmod(cs[0][0], NV)
                x, y, df, dv = tile_of(g, fr, v)
                cell[(tuple(m["lab"]), m["le"], m["bit"])] = (fr, v, x, y, df, dv)
            else:
                cell[(tuple(m["lab"]), m["le"], m["bit"])] = ("n=%d" % len(cs),)
    ref = {(le, bit): c for (lab, le, bit), c in cell.items() if lab == (10, 10) and len(c) == 6}
    rows, c1 = [], collections.Counter()
    for (lab, le, bit), c in sorted(cell.items()):
        if lab == (10, 10):
            continue
        r = ref.get((le, bit))
        if len(c) != 6 or r is None:
            c1["not1cell" if len(c) != 6 else "noref"] += 1
            continue
        d = (c[4] - r[4], c[5] - r[5])
        c1[(lab, d)] += 1
        if d != (0, 0):
            rows.append({"lab": lab, "le": le, "bit": bit, "ref": r[4:], "here": c[4:], "delta": d})
    log.info("LUT-INIT cells: %d single, %d total pairs", sum(1 for c in cell.values() if len(c) == 6), len(cell))
    for k, v in sorted(c1.items(), key=str):
        log.info("  %s: %d", k, v)
    (TMP / "law.json").write_text(json.dumps({"mismatch": rows, "n": len(cell), "single": sum(1 for c in cell.values() if len(c) == 6)}, indent=1, default=list))
    return cell


EXT_LABS = ALL_LABS + [(1, 1), (116, 90)]      # corners supply the axis extremes the sampling rule asks for
DN_LES = tuple(range(16))
PIN_NETS = ("enap", "clrp", "sclp")
CTLS = ("ena", "clr", "sclr", "sload")


def dn_pairs(labs=EXT_LABS):
    """Distinct net per LUT port: same LE/bit enumeration as init_pairs on a subset of LEs."""
    out = []
    for lab in labs:
        b = {**base_params(), "lab": list(lab), "dn": 1}
        for bit in range(16):
            out.append((b, {**b, "smask": f"{1 << bit:04X}"}, {"lab": lab, "le": 0, "bit": bit}))
        for le in DN_LES[1:]:
            bk = {**b, "snk": 2 * le}
            for bit in range(16):
                out.append((bk, {**bk, "kmask": f"{1 << bit:04X}"}, {"lab": lab, "le": le, "bit": bit}))
    return out


def ctl_variants(labs=((10, 10), (58, 30))):
    out = []
    for lab in labs:
        b = {**base_b(lab), "ff": 1, "pins": 1}
        out.append(b)
        for c in CTLS:
            for q in PIN_NETS:
                v = {**b, c: q}
                if c == "sload":
                    v["asdata"] = "ina"
                out.append(v)
    return out


def ll_lab_variants(labs=((58, 30), (37, 60), (100, 75)), positions=(2, 16)):
    """The honoured pin-driven second-sink pairs at X10Y10, rebuilt at other LABs."""
    out, seen = [], set()
    for n, x in okvars().items():
        p = x["params"]
        if p["fam"] == "A" and p.get("k2") and p["k2"][0] in positions and p["lab"] == [10, 10]:
            for lab in labs:
                out.append({**p, "lab": list(lab)})
            seen.add(n)
    return out


def round4():
    return [p for pr in clk_pairs(EXT_LABS) + dn_pairs(EXT_LABS) for p in pr[:2]]


def round3():
    return ([p for pr in dn_pairs() for p in pr[:2]] + ctl_variants() + ll_lab_variants())


def _rel(g, keys):
    """[(df, dv)] tile-relative of plane keys, sorted."""
    return sorted(tile_of(g, *divmod(k, NV))[2:] for k in keys)


def analyse3():
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of(cf.DEVICE))
    ok = okvars()
    res = {}
    # (1) distinct net per port: labels vs X10Y10 and cell sets
    cell = {}
    for pb, pv, m in dn_pairs():
        nb, nv = pname(pb), pname(pv)
        if nb in ok and nv in ok:
            cs = pair_cells(tagged(nv), tagged(nb))
            if len(cs) == 1:
                cell[(tuple(m["lab"]), m["le"], m["bit"])] = tile_of(g, *divmod(cs[0][0], NV))[2:]
    dn = {}
    for lab in EXT_LABS[1:]:
        same = tot = setok = 0
        for le in DN_LES:
            a = {b: cell.get(((10, 10), le, b)) for b in range(16)}
            c = {b: cell.get((lab, le, b)) for b in range(16)}
            if None in a.values() or None in c.values():
                continue
            tot += 16
            same += sum(1 for b in range(16) if a[b] == c[b])
            setok += sorted(a.values()) == sorted(c.values())
        dn[str(lab)] = {"labels_equal": same, "of": tot, "cell_sets_equal": setok, "les": len(DN_LES)}
        log.info("DN lab %s: bit labels identical to X10Y10 %d / %d; cell sets identical %d / %d LEs", lab, same, tot, setok, len(DN_LES))
    res["dn"] = dn
    # (2) control nets from pins: subtract to port / net cells
    ctl = {}
    for lab in ((10, 10), (58, 30)):
        b = {**base_b(lab), "ff": 1, "pins": 1}
        if pname(b) not in ok:
            continue
        S = {}
        for c in CTLS:
            for q in PIN_NETS:
                v = {**b, c: q, **({"asdata": "ina"} if c == "sload" else {})}
                if pname(v) in ok:
                    cs = pair_cells(tagged(pname(v)), tagged(pname(b)))
                    S[(c, q)] = {(k, ina) for k, ina in cs}
        rel = lambda st: sorted(set(_rel(g, [k for k, _ in st])))   # noqa: E731
        info = {"sizes": {f"{c}/{q}": len(v) for (c, q), v in S.items()}}
        for q in PIN_NETS:
            sets = [S[(c, q)] for c in CTLS if (c, q) in S]
            info[f"net:{q}"] = rel(set.intersection(*sets)) if len(sets) > 1 else None
        for c in CTLS:
            sets = [S[(c, q)] for q in PIN_NETS if (c, q) in S]
            info[f"port:{c}"] = rel(set.intersection(*sets)) if len(sets) > 1 else None
        ctl[str(lab)] = info
        log.info("CTL %s sizes %s", lab, info["sizes"])
        for k, v in info.items():
            if k != "sizes":
                log.info("CTL %s %s: %s", lab, k, v)
    res["ctl"] = ctl
    # (3) LOCAL_LINE roles: second-sink connect sets per LAB, port cell = common over lines, line cell = rest
    allv = load_vars()
    grp = collections.defaultdict(dict)
    for n, x in allv.items():
        p = x["params"]
        if n in ok and p["fam"] == "A" and p.get("k2"):
            grp[(tuple(p["lab"]), p["src"], p["snk"], p["port"], p["k2"][0])][p["k2"][1]] = n
    roles = collections.defaultdict(lambda: collections.defaultdict(list))
    ll = lm.ll_of_src()
    for (lab, src, snk, port, pos), d in grp.items():
        if "" in d:
            for pt, n in d.items():
                if pt:
                    cs = pair_cells(tagged(n), tagged(d[""]))
                    roles[(lab, pos, pt)][ll[src]].append(_rel(g, [k for k, _ in cs]))
    out = {}
    for (lab, pos, pt), byI in sorted(roles.items()):
        sets = [tuple(v[0]) for v in byI.values()]
        common = set(sets[0]).intersection(*[set(x) for x in sets[1:]]) if len(sets) > 1 else set()
        out[f"{lab}/k2@{pos}/port{pt}"] = {"lines": len(byI), "port_cells": sorted(common),
                                           "line_cells": {str(I): sorted(set(v[0]) - common) for I, v in sorted(byI.items())}}
    res["ll"] = out
    for k, v in out.items():
        log.info("LL %s: port cells %s; line cells %s", k, v["port_cells"], v["line_cells"])
    (TMP / "round3.json").write_text(json.dumps(res, indent=1, default=list))
    return res


def nulls():
    """Null controls: same design renamed, other fitter seed, all else pinned.  Diff vs the plain build must be empty."""
    c, b = base_b(), base_params()
    f1 = {**c, "ff": 1}
    return [(c, {**c, "nm": "r"}), (c, {**c, "seed": 2}), (f1, {**f1, "nm": "r"}), (f1, {**f1, "seed": 2}), (b, {**b, "seed": 2})]


def null_gate(jobs):
    """Build the null pairs first; any non-empty diff is reported and stops the run."""
    prs = nulls()
    run_variants([p for pr in prs for p in pr], jobs)
    ok = okvars()
    bad = 0
    for pa, pb in prs:
        na, nb = pname(pa), pname(pb)
        if na not in ok or nb not in ok:
            log.info("NULL %s: build missing", knob_of(pa, pb))
            bad += 1
            continue
        n = len(pair_cells(tagged(na), tagged(nb)))
        log.info("NULL %-10s fam %s ff %s: diff cells %d", knob_of(pa, pb), pa["fam"], pa.get("ff", "-"), n)
        bad += n != 0
    if bad:
        sys.exit(f"NULL CONTROL FAILED ({bad} pairs non-empty): fix before trusting any other pair")


def named_pairs(lab=(10, 10)):
    """Dan's explicit one-LE-LAB pairs: (label, params a, params b); all on the same back-annotated routing."""
    c = {**base_b(lab), "ff": 1}
    out = [("base free-fit / back-annotated", {**base_b(lab), "boot": 1}, base_b(lab)), ("ff off/on", base_b(lab), c), ("ff power_up low/high", c, {**c, "pw": "high"}),
           ("clk KA/KB (source LE)", c, {**c, "clk": "KB"}), ("clk KA/~KA (polarity)", c, {**c, "clk": "~KA"})]
    for key, sig in (("ena", "E"), ("clr", "C"), ("sclr", "S")):
        out += [(f"{key} absent/present", c, {**c, key: sig}), (f"{key} high/low (polarity)", {**c, key: sig}, {**c, key: "~" + sig})]
    sl = {**c, "sload": "L", "asdata": "M"}
    out += [("sload+asdata absent/present", c, sl), ("sload high/low (polarity)", sl, {**sl, "sload": "~L"}),
            ("asdata M/E", sl, {**sl, "asdata": "E"}),
            ("sclr S vs aclr S (type)", {**c, "sclr": "S"}, {**c, "clr": "S"}),
            ("LE slot 0/1 (ff off)", base_b(lab), {**base_b(lab), "slot": 1}), ("LE slot 0/7 (ff off)", base_b(lab), {**base_b(lab), "slot": 7}),
            ("LE slot 0/15 (ff off)", base_b(lab), {**base_b(lab), "slot": 15}),
            ("LE slot 0/1 (ff on)", c, {**c, "slot": 1}), ("LE slot 0/7 (ff on)", c, {**c, "slot": 7}), ("LE slot 0/15 (ff on)", c, {**c, "slot": 15}),
            ("output comb/ff", base_b(lab), c), ("output ff/both", c, {**c, "out": "both"}),
            ("FF fed LUT/asdata", c, {**c, "ffsrc": "asdata"}),
            ("input A used/tied0 (mask AAAA)", {**base_b(lab), "kmask": "AAAA"}, {**base_b(lab), "kmask": "AAAA", "tie": "A0"}),
            ("input A tied0/tied1 (mask AAAA)", {**base_b(lab), "kmask": "AAAA", "tie": "A0"}, {**base_b(lab), "kmask": "AAAA", "tie": "A1"}),
            ("input B used(ina)/tied0", base_b(lab), {**base_b(lab), "tie": "B0"}), ("input B tied0/tied1", {**base_b(lab), "tie": "B0"}, {**base_b(lab), "tie": "B1"}),
            ("input B used(ina)/open", base_b(lab), {**base_b(lab), "open": "B"}), ("input B tied0/open", {**base_b(lab), "tie": "B0"}, {**base_b(lab), "open": "B"}),
            ("input A ina pin/LE KB", base_b(lab), {**base_b(lab), "sa": "KB"}),
            ("clk local KA / pin (local clk)", c, {**c, "clk": "PIN"}), ("clk pin local/global", {**c, "clk": "PIN"}, {**c, "clk": "PIN", "gclk": 1}),
            ("fan-out 1/2", base_b(lab), {**base_b(lab), "fan": 2})]
    return out


def replicate(lab, jobs):
    """Rebuild both variants of every recorded distance-1 pair at another LAB; check the cell count and (df, dv)."""
    summ = json.loads((TMP / "summary.json").read_text())
    vs = load_vars()
    want, plist = [], []
    for row in summ["cells"]:
        a, bb = row["example"]
        pa, pb = dict(vs[a]["params"], lab=list(lab)), dict(vs[bb]["params"], lab=list(lab))
        want.append((row, pa, pb))
        plist += [fam_base(pa), pa, pb, fam_base(pb)]
    run_variants(plist, jobs)
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of(cf.DEVICE))
    rep = []
    for row, pa, pb in want:
        na, nb = pname(pa), pname(pb)
        ok = okvars()
        if na not in ok or nb not in ok:
            rep.append({**row, "replica": "no-build"})
            continue
        cs = pair_cells(tagged(na), tagged(nb))
        if len(cs) != 1:
            rep.append({**row, "replica": f"{len(cs)} cells"})
            continue
        fr, v = divmod(cs[0][0], NV)
        x, y, df, dv = tile_of(g, fr, v)
        rep.append({**row, "replica": "match" if (df, dv) == (row["df"], row["dv"]) else f"offset ({df},{dv})"})
    c = collections.Counter(r["replica"] for r in rep)
    (TMP / f"replica_{lab[0]}x{lab[1]}.json").write_text(json.dumps(rep, indent=1, default=list))
    log.info("replicate at %s: %s", lab, dict(c))


def step_toward(pa, pb):
    """Variants of pa that move ONE component toward pb (one bit for masks)."""
    out = []
    if pa["fam"] != pb["fam"]:
        return out
    for k in sorted(set(pa) | set(pb)):
        if pa.get(k) == pb.get(k) or k in ("fam", "lab", "nm", "seed", "boot"):
            continue
        if k in ("smask", "kmask"):
            diff = int(pa[k], 16) ^ int(pb[k], 16)
            bit = diff & -diff
            out.append({**pa, k: f"{int(pa[k], 16) ^ bit:04X}"})
        elif k in pb:
            out.append({**pa, k: pb[k]})
        else:
            out.append({kk: vv for kk, vv in pa.items() if kk != k})
    return out


def adapt(budget, depth, jobs):
    used = 0
    for d in range(depth):
        pairs, _ = distances(3)
        vs = load_vars()
        cand = []
        for dist, a, b in sorted(pairs, key=lambda t: (vs[t[1]]["params"]["fam"] == "A", t[0])):
            if dist in (2, 3):
                cand += step_toward(vs[a]["params"], vs[b]["params"]) + step_toward(vs[b]["params"], vs[a]["params"])
        new, seen = [], set(vs)
        for p in cand:
            n = pname(p)
            if n not in seen:
                seen.add(n)
                new.append(p)
        new = new[:max(0, budget - used)]
        log.info("adapt depth %d: %d candidates, budget left %d", d + 1, len(new), budget - used)
        if not new:
            break
        run_variants(new, jobs)
        used += len(new)


# ---- geometry, report, record ----------------------------------------------------------------------

def tile_of(g, frame, v):
    """(x, y, df, dv): same translation as cycloneiv_bit_inventory class 3 (frame = FX[x] + df, v = vy0 + vpitch*y + dv)."""
    xs = sorted(g.FX, key=lambda x: g.FX[x])
    x = max((x for x in xs if g.FX[x] - 19 <= frame), key=lambda x: g.FX[x], default=None)
    y = int(np.floor_divide(v - (g.vy0 - 68), g.vpitch))
    return x, y, frame - g.FX[x], v - (g.vy0 + g.vpitch * y)


def pair_cells(Da, Db):
    """Cells (key, in_a) for the symmetric difference: in_a True = set only in plane a."""
    out = []
    for t in Da ^ Db:
        key, rem = t >> 1, t & 1
        in_a = (t in Da) != bool(rem)     # add-tag in Da => set in a; rem-tag in Da => clear in a (so set in b)
        out.append((key, in_a))
    return out


def report(record=False):
    import cycloneiv_geom as cg
    g = cg.load(cg.die_of(cf.DEVICE))
    pairs, D = distances(3)
    vs = load_vars()
    par = {n: vs[n]["params"] for n in D}
    bn = pname(base_params())
    by_status = collections.Counter(v["status"] for v in vs.values())
    d1 = [(a, b) for d, a, b in pairs if d == 1]
    cells = {}
    per_knob = collections.defaultdict(lambda: {"pairs": 0, "cells": set()})
    for a, b in d1:
        (key, in_a), = pair_cells(D[a], D[b])
        kn = par[a]["fam"] + ":" + knob_of(par[a], par[b]) if par[a]["fam"] == par[b]["fam"] else "cross-family"
        cells.setdefault(key, []).append((kn, a, b, in_a))
        per_knob[kn]["pairs"] += 1
        per_knob[kn]["cells"].add(key)
    # variants vs base distances (calibration + hit rate per knob)
    hit = collections.defaultdict(lambda: [0, 0])
    for n in D:
        fb = pname(fam_base(par[n]))
        if n == fb or fb not in D:
            continue
        kn = par[n]["fam"] + ":" + knob_of(par[n], par[fb])
        hit[kn][0] += 1
        hit[kn][1] += 1 if len(D[n]) == 1 else 0
    rows = []
    for key, lst in sorted(cells.items()):
        fr, v = divmod(key, NV)
        x, y, df, dv = tile_of(g, fr, v)
        rows.append({"frame": fr, "v": v, "tile": [x, y], "df": df, "dv": dv, "knobs": sorted({k for k, *_ in lst}),
                     "n_pairs": len(lst), "example": lst[0][1:3]})
    summ = {"variants": dict(by_status), "d0": sum(1 for d, *_ in pairs if d == 0), "d1_pairs": len(d1), "cells": rows,
            "hit_rate_vs_base": {k: v for k, v in sorted(hit.items())},
            "unsplit_d2": [(a, b, knob_of(par[a], par[b])) for d, a, b in pairs if d == 2 and par[a]["fam"] == par[b]["fam"]],
            "unsplit_d3": [(a, b, knob_of(par[a], par[b])) for d, a, b in pairs if d == 3 and par[a]["fam"] == par[b]["fam"]]}
    (TMP / "summary.json").write_text(json.dumps(summ, indent=1, default=list))
    nm = {}
    for lbl, pa, pb in named_pairs():
        na, nb = pname(pa), pname(pb)
        if na in D and nb in D:
            cs = pair_cells(D[na], D[nb])
            nm[lbl] = len(cs)
            log.info("NAMED %-32s cells %d %s", lbl, len(cs), [tile_of(g, *divmod(k, NV))[2:] for k, _ in cs][:6] if len(cs) <= 6 else "")
        else:
            log.info("NAMED %-32s not built", lbl)
    summ["named"] = nm
    (TMP / "summary.json").write_text(json.dumps(summ, indent=1, default=list))
    log.info("variants %s; distance-0 pairs %d; distance-1 pairs %d; distinct cells %d", dict(by_status), summ["d0"], len(d1), len(rows))
    for k, (n, h) in sorted(hit.items()):
        log.info("knob %-14s variants %3d, exactly-1-cell vs base %3d", k, n, h)
    if record:
        record_pairs(cells, D, par, g)
    return summ


def record_pairs(cells, D, par, g):
    """One evidence row per (distinct cell, knob): spec = plane a, base = plane b; plane-level diff, n_objects 1."""
    from provenance import evidence_io as E
    from provenance import corpus as CO
    import db
    done = 0
    with db.engine().begin() as conn:
        E.ensure_family(conn, "cycloneiv")
        for key, lst in cells.items():
            fr, v = divmod(key, NV)
            x, y, df, dv = tile_of(g, fr, v)
            seen = set()
            for kn, a, b, in_a in lst:
                if kn in seen:
                    continue
                seen.add(kn)
                on, off = ([key], []) if in_a else ([], [key])
                meta = {"group": "bit_hunter", "knob": kn, "frame": fr, "v": v, "tile": [x, y], "df": df, "dv": dv,
                        "params_spec": par[a], "params_base": par[b], "plane_level": True}
                E.record_specimen(conn, "cycloneiv", lm.EV_DEVICE, f"bh_{a[5:]}_{b[5:]}", b, on, off, meta,
                                  f"bit_hunter:{kn}", GENERATOR, E.git_head(REPO), NV, tool_version="25.1", level=3,
                                  build_base=CO.build_id(conn, "cycloneiv", b), build_spec=CO.build_id(conn, "cycloneiv", a))
                done += 1
    log.info("recorded %d evidence rows", done)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("calib", "batch1", "batch2", "batch3", "round2a", "round2b", "law", "round3", "round4", "analyse3", "adapt", "report", "record", "replicate"))
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--budget", type=int, default=100)
    ap.add_argument("--depth", type=int, default=3)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    for lg in (log, fz.log):
        lg.setLevel(logging.INFO)
        for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_bit_hunter.log"), logging.StreamHandler()):
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            lg.addHandler(h)
    if a.cmd == "calib":
        b = base_params()
        pl = [dict(b)] + [{**b, "kmask": f"{1 << k:04X}"} for k in range(8)] + [{**b, "smask": f"{1 << k:04X}"} for k in range(8)]
        run_variants(pl, a.jobs)
        report()
    elif a.cmd == "batch1":
        null_gate(a.jobs)
        run_variants(batch1(), a.jobs)
        report()
    elif a.cmd == "round2a":
        run_variants(round2a(), a.jobs)
        law()
    elif a.cmd == "round2b":
        run_variants(round2b(), a.jobs)
        report()
    elif a.cmd == "round3":
        run_variants(round3(), a.jobs)
        analyse3()
    elif a.cmd == "round4":
        run_variants(round4(), a.jobs)
        analyse3()
    elif a.cmd == "analyse3":
        analyse3()
    elif a.cmd == "law":
        law()
    elif a.cmd == "batch3":
        run_variants(batch3(), a.jobs)
        report()
    elif a.cmd == "batch2":
        run_variants(batch2(), a.jobs)
        report()
    elif a.cmd == "adapt":
        adapt(a.budget, a.depth, a.jobs)
        report()
    elif a.cmd == "replicate":
        replicate((58, 30), a.jobs)
    elif a.cmd == "report":
        report()
    elif a.cmd == "record":
        report(record=True)


if __name__ == "__main__":
    main()
