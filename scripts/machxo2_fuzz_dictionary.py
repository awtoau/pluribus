#!/usr/bin/env python3
"""MachXO2 fuzz corpus as a construct dictionary: fuzz.v source -> what Diamond placed.

Reads diamond-fuzz/targets/<t>/fuzz.v and corpus/machxo2/diamond-fuzz/<t>/oracle.json
(scripts/machxo2_diamond_oracle.py) and writes docs/lattice/machxo2/machxo2-fuzz-dictionary.md.
Generated facts only; rerun to regenerate.

Usage: python3 scripts/machxo2_fuzz_dictionary.py [--targets-dir D] [--oracle D] [--out F]
Log:   tmp/logs/machxo2_fuzz_dictionary.log
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
import diamond_oracle_parse as P  # noqa: E402
from machxo2_diamond_oracle import REPO  # noqa: E402

LOG_PATH = os.path.join(REPO, "tmp", "logs", "machxo2_fuzz_dictionary.log")
_PRIM_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*(#\s*\(|[a-zA-Z_][\w]*\s*\()", re.M)
_PARAM_RE = re.compile(r"\.(\w+)\s*\(\s*(\"[^\"]*\"|[^)\s,]+)\s*\)")
_REG_FIELDS = ("REGMODE", "CLKMUX", "CEMUX", "LSRMUX", "SRMODE")
_IO_KEYS = ("IO_TYPE", "PULLMODE", "DRIVE", "SLEWRATE", "OPENDRAIN", "HYSTERESIS",
            "CLAMP", "DIFFRESISTOR", "TERMINATION")


def log(msg):
    print(msg, flush=True)
    with open(LOG_PATH, "a") as fh:
        fh.write(msg + "\n")


def parse_fuzz_v(text):
    """-> (summary str, {prim.param: value}).  Primitive instances + #() params."""
    text = re.sub(r"//.*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    attrs = {m.end(): m.group(1) for m in re.finditer(r"\(\*(.*?)\*\)\s*", text, re.S)}
    prims, params = [], {}
    for m in _PRIM_RE.finditer(text):
        name = m.group(1)
        if name in ("BLOCK", "LOCATE", "FREQUENCY", "IOBUF"):
            continue
        ps = []
        # (* K=V, ... *) attribute block directly before the instance
        for kv in re.findall(r'(\w+)\s*=\s*("[^"]*"|[^,\s]+)', attrs.get(m.start(1), "")):
            ps.append(f"{kv[0]}={kv[1].strip(chr(34))}")
            params[f"{name}.{kv[0]}"] = kv[1].strip('"')
        if m.group(2).startswith("#"):
            depth, i = 1, m.end()
            while i < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[i], 0)
                i += 1
            for k, v in _PARAM_RE.findall(text[m.end():i - 1]):
                v = v.strip('"')
                ps.append(f"{k}={v}")
                params[f"{name}.{k}"] = v
        prims.append(name + (f"({', '.join(ps)})" if ps else ""))
    n_always = len(re.findall(r"\balways\b", text))
    n_assign = len(re.findall(r"\bassign\b", text))
    cnt = Counter(prims)
    parts = [p if n == 1 else f"{p}x{n}" for p, n in cnt.items()]
    if n_always or not parts:
        parts.append(f"RTL: {n_always} always, {n_assign} assign")
    return "; ".join(parts), params


NO_SOURCE = ("(no fuzz.v)", {})


def placed_facts(o):
    types = Counter(c["type"] for c in o["comps"])
    luts, regs, ios = [], Counter(), Counter()
    for c in o["comps"]:
        f = P.config_fields(c["config"])
        if c["type"] == "SLICE":
            for k in ("K0", "K1"):
                v = f.get(k, "#OFF")
                if v.startswith(":H"):
                    luts.append(v.split("=", 1)[1])
            m = re.match(r"^:S0=(\w+),S1=(\w+)", f.get("CCU2", ""))
            if m:
                luts.append(f"CCU2 {m.group(1)}/{m.group(2)}")
            if f.get("REGMODE", "#OFF") != "#OFF":
                key = " ".join(f"{k}={f[k]}" for k in _REG_FIELDS if f.get(k, "#OFF") != "#OFF")
                if any("REGSET=SET" in f.get(r, "") for r in ("REG0", "REG1")):
                    key += " REGSET=SET"
                regs[key] += 1
        elif c["type"] == "PIO":
            m = re.search(r"IOBUF:::(\S+)", c["config"])
            if m:
                kv = dict(x.split("=", 1) for x in m.group(1).split(",") if "=" in x)
                ios[f"{c['site']}:" + "/".join(kv[k] for k in _IO_KEYS if k in kv)] += 1
    wcls = {re.sub(r"\d", "#", P.split_wire(w)[2]) for n in o["nets"] for w in n["wires"]}
    return {
        "types": " ".join(f"{t}x{n}" for t, n in sorted(types.items())),
        "luts": "; ".join(sorted(Counter(luts)))[:100] or "-",
        "regs": "; ".join(f"{k}" + (f" x{n}" if n > 1 else "") for k, n in regs.items()) or "-",
        "ios": "; ".join(f"{k}" + (f" x{n}" if n > 1 else "") for k, n in ios.items()) or "-",
        "nets": sum(n["routed"] for n in o["nets"]),
        "arcs": sum(len(n["arcs"]) for n in o["nets"]),
        "wire_classes": len(wcls),
        "io_set": set(ios), "reg_set": set(regs), "type_set": set(types),
    }


def group_of(t):
    p = t.split("_")
    return "_".join(p[:2]) if p[0] in ("re", "pll") and len(p) > 1 else p[0]


def esc(s):
    return str(s).replace("|", "\\|")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--targets-dir", default=os.path.join(REPO, "diamond-fuzz", "targets"))
    ap.add_argument("--oracle", default=os.path.join(REPO, "corpus", "machxo2", "diamond-fuzz"))
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "lattice", "machxo2", "machxo2-fuzz-dictionary.md"))
    args = ap.parse_args()
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    rows = defaultdict(list)
    n = 0
    for t in sorted(os.listdir(args.oracle)):
        oj = os.path.join(args.oracle, t, "oracle.json")
        fv = os.path.join(args.targets_dir, t, "fuzz.v")
        if not os.path.exists(oj):
            continue
        with open(oj) as fh:
            o = json.load(fh)
        if os.path.exists(fv):
            with open(fv) as fh:
                summ, params = parse_fuzz_v(fh.read())
        else:
            summ, params = NO_SOURCE
        rows[group_of(t)].append((t, summ, params, placed_facts(o)))
        n += 1

    L = ["# MachXO2 fuzz dictionary",
         "",
         "Generated by `python3 scripts/machxo2_fuzz_dictionary.py` from each target's "
         "`fuzz.v` and its Diamond oracle (`corpus/machxo2/diamond-fuzz/<t>/oracle.json`, "
         "see [machxo2-diamond-oracle.md](machxo2-diamond-oracle.md)). Do not hand-edit.",
         "",
         f"- {n} targets (LCMXO2-1200HC, TQFP100), {len(rows)} groups (name prefix; "
         "`re_*` / `pll_*` split one level deeper).",
         "- Columns: source = primitives + `#()` parameters parsed from `fuzz.v`; "
         "placed = Diamond component counts; LUTs = distinct LUT equations "
         "(`@` xor, `*` and, `+` or, `~` not); regs = non-`#OFF` FF muxes; "
         "I/O = pad pin:IO_TYPE/PULLMODE/DRIVE/...; nets/arcs/cls = routed nets, route arcs, distinct wire classes.",
         "", "## Groups", "",
         "| group | targets | varies in fuzz.v | varies in placement |",
         "|---|---|---|---|"]
    for g in sorted(rows):
        rs = rows[g]
        pv = defaultdict(set)
        for _t, _s, params, _p in rs:
            for k, v in params.items():
                pv[k].add(v)
        keys = set().union(*[set(p) for _t, _s, p, _f in rs])
        vary = []
        for k in sorted(keys):
            vals = {r[2].get(k, "(absent)") for r in rs}
            if len(vals) > 1:
                vs = sorted(vals)
                vary.append(f"{k.split('.', 1)[1]}: " + (", ".join(vs[:6]) + (f" +{len(vs) - 6}" if len(vs) > 6 else "")))
        srcs = {r[1] for r in rs}
        if not vary and len(srcs) > 1:
            vary.append(f"{len(srcs)} distinct sources")
        pl = []
        for name, key in (("types", "type_set"), ("I/O", "io_set"), ("regs", "reg_set")):
            vals = {frozenset(r[3][key]) for r in rs}
            if len(vals) > 1:
                pl.append(f"{name}: {len(vals)} variants")
        nets = sorted({r[3]["nets"] for r in rs})
        if len(nets) > 1:
            pl.append(f"nets {nets[0]}-{nets[-1]}")
        L.append(f"| [{g}](#{g.replace('_', '-').lower()}) | {len(rs)} | "
                 f"{esc('; '.join(vary[:6]) or 'none')} | {esc('; '.join(pl) or 'none')} |")
    for g in sorted(rows):
        L += ["", f"## {g}", "",
              "| target | source | placed | LUTs | regs | I/O | nets/arcs/cls |",
              "|---|---|---|---|---|---|---|"]
        for t, summ, _params, p in rows[g]:
            L.append(f"| {t} | {esc(summ[:150])} | {esc(p['types'])} | {esc(p['luts'])} | "
                     f"{esc(p['regs'])} | {esc(p['ios'])} | "
                     f"{p['nets']}/{p['arcs']}/{p['wire_classes']} |")
    with open(args.out, "w") as fh:
        fh.write("\n".join(L) + "\n")
    log(f"[dict] {n} targets, {len(rows)} groups -> {args.out}")


if __name__ == "__main__":
    main()
