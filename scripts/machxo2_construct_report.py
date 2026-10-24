#!/usr/bin/env python3.15t
"""Write docs/machxo2-construct-dictionary.md from corpus/machxo2/constructs outputs (facts only).

Per build: slices, LUT4s, CCU2 carry slices/chains, registers + modes, EBR, LUT equations,
routed nets + wire classes (from oracle.json, the .mrp, build.json); per construct a
comparison across widths and variants; oracle-comparison fault headline (compare.json /
_compare_summary.json, if scripts/machxo2_oracle_compare.py was run on this directory).

Usage: python3.15t scripts/machxo2_construct_report.py [--dir D] [--out FILE]
Log:   tmp/logs/machxo2_construct_report.log
"""
import argparse
import json
import os
import re
import tomllib
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(REPO, "corpus", "machxo2", "constructs")
OUT = os.path.join(REPO, "docs", "machxo2-construct-dictionary.md")
LOG = os.path.join(REPO, "tmp", "logs", "machxo2_construct_report.log")


def wire_class(w):
    nm = re.sub(r"^R\d+C\d+_", "", w)
    nm = re.sub(r"^[EWNS]\d_", "", nm)
    m = re.match(r"^([HV]\d\d)[NSEW]", nm)
    if m:
        return m.group(1) + " span"
    if nm.endswith("_SLICE"):
        return "slice pin"
    if nm.startswith("J"):
        return "J pin (" + re.sub(r"\d+", "#", nm[1:])[:12] + ")" if not nm.startswith(("JPADD", "JCLK")) else "pad/clock J pin"
    if re.match(r"^[A-Z]+\d+$", nm):
        return "local " + re.sub(r"\d+", "#", nm)
    return re.sub(r"\d+", "#", nm)


def mrp(d):
    out = {}
    p = os.path.join(d, "logs", "fuzz_impl1.mrp")
    if not os.path.exists(p):
        return out
    pats = {"regs": r"Number of registers:\s+(\d+)", "slices": r"Number of SLICEs:\s+(\d+)",
            "carry_slices": r"SLICEs as Carry:\s+(\d+)", "ram_slices": r"SLICEs as RAM:\s+(\d+)",
            "lut4": r"Number of LUT4s:\s+(\d+)", "ripple": r"used as ripple logic:\s+(\d+)",
            "dram": r"used as distributed RAM:\s+(\d+)", "ebr": r"Number of block RAMs:\s+(\d+)",
            "pio": r"Number of PIO sites used:\s+(\d+)"}
    txt = open(p, errors="replace").read()
    for k, pat in pats.items():
        m = re.search(pat, txt)
        out[k] = int(m.group(1)) if m else None
    return out


def analyse(d):
    o = json.load(open(os.path.join(d, "oracle.json")))
    comps = o["comps"]
    sl = [c for c in comps if c["type"] == "SLICE"]
    modes = Counter(re.search(r"MODE:(\w+)", c["config"]).group(1) for c in sl)
    regs = Counter()
    eqs = Counter()
    for c in sl:
        cf = dict(re.findall(r"(\w+):(\S+)", c["config"]))
        for j in (0, 1):
            if cf.get(f"REG{j}") == "#ON":
                regs[f"{cf.get('REGMODE')}/{cf.get('SRMODE')}/CE={cf.get('CEMUX')}/LSR={cf.get('LSRMUX')}/GSR={cf.get('GSR')}"] += 1
        for m in re.finditer(r"K[01]::H[01]=(\(.*?\)|\S+?)(?= K\d|\s[A-Z]+\d?:|$)", c["config"]):
            eqs[m.group(1)] += 1
        m = re.search(r"CCU2::(\S+)", c["config"])
        if m:
            eqs["CCU2 " + m.group(1)] += 1
    fco = {n["name"] for n in o["nets"] for p in n["pins"] if p["pin"] == "FCO"}
    links = sum(1 for n in o["nets"]
                if {"FCO"} & {p["pin"] for p in n["pins"]} and {"FCI"} & {p["pin"] for p in n["pins"]})
    nccu = modes.get("CCU2", 0)
    ebr = [c for c in comps if c["type"] not in ("SLICE", "PIO")]
    wc = Counter()
    arcs = 0
    for n in o["nets"]:
        arcs += len(n["arcs"])
        for w in n["wires"]:
            wc[wire_class(w)] += 1
    del fco
    return {"modes": modes, "regs": regs, "eqs": eqs, "ccu2": nccu, "chains": nccu - links if nccu else 0,
            "other": Counter(c["type"] for c in ebr), "ebr_cfg": [c["config"][:200] for c in ebr if "EBR" in c["type"]][:1],
            "nets": len(o["nets"]), "routed": sum(1 for n in o["nets"] if n.get("routed")), "arcs": arcs, "wc": wc,
            "io": sum(1 for c in comps if c["type"] == "PIO")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    names = sorted(n for n in os.listdir(a.dir) if os.path.exists(os.path.join(a.dir, n, "design.toml")))
    rows = []
    for n in names:
        d = os.path.join(a.dir, n)
        meta = tomllib.load(open(os.path.join(d, "design.toml"), "rb"))
        bj = json.load(open(os.path.join(d, "build.json"))) if os.path.exists(os.path.join(d, "build.json")) else {"status": "not built"}
        r = {"name": n, "meta": meta, "build": bj}
        if bj.get("status") == "ok":
            r["m"] = mrp(d)
            if os.path.exists(os.path.join(d, "oracle.json")):
                r["a"] = analyse(d)
            else:
                r["a"] = None
        cj = os.path.join(d, "compare.json")
        if os.path.exists(cj):
            c = json.load(open(cj))
            r["cmp"] = c
        rows.append(r)
    skipped = {}
    sp = os.path.join(a.dir, "_skipped.json")
    if os.path.exists(sp):
        skipped = json.load(open(sp))
    L = []
    w = L.append
    ok = [r for r in rows if r["build"].get("status") == "ok"]
    bad = [r for r in rows if r["build"].get("status") != "ok"]
    w("# MachXO2 construct dictionary (Diamond 3.14 / LSE)\n")
    w("Generated by `scripts/machxo2_construct_report.py` from `corpus/machxo2/constructs/*` (not edited by hand).")
    w("Device LCMXO2-1200HC-5TG100C, Diamond LSE, default strategy, no LPF (pads auto-placed). Sources: `scripts/machxo2_construct_gen.py`; build: `scripts/machxo2_construct_build.py`.\n")
    w("- Variants: `v95` plain Verilog-95; `vnd` Lattice vendor features (attributes / primitive instantiation); `v01` Verilog-2001 (ANSI ports, generate, signed, `always @*`, localparam); `sv` = SystemVerilog feature probes (`probe_*`, built as `top.v`; Diamond `prj_src add` rejects `*.sv`).")
    w("- `io_reduced`: outputs folded to one registered parity bit when port bits exceed the TQFP100 budget (72).")
    w(f"- Builds: {len(rows)} attempted, {len(ok)} succeeded, {len(bad)} failed.\n")
    if skipped:
        w("## Vendor variants skipped (no applicable feature)\n")
        for k, v in sorted(skipped.items()):
            w(f"- `{k}`: {v}")
        w("")
    w("## Failures\n")
    fails = defaultdict(list)
    for r in bad:
        fails[re.sub(r"/mnt/\S*/src/", "", re.sub(r"\(\d+\)", "(N)", (r["build"].get("reason") or r["build"].get("status", "")).strip()))[:300]].append(r["name"])
    if not fails:
        w("- none")
    for reason, ns in sorted(fails.items(), key=lambda x: -len(x[1])):
        w(f"- {len(ns)} builds: `{reason}`")
        w(f"  - {', '.join(ns[:40])}{' ...' if len(ns) > 40 else ''}")
    w("")
    # per construct comparison
    w("## Per construct: widths x variants\n")
    w("Cell = `slices/LUT4/FF/CCU2/EBR` (mapper report); `FAIL` = flow failed; `-` = no such build.\n")
    byc = defaultdict(dict)
    for r in rows:
        byc[r["meta"]["construct"]][(r["meta"]["variant"], r["meta"]["width"])] = r
    for cons in sorted(byc):
        ws = sorted({k[1] for k in byc[cons]})
        vs = [v for v in ("v95", "vnd", "v01", "sv") if any(k[0] == v for k in byc[cons])]
        w(f"### {cons}\n")
        w("| variant \\ width | " + " | ".join(str(x) for x in ws) + " |")
        w("|---|" + "---|" * len(ws))
        for v in vs:
            cells = []
            for x in ws:
                r = byc[cons].get((v, x))
                if r is None:
                    cells.append("-")
                elif "m" not in r:
                    cells.append("FAIL")
                else:
                    m, an = r["m"], r["a"]
                    cells.append(f"{m['slices']}/{m['lut4']}/{m['regs']}/{an['ccu2'] if an else m['carry_slices']}/{m['ebr']}" + ("*" if r["meta"].get("io_reduced") else ""))
            w(f"| {v} | " + " | ".join(cells) + " |")
        w("\n`*` = io_reduced.\n")
    # per build
    w("## Per build\n")
    for r in rows:
        meta, b = r["meta"], r["build"]
        w(f"### {r['name']}\n")
        w(f"- {meta.get('purpose', '')}; lang {meta.get('lang', 'n/a')}; width {meta.get('width', '')}; io_bits {meta.get('io_bits', '')}; io_reduced {meta.get('io_reduced', '')}")
        if "m" not in r:
            w(f"- **{b.get('status')}**: `{re.sub(chr(47) + 'mnt' + chr(47) + chr(92) + 'S*' + chr(47) + 'src' + chr(47), '', b.get('reason', ''))}`\n")
            continue
        if r["a"] is None:
            m = r["m"]
            w(f"- slices {m['slices']}; LUT4 {m['lut4']}; registers {m['regs']}; EBR {m['ebr']}; PIO {m['pio']}")
            w(f"- oracle extraction failed: `{b.get('oracle', '')[:160]}` (no routing detail)\n")
            continue
        m, an = r["m"], r["a"]
        w(f"- slices {m['slices']} (carry {m['carry_slices']}, ram {m['ram_slices']}); LUT4 {m['lut4']} (ripple {m['ripple']}, dist-RAM {m['dram']}); registers {m['regs']}; EBR {m['ebr']}; PIO {m['pio']}")
        w(f"- slice MODE {dict(an['modes'])}; CCU2 slices {an['ccu2']}, carry chains {an['chains']}")
        w("- register modes: " + ("; ".join(f"{k} x{v}" for k, v in an["regs"].most_common(4)) or "none"))
        if an["other"]:
            w(f"- non-slice/PIO comps: {dict(an['other'])}" + (f"; EBR config `{an['ebr_cfg'][0]}`" if an["ebr_cfg"] else ""))
        eq = an["eqs"].most_common(6)
        if eq:
            w("- LUT equations: " + "; ".join(f"`{k}` x{v}" for k, v in eq) + (f" (+{len(an['eqs']) - 6} more)" if len(an["eqs"]) > 6 else ""))
        w(f"- nets {an['nets']} (routed {an['routed']}), route arcs {an['arcs']}; wire classes: " +
          ", ".join(f"{k} {v}" for k, v in an["wc"].most_common(8)))
        if "cmp" in r:
            pv = r["cmp"]["pips"]
            nv = r["cmp"]["net_verdicts"]
            w(f"- oracle comparison: pips {dict(pv)}; nets {dict(nv)}")
        w("")
    # comparison headline
    cs = os.path.join(a.dir, "_compare_summary.json")
    w("## Oracle comparison (decode + lift vs Diamond)\n")
    if os.path.exists(cs):
        s = json.load(open(cs))
        w(f"- targets {s['targets']}, status {s['status']}")
        for k, h in s.get("headline", {}).items():
            w(f"- {k}: {h['match']} / {h['total']} matched = {h['rate_pct']}%; faults (every non-MATCH) {h['faults']}")
        w(f"- pips by verdict: {s['pips']}")
        w(f"- nets by verdict: {s['net_verdicts']}")
        w(f"- gkey branches: {s['gkey_verdicts']}")
        w(f"- site fields (non-MATCH only): { {k: v for k, v in s['site_field_verdicts'].items() if 'MATCH' not in k.split(':')[-1] or 'MISMATCH' in k} }")
        w("- Faults counted: LIFT_MISSING, ORACLE_ONLY, LIFT_ONLY, MISMATCH; see `docs/machxo2-diamond-oracle.md` for definitions.")
    else:
        w("- not run (untested)")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w").write("\n".join(L) + "\n")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, "a").write(f"wrote {a.out}: {len(rows)} rows, {len(ok)} ok\n")
    print(f"wrote {a.out}: {len(rows)} rows, {len(ok)} ok")


if __name__ == "__main__":
    main()
