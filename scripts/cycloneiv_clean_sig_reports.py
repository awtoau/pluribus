#!/usr/bin/env python3.15t
"""Report-level structure of a map/fit specimen: tmp/sig/<name>/map.rpt + fit.rpt -> tmp/sig/<name>/report_sig.json, #165.

  python3.15t scripts/cycloneiv_clean_sig_reports.py NAME [NAME ...]      (or --all: every dir with map.rpt)
Source: the Analysis & Synthesis hierarchy table, RAM summary and DSP columns of the normal Quartus Lite map report
(licensed cores cannot export a netlist: quartus_eda error 204012).  Counts only; entity names stay in tmp/.
Totals are given net of the OpenCore Plus overhead entities (`sld_hub` Signal Tap hub + the obfuscated timer wrapper) that every time-limited design carries.
Log: tmp/logs/cycloneiv_clean_sig_reports.log.
"""
import collections
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SIG = REPO / "tmp" / "sig"
LOG = REPO / "tmp" / "logs" / "cycloneiv_clean_sig_reports.log"
# public Quartus library primitives by entity-name prefix -> role
ROLES = [("lpm_add_sub", "adder"), ("lpm_counter", "counter"), ("lpm_mult", "mult"), ("altmult_add", "mult_add"),
         ("altera_mult_add", "mult_add"), ("altsyncram", "ram"), ("altshift_taps", "shift_taps"), ("lpm_compare", "compare"),
         ("lpm_mux", "mux"), ("altdpram", "dpram"), ("lpm_ff", "ff"), ("lpm_shiftreg", "shiftreg"), ("lpm_divide", "divide"),
         ("scfifo", "fifo"), ("dcfifo", "fifo"), ("altpll", "pll")]


OCP = ("sld_hub", "pzdyqx")       # OpenCore Plus time-limit overhead entities (Signal Tap hub + obfuscated timer wrapper), fixed per release


def num(s):
    m = re.match(r"\s*(\d+)(?:\s*\((\d+)\))?", s)
    return (int(m.group(1)), int(m.group(2))) if m and m.group(2) else (int(m.group(1)), None) if m else (0, None)


def table(text, title):
    """Rows (list of stripped cells) of the first report table whose title line is `title`."""
    lines = text.splitlines()
    for i, l in enumerate(lines):
        if l.startswith("; " + title):
            rows = []
            for r in lines[i + 2:]:
                if r.startswith(";"):
                    rows.append([c.strip() if k else c for k, c in enumerate(r.strip().strip(";").split(";"))])
                elif rows and r.startswith("+") and not r.startswith("+-"):
                    break
                elif rows and not r.strip():
                    break
            return rows
    return []


def hierarchy(text):
    """[(depth, name, comb_total, comb_self, regs_total, regs_self, membits, dsp, d9, d18, d36)] in report order."""
    out = []
    for c in table(text, "Analysis & Synthesis Resource Utilization by Entity"):
        if len(c) < 9 or not c[0].lstrip().startswith("|"):
            continue
        raw = c[0]
        depth = (len(raw) - len(raw.lstrip())) // 3
        name = raw.strip().strip("|")
        n = [num(x) for x in c[1:9]]
        out.append(dict(depth=depth, name=name, comb=n[0][0], comb_self=n[0][1], regs=n[1][0], regs_self=n[1][1], mem=n[2][0],
                        dsp=n[3][0], d9=n[4][0], d18=n[5][0], d36=n[6][0]))
    return out


def role(name):
    base = name.split(":")[0]
    for pre, r in ROLES:
        if base == pre:
            return r
    return None


def analyse(name):
    d = SIG / name
    text = (d / "map.rpt").read_text(errors="replace")
    fit = json.loads((d / "fit.json").read_text())
    H = hierarchy(text)
    if not H:
        raise SystemExit(f"{name}: no hierarchy table")
    ocp = [h for h in H if h["depth"] == 1 and h["name"].split(":")[0] in OCP]
    hub = dict(comb=sum(h["comb"] for h in ocp), regs=sum(h["regs"] for h in ocp)) if ocp else None
    top = H[0]
    net = dict(les_comb=top["comb"] - (hub["comb"] if hub else 0), regs=top["regs"] - (hub["regs"] if hub else 0),
               mem_bits=top["mem"], mult9=top["d9"] + 2 * top["d18"], d18=top["d18"])
    kids = [h for h in H if h["depth"] == 1 and h["name"].split(":")[0] not in OCP]
    kid_groups = collections.Counter()
    for k in kids:
        kid_groups[(k["name"].split(":")[0], k["comb"], k["regs"], k["mem"], k["d18"] * 2 + k["d9"])] += 1
    roles = collections.defaultdict(list)
    for h in H:
        if h["depth"] == 0 or h["name"].split(":")[0] in OCP:
            continue
        r = role(h["name"])
        if r:
            roles[r].append(h)
    rp = {}
    for r, hs in roles.items():
        # megafunction wrapper nodes (altsyncram:..., lpm_add_sub:...) only; their auto_generated children are excluded by prefix
        rp[r] = dict(n=len(hs), comb_hist=dict(sorted(collections.Counter(h["comb"] for h in hs).items())),
                     regs_hist=dict(sorted(collections.Counter(h["regs"] for h in hs).items())),
                     mult9_hist=dict(sorted(collections.Counter(h["d9"] + 2 * h["d18"] for h in hs).items())),
                     mem_hist=dict(sorted(collections.Counter(h["mem"] for h in hs).items())))
    ram = collections.Counter()
    for c in table(text, "Analysis & Synthesis RAM Summary"):
        if len(c) >= 9 and c[1] in ("AUTO", "M9K", "M144K", "MLAB", "LC") or (len(c) >= 9 and c[2] in ("ROM", "Single Port", "Simple Dual Port", "True Dual Port")):
            ram[(c[2], c[3], c[4], c[5], c[6])] += 1
    rec = dict(name=name, fit=fit, net=net, hub=hub, top_children=len(kids),
               child_groups=[dict(entity=k[0], comb=k[1], regs=k[2], mem=k[3], mult9=k[4], inst=v) for k, v in sorted(kid_groups.items(), key=lambda kv: -kv[1])],
               roles=rp, ram=[dict(mode=k[0], depthA=k[1], widthA=k[2], depthB=k[3], widthB=k[4], inst=v) for k, v in sorted(ram.items())],
               carry_chain_adders=len([h for h in H if h["name"].startswith("lpm_add_sub")]))
    (d / "report_sig.json").write_text(json.dumps(rec, indent=1))
    return rec


def main():
    names = sys.argv[1:]
    if names == ["--all"]:
        names = sorted(p.parent.name for p in SIG.glob("*/map.rpt"))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as lg:
        for n in names:
            r = analyse(n)
            line = f"{n}: net comb {r['net']['les_comb']} regs {r['net']['regs']} mem {r['net']['mem_bits']} mult9 {r['net']['mult9']} children {r['top_children']} roles " + \
                   ",".join(f"{k}={v['n']}" for k, v in sorted(r["roles"].items()))
            print(line)
            lg.write(line + "\n")


if __name__ == "__main__":
    main()
