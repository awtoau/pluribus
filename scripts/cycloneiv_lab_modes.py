#!/usr/bin/env python3.15t
"""Cyclone IV LAB core feature specimens (item A of #141): RAW cram-plane diff, no decoder in the loop.

Pair = identical cells/placement/masks; specimen adds ONE thing, base leaves it out.  Diff = set bits
only in one plane.  Evidence goes to databases/cycloneiv/gx150.db (kind specimen-pair, source_ref
lab_modes:<group>).  Design prefix gxlm_.  Groups (smallest first):
  pprobe   forced LOCAL_LINE I x sink port (A-D) legality probe, 1 sink, X10Y10
  ports    every (source LE, sink LE, port A-D) with the LL/port forced, per LAB
  (later groups: modes, buf, flags - see docs/cycloneiv-specimens.md "LAB core checklist")

  gen <group> | build <group> | diff <group> | run <group> (= gen+build+diff per pair) | compare <group>
Log tmp/logs/cycloneiv_lab_modes.log
"""
import argparse
import logging
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(REPO / "databases" / "cycloneiv" / "gx150.db"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_forced as cf  # noqa: E402
import cycloneiv_fuzz as fz  # noqa: E402

log = logging.getLogger("cycloneiv_lab_modes")
CORPUS = cf.CORPUS
DEVICE = cf.DEVICE
EV_DEVICE = "EP4CGX150"   # device string of the evidence rows
GENERATOR = "scripts/cycloneiv_lab_modes.py"
LABS = [(10, 10), (58, 30), (37, 60), (100, 75)]
SRC_REF = "lab_modes:"
KEEP_FULL = 4            # full bitstreams kept for the first N pairs of a group
DISK_FLOOR_GB = 12.0
LL_OF_SRC = None         # {src N: LOCAL_LINE I}, read from the existing same-LAB grid evidence

CELL = ('  cycloneiv_lcell_comb #(.lut_mask(16\'h{mask}), .sum_lutc_input("datac"), .dont_touch("on"))\n'
        "    {name} ({ports});\n")


def ll_of_src():
    global LL_OF_SRC
    if LL_OF_SRC is None:
        import evidence_io_bridge as B
        t = B.specimen_table("cycloneiv", EV_DEVICE, "evidence/cycloneiv/cycloneiv_forced_lab.json")
        LL_OF_SRC = {v["src"]: v["hop"][3] for v in t.values()}
        if len(LL_OF_SRC) != 16:
            sys.exit("same-LAB grid evidence missing (need src -> LOCAL_LINE I)")
    return LL_OF_SRC


def rcf_for(lab, ll, port):
    return ("section global_data {\n\trcf_written_by = \"Quartus Prime 25.1 Build 1129\";\n"
            f"\tdevice = {DEVICE};\n}}\n\nsignal_name = u0_o {{\n\tLOCAL_LINE:X{lab[0]}Y{lab[1]}S0I{ll};\n"
            f"\tdest = ( u1, DATA{port} ), route_port = DATA{port};\n}}\n")


def verilog(src_mask, snk_mask, conn):
    """u0 (source, no inputs) -> u1 (sink), y = u1.combout; conn = '' for the base."""
    return ("module top(output y);\n  wire u0_o;\n"
            + CELL.format(mask=src_mask, name="u0", ports=".combout(u0_o)")
            + CELL.format(mask=snk_mask, name="u1", ports=(conn + ".combout(y)"))
            + "endmodule\n")


def rcf_multi(lab, ll, dests):
    """dests [(cell, port)]: one LOCAL_LINE element, one dest line pair per sink."""
    body = "".join(f"\tdest = ( {c}, DATA{p} ), route_port = DATA{p};\n" for c, p in dests)
    return ("section global_data {\n\trcf_written_by = \"Quartus Prime 25.1 Build 1129\";\n"
            f"\tdevice = {DEVICE};\n}}\n\nsignal_name = u0_o {{\n\tLOCAL_LINE:X{lab[0]}Y{lab[1]}S0I{ll};\n{body}}}\n")


def verilog_multi(sinks):
    """u0 -> sinks [(cell, port)]; u1 combout is y, other sinks dangle (dont_touch keeps them)."""
    v = "module top(output y);\n  wire u0_o;\n" + CELL.format(mask="0000", name="u0", ports=".combout(u0_o)")
    for c, p in sinks:
        v += CELL.format(mask="FFFF", name=c, ports=f".data{p.lower()}(u0_o), " + (".combout(y)" if c == "u1" else ".combout()"))
    return v + "endmodule\n"


def lc(lab, n):
    return cf.lc(lab[0], lab[1], n)


def port_pair(lab, src, snk, port, ll=None):
    """(name, spec verilog, base verilog, qsf, rcf, meta): u0@N<src> -> u1@N<snk>.DATA<port>, LL forced."""
    ll = ll_of_src()[src] if ll is None else ll
    name = f"gxlm_p{port}_{lab[0]}x{lab[1]}_{src:02d}_{snk:02d}_i{ll:02d}"
    q = [f"set_location_assignment {lc(lab, src)} -to u0", f"set_location_assignment {lc(lab, snk)} -to u1",
         "set_location_assignment PIN_B9 -to y"]
    meta = {"group": "ports", "lab": list(lab), "src": src, "snk": snk, "port": port, "ll": ll}
    return (name, verilog("0000", "FFFF", f".data{port.lower()}(u0_o), "), verilog("0000", "FFFF", ""),
            q, rcf_for(lab, ll, port), meta)


def legal_ports():
    """{src: [ports]} the pprobe forced as asked (honoured) at X10Y10; the rest were rerouted by the fitter."""
    import json
    import sqlite3
    import dbtools
    c = sqlite3.connect(f"file:{dbtools.family_db('cycloneiv')}?mode=ro", uri=True)
    out = {}
    for (r,) in c.execute("SELECT result FROM evidence WHERE source_ref='lab_modes:ports'"):
        m = json.loads(r)["meta"]
        if m.get("forced_honoured") and m["lab"] == [10, 10]:
            out.setdefault(m["src"], set()).add(m["port"])
    return out


def multi_pair(tag, lab, src, spec_sinks, base_sinks, meta):
    """spec drives spec_sinks [(cell, snk N, port)], base base_sinks; both forced onto the source's LL.
    Cells in both builds are identical: every sink cell is placed in both, un-driven ones just float."""
    ll = ll_of_src()[src]
    cells = sorted({(c, k) for c, k, _ in spec_sinks + base_sinks})
    allv = lambda sk: verilog_multi_all(cells, sk)   # noqa: E731
    q = [f"set_location_assignment {lc(lab, src)} -to u0", "set_location_assignment PIN_B9 -to y"] + [
        f"set_location_assignment {lc(lab, k)} -to {c}" for c, k in cells]
    name = f"gxlm_{tag}_{lab[0]}x{lab[1]}_{src:02d}_" + "_".join(f"{c}{k:02d}{p}" for c, k, p in spec_sinks) + f"_i{ll:02d}"
    meta = {**meta, "lab": list(lab), "src": src, "ll": ll, "spec_dests": [[c, k, p] for c, k, p in spec_sinks],
            "base_dests": [[c, k, p] for c, k, p in base_sinks]}
    rb = rcf_multi(lab, ll, [(c, p) for c, _, p in base_sinks]) if base_sinks else None
    meta["rcf_base"] = rb
    return (name, allv(spec_sinks), allv(base_sinks), q, rcf_multi(lab, ll, [(c, p) for c, _, p in spec_sinks]), meta)


def verilog_multi_all(cells, driven):
    """Extra sink cells feed u1's first free port so they keep fan-out (a dangling cell is deleted)."""
    dm = {c: p for c, _, p in driven}
    extra = [c for c, _k in cells if c != "u1"]
    free = [x for x in "ABCD" if x != dm.get("u1")]
    v = ("module top(output y);\n  wire u0_o;\n" + "".join(f"  wire {c}_o;\n" for c in extra)
         + CELL.format(mask="0000", name="u0", ports=".combout(u0_o)"))
    for c in extra:
        conn = f".data{dm[c].lower()}(u0_o), " if c in dm else ""
        v += CELL.format(mask="FFFF", name=c, ports=conn + f".combout({c}_o)")
    u1 = (f".data{dm['u1'].lower()}(u0_o), " if "u1" in dm else "") + "".join(
        f".data{free[i].lower()}({c}_o), " for i, c in enumerate(extra))
    return v + CELL.format(mask="FFFF", name="u1", ports=u1 + ".combout(y)") + "endmodule\n"


def lp_ports():
    lp = legal_ports()
    return {s: sorted(v) for s, v in lp.items()}


def group_pairs(group):
    if group == "fan":       # source cells: base S->K1, spec S->K1 and S->K2 (second sink added)
        lab, lp, out = LABS[0], lp_ports(), []
        for s in range(0, 32, 2):
            p = lp[s][0]
            k1 = 30 if s != 30 else 28
            for k2 in [k for k in (0, 10, 20) if k != s]:
                out.append(multi_pair("fan", lab, s, [("u1", k1, p), ("u2", k2, p)], [("u1", k1, p)], {"group": "fan"}))
        return out
    if group == "pswap":     # port-only: same (source, sink), port p1 vs p2 (both legal for the LL)
        lab, lp, out = LABS[0], lp_ports(), []
        for s in range(0, 32, 2):
            for k in [k for k in (0, 10, 20) if k != s]:
                p1, p2 = lp[s][:2]
                out.append(multi_pair("psw", lab, s, [("u1", k, p2)], [("u1", k, p1)], {"group": "pswap", "ports": [p1, p2]}))
        return out
    if group == "pprobe":     # legality: every (LL I, port) once, sink fixed at N2 (N4 for source N2)
        lab = LABS[0]
        return [port_pair(lab, s, 4 if s == 2 else 2, p) for s in range(0, 32, 2) for p in "ABCD"]
    if group.endswith("s") and group.startswith("ports"):   # seeded 10% sample of the full grid
        import random
        full = group_pairs(group[:-1])
        return sorted(random.Random(20261029).sample(full, max(1, len(full) // 10)), key=lambda p: p[0])
    if group.startswith("ports"):   # portsX10Y10 etc: all src x snk x port at one LAB (src != snk)
        m = re.fullmatch(r"ports(\d+)x(\d+)", group)
        lab = (int(m.group(1)), int(m.group(2)))
        lp = legal_ports()
        return [port_pair(lab, s, k, p) for s in range(0, 32, 2) for k in range(0, 32, 2) if s != k for p in sorted(lp[s])]
    sys.exit(f"unknown group {group}")


def write_pair(pr):
    name, vs, vb, q, rcf, meta = pr
    for kind, v in (("s", vs), ("b", vb)):
        d = CORPUS / f"{name}_{kind}"
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / "src" / "top.v").write_text(v)
        qq = list(q)
        use = rcf if kind == "s" else meta.get("rcf_base")
        if use:
            (d / "src" / "force.rcf").write_text(use)
            qq = ["set_global_assignment -name ROUTING_BACK_ANNOTATION_MODE NORMAL",
                  "set_global_assignment -name ROUTING_BACK_ANNOTATION_FILE ../src/force.rcf"] + qq
        qq += ["set_global_assignment -name SEED 1", 'set_global_assignment -name FITTER_EFFORT "FAST FIT"']
        (d / "design.toml").write_text(
            f'top = "top"\npurpose = "lab_modes {meta["group"]} {kind}"\nexercises = {fz.toml_list(["lab", "forced"])}\n'
            f"qsf = {fz.toml_list(qq)}\ndevice = \"{DEVICE}\"\ntool = \"quartus\"\n"
            f'tool_version = "25.1"\nbuilt = "{__import__("datetime").date.today().isoformat()}"\n')


def prune(n, full):
    d = CORPUS / n
    shutil.rmtree(d / "quartus", ignore_errors=True)
    shutil.rmtree(d / "logs", ignore_errors=True)
    for f in ("postfit.vo", "fit.rpt", "build.pin") + (() if full else ("bitstream.rbf",)):
        (d / f).unlink(missing_ok=True)


def rcf_hop_of(name):
    """(LOCAL_LINE I, port) in the post-fit RCF for u0_o, or None."""
    p = CORPUS / f"{name}_s" / "routing.rcf"
    if not p.exists():
        return None
    m = re.search(r"signal_name = u0_o \{\s*(\w+):X(\d+)Y(\d+)S0I(\d+);\s*dest = \( u1, \w+ \), route_port = (\w+);",
                  p.read_text())
    return None if not m else [m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)]


def dests_ok(name, kind, ll, want):
    """RCF of build `kind` routes u0_o over LOCAL_LINE I=ll to exactly the wanted (cell, port)s."""
    p = CORPUS / f"{name}_{kind}" / "routing.rcf"
    if not p.exists():
        return False
    m = re.search(r"signal_name = u0_o \{\n(.*?)\n\}", p.read_text(), re.S)
    if not m:
        return not want
    lls = re.findall(r"LOCAL_LINE:X\d+Y\d+S0I(\d+)", m.group(1))
    got = sorted((d, r) for d, r in re.findall(r"dest = \( (\w+), DATA\w \), route_port = DATA(\w)", m.group(1)))
    return sorted((c, p_) for c, _, p_ in want) == got and set(lls) <= {str(ll)}


def build_diff_record(pr, idx, record=True):
    """Build base + specimen, raw-diff, record the evidence row, prune.  Returns the meta."""
    from provenance import evidence_io as E
    import db
    name, _vs, _vb, _q, _rcf, meta = pr
    meta = {k: v for k, v in meta.items() if k != "rcf_base"} | ({"rcf_base_set": True} if meta.get("rcf_base") else {})
    full = idx < KEEP_FULL
    for k in ("b", "s"):
        f = fz.build_one(f"{name}_{k}")
        if f:
            log.info("%s_%s: FAIL at %s", name, k, f)
            return {**meta, "status": "build-fail", "step": f}
    on, off = cf.diff(f"{name}_s", f"{name}_b")
    hop = rcf_hop_of(name)
    if "spec_dests" in meta:
        honoured = all(dests_ok(name, k, meta["ll"], meta[f"{k2}_dests"]) for k, k2 in (("s", "spec"), ("b", "base")))
    else:
        honoured = bool(hop and hop[3] == meta.get("ll") and hop[4] == f"DATA{meta.get('port')}") if "port" in meta else None
    meta = {**meta, "hop": hop, "forced_honoured": honoured, "status": "ok"}
    nv = cc.load_plane_only(f"{name}_b").shape[1]
    for k in ("s", "b"):
        prune(f"{name}_{k}", full)
    if record:
        with db.engine().begin() as conn:
            E.ensure_family(conn, "cycloneiv")
            from provenance import corpus as CO
            E.record_specimen(conn, "cycloneiv", EV_DEVICE, name, f"{name}_b", on, off, meta, SRC_REF + meta["group"],
                              GENERATOR, E.git_head(REPO), nv, tool_version="25.1",
                              build_base=CO.build_id(conn, "cycloneiv", f"{name}_b"), build_spec=CO.build_id(conn, "cycloneiv", f"{name}_s"))
    log.info("%s: on %d off %d hop %s honoured %s", name, len(on), len(off), hop, honoured)
    return {**meta, "on": on, "off": off}


def run(group, jobs, todo_only=True):
    import build_pool
    import db
    from sqlalchemy import select
    import schema as S
    prs = group_pairs(group)
    with db.engine().connect() as conn:
        done = {r[0] for r in conn.execute(select(S.evidence.c.name).where(
            S.evidence.c.source_ref == SRC_REF + (prs[0][5]["group"]), S.evidence.c.family == "cycloneiv"))}
    todo = [(i, p) for i, p in enumerate(prs) if p[0] not in done]
    log.info("group %s: %d pairs, %d to do", group, len(prs), len(todo))
    for _i, p in todo:
        write_pair(p)
    if shutil.disk_usage(REPO).free / 2**30 < DISK_FLOOR_GB:
        sys.exit("disk floor")
    res = build_pool.map_adaptive(lambda ip: build_diff_record(ip[1], ip[0]), todo, per_job_gb=2.5,
                                  max_workers=jobs or None, disk_floor_gb=DISK_FLOOR_GB)
    bad = [r for r in res if r.get("status") != "ok"]
    ok = [r for r in res if r.get("status") == "ok"]
    hon = sum(1 for r in ok if r.get("forced_honoured"))
    log.info("group %s: %d ok, %d failed, forced honoured %d / %d", group, len(ok), len(bad), hon, len(ok))
    return res


def rows(group_ref="lab_modes:ports"):
    """{name: (meta, on flat list, off flat list)} from the evidence rows of one source_ref."""
    import evidence_io_bridge as B
    return B.specimen_table("cycloneiv", EV_DEVICE, group_ref) or {}


def compare(labs, nv=6368):
    """Each LAB's ports grid vs X10Y10 in (frame, v): best single (dframe, dv) offset, then pairs equal up to it."""
    import collections
    t = rows()
    fv = lambda bs: sorted(divmod(b, nv) for b in bs)   # noqa: E731
    ref = {(m["src"], m["snk"], m["port"]): m for m in t.values() if m["lab"] == [10, 10]}
    for lab in labs:
        cur = {(m["src"], m["snk"], m["port"]): m for m in t.values() if m["lab"] == list(lab)}
        offs = collections.Counter()
        for k, m in cur.items():
            r = ref.get(k)
            if r and len(r["on"]) == len(m["on"]):
                for (f1, v1), (f0, v0) in zip(fv(m["on"]), fv(r["on"])):
                    offs[(f1 - f0, v1 - v0)] += 1
        if not offs:
            log.info("LAB %s: no overlapping pairs", lab)
            continue
        (df, dv), cnt = offs.most_common(1)[0]
        same = [k for k, m in cur.items() if k in ref and fv(m["on"]) == [(a + df, b + dv) for a, b in fv(ref[k]["on"])] and not m["off"]]
        bad = [k for k in cur if k not in same]
        log.info("LAB %s vs X10Y10: offset (dframe %d, dv %d) %d votes; %d / %d pairs match", lab, df, dv, cnt, len(same), len(cur))
        for k in sorted(bad)[:20]:
            log.info("  NOMATCH %s: %s vs %s", k, fv(cur[k]["on"]), fv(ref[k]["on"]) if k in ref else None)


def additive(tab):
    """tab {(a, b): int}: solve v = fa[a] + fb[b] by propagation over the (a, b) graph; hits = cells it reproduces."""
    adj_a, adj_b = {}, {}
    for (a, b), v in tab.items():
        adj_a.setdefault(a, []).append((b, v))
        adj_b.setdefault(b, []).append((a, v))
    fa, fb = {}, {}
    for a0 in sorted(adj_a):
        if a0 in fa:
            continue
        fa[a0] = 0
        todo = [("a", a0)]
        while todo:
            k, x = todo.pop()
            if k == "a":
                for b, v in adj_a[x]:
                    if b not in fb:
                        fb[b] = v - fa[x]
                        todo.append(("b", b))
            else:
                for a, v in adj_b[x]:
                    if a not in fa:
                        fa[a] = v - fb[x]
                        todo.append(("a", a))
    hits = sum(1 for (a, b), v in tab.items() if fa[a] + fb[b] == v)
    return 0, fa, fb, hits, len(tab)


def fit(group_ref="lab_modes:ports", lab=(10, 10)):
    """Per port: bit sets by (src, snk); every component classified src-only / snk-only / additive / other."""
    import collections
    t = [m for m in rows(group_ref).values() if m["lab"] == list(lab) and m.get("forced_honoured")]
    byport = collections.defaultdict(dict)
    for m in t:
        byport[m["port"]][(m["src"], m["snk"])] = sorted(m["on"])
    out = {}
    for port, tab in sorted(byport.items()):
        sizes = collections.Counter(len(v) for v in tab.values())
        k = sizes.most_common(1)[0][0]
        for j in range(k):
            comp = {key: v[j] for key, v in tab.items() if len(v) == k}
            srconly = len({(a, v) for (a, b), v in comp.items()}) == len({a for a, _ in comp})
            snkonly = len({(b, v) for (a, b), v in comp.items()}) == len({b for _, b in comp})
            base, fa, fb, hits, n = additive(comp)
            kind = "src-only" if srconly else "snk-only" if snkonly else ("additive" if hits == n else "other")
            out[(port, j)] = (kind, hits, n)
            log.info("port %s component %d: %s (additive hits %d / %d), sizes %s", port, j, kind, hits, n, dict(sizes))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("gen", "run", "show", "compare", "fit"))
    ap.add_argument("group")
    ap.add_argument("--jobs", type=int, default=0)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    for lg in (log, fz.log):
        lg.setLevel(logging.INFO)
        for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_lab_modes.log"), logging.StreamHandler()):
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            lg.addHandler(h)
    if a.cmd == "gen":
        for p in group_pairs(a.group):
            write_pair(p)
    elif a.cmd == "fit":
        fit()
    elif a.cmd == "compare":
        compare([tuple(int(v) for v in x.split("x")) for x in a.group.split(",")])
    elif a.cmd == "run":
        run(a.group, a.jobs)


if __name__ == "__main__":
    main()
