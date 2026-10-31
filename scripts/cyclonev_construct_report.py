#!/usr/bin/env python3
"""Write docs/altera/cycloneV/cyclonev-construct-dictionary.md from the corpus DB (issue #104).

Reads corpus_builds / postfit_atoms / postfit_conns / gate_verdicts / route_hops for every
design whose design.toml has a `construct` field (made by scripts/cyclonev_construct_gen.py).
Nothing in the output is hand-written except the fixed headings and column legends.
Usage: python3.15t scripts/cyclonev_construct_report.py
Log: tmp/logs/cyclonev_construct_report.log
"""
import collections
import json
import logging
import os
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(REPO / "corpus" / "cyclonev" / "corpus.db"))
sys.path.insert(0, str(REPO))
OUT = REPO / "docs" / "altera" / "cycloneV" / "cyclonev-construct-dictionary.md"
LOG = REPO / "tmp" / "logs" / "cyclonev_construct_report.log"
log = logging.getLogger("construct_report")

CTL = ("ena", "clrn", "sclr", "sload", "aload", "asdata")
VERDICTS = ("MATCH", "MISMATCH", "LIFT_MISSING", "QUARTUS_ONLY", "LIFT_ONLY", "UNMODELLED")
# IO pad/buffer, primitive-cell and clock-network elements are not fabric routing
NOT_FABRIC = re.compile(r"(IO_|ARRIAV_|CLKBUF|GCLK|SCLK|SPINE|ROWCLK|LAB_CLK|GLOBAL|BLK_CLK|HMCPHY)")
VORDER = {"v95": 0, "vnd": 1, "sv": 2}


def short(t):
    return {"cyclonev_lcell_comb": "lcell", "cyclonev_io_ibuf": "ibuf", "cyclonev_io_obuf": "obuf",
            "cyclonev_mac": "mac", "cyclonev_ram_block": "ram", "dffeas": "dff"}.get(t, t.replace("cyclonev_", ""))


def vkey(v):
    return (VORDER.get(v.split("_")[0], 9), v)


def load_builds(c):
    rows = c.execute("select id, design, status, out_dir, toolchain from corpus_builds").fetchall()
    builds = []
    for bid, design, status, out_dir, tc in rows:
        spec = tomllib.loads((REPO / out_dir / "design.toml").read_text())
        builds.append(dict(id=bid, design=design, status=status, dir=REPO / out_dir, tc=tc,
                           construct=spec.get("construct"), variant=spec.get("variant"),
                           width=spec.get("width"), purpose=spec.get("purpose", "")))
    return builds


def facts(c, b):
    bid = b["id"]
    f = {}
    f["types"] = collections.Counter(short(t) for (t,) in c.execute(
        "select type from postfit_atoms where build=? and type!='pin'", (bid,)))
    # LUT cells: mask, data inputs actually driven, arithmetic (sumout/cout/cin connected)
    luts = []
    for aid, params in c.execute("select id, params from postfit_atoms where build=? "
                                 "and type='cyclonev_lcell_comb'", (bid,)):
        p = json.loads(params)
        ports = {}
        for port, net, const in c.execute("select port, net, const from postfit_conns "
                                          "where atom=? and port in ('dataa','datab','datac','datad',"
                                          "'datae','dataf','datag','cin','sumout','cout','combout')",
                                          (aid,)):
            ports[port] = (net, const)
        used = sum(1 for k in ("dataa", "datab", "datac", "datad", "datae", "dataf", "datag")
                   if k in ports and ports[k][1] is None and ports[k][0])
        arith = any(ports.get(k, (None, "x"))[0] for k in ("sumout", "cout")) or \
            (ports.get("cin", (None, "x"))[0] is not None and ports["cin"][1] is None)
        luts.append(dict(mask=p.get("lut_mask", "?").replace("64'h", ""), used=used, arith=arith,
                         ext=p.get("extended_lut") == "on", sh=p.get("shared_arith") == "on",
                         comb_out=bool(ports.get("combout", (None,))[0])))
    f["luts"] = luts
    # register control: driven (net, no const) vs tied (const)
    ctl = {k: 0 for k in CTL}
    inv_clk = 0
    for port, net, const, inv in c.execute(
            "select c.port, c.net, c.const, c.inverted from postfit_conns c join postfit_atoms a "
            "on a.id=c.atom where c.build=? and a.type='dffeas'", (bid,)):
        if port in ctl and const is None and net:
            ctl[port] += 1
        if port == "clk" and inv:
            inv_clk += 1
    f["ctl"] = ctl
    # routing: data-path routing elements (distinct location+element), by type
    el = collections.Counter()
    seen = set()
    for loc, element in c.execute("select location, element from route_hops where build=? and type='RE'", (bid,)):
        if NOT_FABRIC.match(element):
            continue
        if (loc, element) not in seen:
            seen.add((loc, element))
            el[element] += 1
    f["route"] = el
    verd = collections.Counter()
    pairs = set()
    for field, verdict in c.execute("select field, verdict from gate_verdicts where build=?", (bid,)):
        key = re.sub(r"\.(dataa|datab|datac|datad|datae|dataf|datag|cin|sharein)$", ".<in>", field)
        verd[verdict] += 1
        pairs.add((key, verdict))
    f["verd"] = verd
    f["pairs"] = pairs
    return f


def err_text(d):
    for step in ("quartus_map", "quartus_fit", "quartus_asm", "quartus_eda", "quartus_cpf",
                 "quartus_sta", "decomp", "load", "verilog"):
        lf = d / "logs" / f"{step}.log"
        if lf.exists():
            errs = [ln.strip() for ln in lf.read_text(errors="replace").splitlines()
                    if re.match(r"\s*(Error|ERROR|Traceback|.*Error:)", ln)]
            if errs:
                return step, errs[0][:300]
    return None, ""


def mask_cell(f):
    ms = collections.Counter(l["mask"] for l in f["luts"])
    if not ms:
        return "-"
    if len(ms) <= 3 and sum(ms.values()) <= 6:
        return ", ".join(f"`{m}`" + (f"x{n}" if n > 1 else "") for m, n in sorted(ms.items()))
    top = ", ".join(f"`{m}`x{n}" for m, n in ms.most_common(3))
    return f"{len(ms)} distinct: {top}, ..."


def modes_cell(f):
    L = f["luts"]
    if not L:
        return "-"
    k = collections.Counter(l["used"] for l in L)
    s = " ".join(f"k{n}:{k[n]}" for n in sorted(k))
    flags = [("arith", sum(l["arith"] for l in L)), ("ext", sum(l["ext"] for l in L)),
             ("shr", sum(l["sh"] for l in L))]
    return s + "".join(f" {n}:{v}" for n, v in flags if v)


def ctl_cell(f):
    s = " ".join(f"{k}:{v}" for k, v in f["ctl"].items() if v)
    return s or ("none" if f["types"].get("dff") else "-")


def route_cell(f):
    items = f["route"].most_common()
    return " ".join(f"{e}x{n}" for e, n in items[:8]) or "-"


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)])
    import db
    c = db.connect_threadsafe()
    builds = load_builds(c)
    orig = [b for b in builds if not b["construct"]]
    cons = [b for b in builds if b["construct"]]
    log.info("%d original, %d construct builds", len(orig), len(cons))
    for b in builds:
        b["f"] = facts(c, b) if b["status"] == "ok" else None

    o_pairs = set()
    o_verd = collections.Counter()
    for b in orig:
        if b["f"]:
            o_pairs |= b["f"]["pairs"]
            o_verd += b["f"]["verd"]
    toolchains = sorted({b["tc"] for b in builds if b["tc"]})

    w = []
    w.append("# Cyclone V construct dictionary\n")
    w.append("Generated by `scripts/cyclonev_construct_report.py` from `corpus/cyclonev/corpus.db`; do not edit by hand.")
    w.append("Sources: `corpus/cyclonev/c_*/src/*.v` (made by `scripts/cyclonev_construct_gen.py`). Context: issue #104.\n")
    w.append(f"- Device `5CEBA4U19C8`; Quartus {', '.join(toolchains)}; {len(cons)} construct builds, "
             f"{sum(1 for b in cons if b['status'] == 'ok')} ok.")
    w.append("- Variants: `v95` Verilog-95 (qsf `VERILOG_INPUT_VERSION VERILOG_1995`); `vnd` Quartus-specific "
             "(lpm_*/altsyncram megafunctions, `syn_encoding`/`ramstyle`/`keep` attributes, `full_case parallel_case` pragma; "
             "`VERILOG_2001`); `sv` SystemVerilog (`SYSTEMVERILOG_2005`).")
    w.append("- Columns: `lcell` = cyclonev_lcell_comb, `dff` = dffeas, `io` = ibuf+obuf. `modes`: `kN:M` = M lcells with N "
             "data inputs driven by nets, `arith` = lcells with sumout/cout/cin in use, `ext` = extended_lut on, `shr` = shared_arith on. "
             "`masks` = `lut_mask` hex (64 bit). `ctl` = dff control pins driven by a net (rest tied): ena, clrn, sclr, sload, aload, asdata. "
             "`route` = distinct fabric routing elements (location+element) by type over all reported paths, top 8; IO pad/buffer, cell and clock-network elements omitted.\n")

    # failures
    fails = [b for b in cons if b["status"] != "ok"]
    w.append("## Failed builds\n")
    if not fails:
        w.append("None.\n")
    else:
        w.append("| design | status | first error |\n|---|---|---|")
        for b in sorted(fails, key=lambda b: b["design"]):
            step, e = err_text(b["dir"])
            w.append(f"| `{b['design']}` | {b['status']} | {step or ''}: {e.replace('|', '/')} |")
        w.append("")

    # original verdicts
    w.append("## Lifter verdicts, original designs (baseline)\n")
    w.append(f"{len(orig)} designs; verdict counts over all compare rows (lifter known-broken, #106; recorded only).\n")
    w.append("| " + " | ".join(VERDICTS) + " |\n|" + "---|" * len(VERDICTS))
    w.append("| " + " | ".join(str(o_verd.get(v, 0)) for v in VERDICTS) + " |\n")

    by_c = collections.defaultdict(list)
    for b in cons:
        by_c[b["construct"]].append(b)
    order = [k for k in dict.fromkeys(b["construct"] for b in sorted(cons, key=lambda b: b["design"]))]

    for cname in order:
        bs = sorted(by_c[cname], key=lambda b: (vkey(b["variant"]), b["width"]))
        w.append(f"## {cname}\n")
        w.append(bs[0]["purpose"].split(" [")[0] + ".\n")
        w.append("| variant | w | lcell | dff | mac | ram | io | other | modes | masks | ctl | route |")
        w.append("|---|--:|--:|--:|--:|--:|--:|---|---|---|---|---|")
        for b in bs:
            f = b["f"]
            if not f:
                step, e = err_text(b["dir"])
                w.append(f"| {b['variant']} | {b['width']} | FAILED {b['status']}: {e.replace('|', '/')[:120]} |||||||||| ")
                continue
            t = f["types"]
            other = " ".join(f"{k}:{v}" for k, v in sorted(t.items())
                             if k not in ("lcell", "dff", "mac", "ram", "ibuf", "obuf")) or "-"
            w.append(f"| {b['variant']} | {b['width']} | {t.get('lcell', 0)} | {t.get('dff', 0)} | {t.get('mac', 0)} | "
                     f"{t.get('ram', 0)} | {t.get('ibuf', 0) + t.get('obuf', 0)} | {other} | {modes_cell(f)} | "
                     f"{mask_cell(f)} | {ctl_cell(f)} | {route_cell(f)} |")
        w.append("")
        ok = [b for b in bs if b["f"]]
        # scaling per variant
        w.append("Scaling (width: lcell/dff/ram):")
        for v in sorted({b["variant"] for b in ok}, key=vkey):
            s = ", ".join(f"{b['width']}: {b['f']['types'].get('lcell', 0)}/{b['f']['types'].get('dff', 0)}/"
                          f"{b['f']['types'].get('ram', 0)}" for b in ok if b["variant"] == v)
            w.append(f"- `{v}` {s}")
        # variant differences vs the first variant at each width
        w.append("\nVariant differences (vs `" + sorted({b['variant'] for b in ok}, key=vkey)[0] + "` at the same width):")
        base_v = sorted({b["variant"] for b in ok}, key=vkey)[0]
        base = {b["width"]: b["f"] for b in ok if b["variant"] == base_v}
        any_diff = False
        for b in ok:
            if b["variant"] == base_v or b["width"] not in base:
                continue
            a, f = base[b["width"]], b["f"]
            d = []
            for k in sorted(set(a["types"]) | set(f["types"])):
                if a["types"].get(k, 0) != f["types"].get(k, 0):
                    d.append(f"{k} {a['types'].get(k, 0)}->{f['types'].get(k, 0)}")
            if sorted(l["mask"] for l in a["luts"]) != sorted(l["mask"] for l in f["luts"]):
                d.append("masks differ")
            if a["ctl"] != f["ctl"]:
                d.append("ctl " + " ".join(f"{k}:{a['ctl'][k]}->{f['ctl'][k]}" for k in CTL if a["ctl"][k] != f["ctl"][k]))
            if modes_cell(a) != modes_cell(f):
                d.append(f"modes {modes_cell(a)} -> {modes_cell(f)}")
            if d:
                any_diff = True
                w.append(f"- `{b['variant']}` w={b['width']}: " + "; ".join(d))
        if not any_diff:
            w.append("- none: atom counts, masks, modes and control usage identical")
        # verdicts
        tot = collections.Counter()
        pairs = set()
        for b in ok:
            tot += b["f"]["verd"]
            pairs |= b["f"]["pairs"]
        new = sorted(pairs - o_pairs)
        w.append("\nLifter verdicts (all builds of this construct): " +
                 ", ".join(f"{v} {tot[v]}" for v in VERDICTS if tot[v]) + ".")
        if new:
            w.append("- (field, verdict) pairs not seen in the original designs: " +
                     ", ".join(f"{k}={v}" for k, v in new))
        else:
            w.append("- no (field, verdict) pair outside the set seen in the original designs")
        w.append("")
    OUT.write_text("\n".join(w) + "\n")
    log.info("wrote %s (%d lines)", OUT, len(w))


if __name__ == "__main__":
    main()
