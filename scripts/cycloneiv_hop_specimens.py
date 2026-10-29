#!/usr/bin/env python3.15t
"""Cyclone IV GX forced single-hop specimens on span wires and LI muxes (issue #157, decision 1).

PREDICTION (written before any build): for a (block, group) after afx_map, the asm.ddb group bits (entries with
`pred` set, plane cells via the AFX-mapped coordinates) of the hop S -> M are a subset of the raw-diff cell set
of an RCF-forced path through that hop, and the rest of the raw diff is hop-independent: for one mux M and a
fixed downstream path, flipped(S_i) = asm_bits(S_i -> M) U asm_bits(downstream groups) U R, with R the same
cell set (the non-asm LE-input mux + LE_BUFFER side) for every input S_i of M.  Exact = both parts hold.
A miss on either part is reported with the cell counts (missing from the flip, extra beyond R).

Mux inputs come from the decoded routing.ddb fan-in (inverted exact fan-out).  RCF names of wire records are
only a NAMING aid learnt from corpus RCFs (exact-tile unique resolution, conflicts dropped); no bits are learnt.
Pair = base (u1 input open) + spec (u0 -> u1 forced by RCF), identical cells/placement/pins; the spec RCF is
the base's post-fit RCF plus the forced u0_o signal, so every other route is the same in both builds.
Raw diff of the cram planes; no Dec.active.  Honoured = the spec's post-fit u0_o route equals the forced one.

  python3.15t scripts/cycloneiv_hop_specimens.py names     # corpus RCF naming table -> tmp/hop_specimens/names.json
  python3.15t scripts/cycloneiv_hop_specimens.py plan      # muxes, inputs, forced paths -> plan.json
  python3.15t scripts/cycloneiv_hop_specimens.py build [--only null|arcs]
  python3.15t scripts/cycloneiv_hop_specimens.py analyse   # diff vs asm groups -> results.json, metrics
  python3.15t scripts/cycloneiv_hop_specimens.py record    # evidence rows (specimen-pair, build_base set)
Log tmp/logs/cycloneiv_hop_specimens.log.
"""
import argparse
import collections
import glob
import json
import logging
import re
import sys
import shutil
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
TMP = REPO / "tmp" / "hop_specimens"
CORPUS = REPO / "corpus" / "cycloneiv"
log = logging.getLogger("cycloneiv_hop_specimens")
PFX = "gxhop"
LAB = (10, 10)
NV = 6368
ENUM = {"LB": 45, "R4": 268, "C4": 275, "R24": 273, "C16": 281, "LI": 282}
TYPE_OF = {v: k for k, v in ENUM.items()}
WIRE = ("R4", "C4", "R24", "C16")
# LI index -> its more common sink port (corpus RCFs; every LI feeds two ports, e.g. I0 -> B or C)
LI_PORT = dict(enumerate("C A A A C C C C B B A B B B A A A C A A A A A B B B B A B B C C C A A A C C".split()))
SEED = 20261029


def n_of_i(i):
    """LE_BUFFER index -> LCCOMB N: each LE n has two output buffers I = 2n and 2n + 1, both with the LCCOMB at N = 2n as
    source (corpus: post-fit atom location vs first RCF element; the gxnb direct-link grid saw only one of the two)."""
    return i - (i % 2)


class Graph:
    """Exact routing.ddb graph (fan-out via Ddb, fan-in inverted) + asm group lookups."""

    def __init__(self):
        import cycloneiv_ddb_trace as T
        self.T = T
        self.D = T.Ddb(need_map=False)
        D = self.D
        self.Q, self.P, self.N = D.Q, D.P, D.N
        c = D.cnt[D.tpl].astype(np.int64)
        tot = int(c.sum())
        src = np.repeat(np.arange(self.N, dtype=np.int32), c)
        st = np.cumsum(c) - c
        k = (np.arange(tot) - np.repeat(st, c)).astype(np.int32)
        dst = (np.repeat(D.V, c) + D.offs[np.repeat(D.eoff[D.tpl], c) + k]).astype(np.int32)
        o = np.argsort(dst, kind="stable")
        self.fi_src, self.fi_k = src[o], k[o]
        self.fi_start = np.searchsorted(dst[o], np.arange(self.N + 1))
        del src, dst, k, o
        sel = np.flatnonzero(self.Q.enum == ENUM["LB"])
        self.lb = {(int(self.P.vx[r]), int(self.P.vy[r]), int(self.Q.index[r])): int(r) for r in sel}
        self.dec = None

    def vx(self, X):
        return self.D.cm[X]

    def fanin(self, m):
        a, b = self.fi_start[m], self.fi_start[m + 1]
        return self.fi_src[a:b], self.fi_k[a:b]

    def klass(self, r):
        return TYPE_OF.get(int(self.Q.enum[r]), f"E{int(self.Q.enum[r])}")

    def edge_k(self, s, d):
        fan = self.D.fan_of(s)
        w = np.flatnonzero(fan == d)
        return int(w[0]) if len(w) else None

    def group_bits(self, s, d):
        """Programmed asm cells (plane keys) of the group of source record s whose edge goes to d, + dropped count."""
        if self.dec is None:
            import cycloneiv_asm_decode as AD
            self.dec = AD.Dec()
            self.grec_first = np.searchsorted(np.asarray(self.dec.grec), np.arange(self.N))
        k = self.edge_k(s, d)
        if k is None:
            return None
        dec = self.dec
        g = int(self.grec_first[s]) + k
        a, n = int(dec.gstart[g]), int(dec.gsize[g])
        pred = np.asarray(dec.pred[a:a + n])
        pf, pv = np.asarray(dec.pf[a:a + n])[pred], np.asarray(dec.pv[a:a + n])[pred]
        ok = pf != 30000
        return sorted((pf[ok].astype(np.int64) * NV + pv[ok]).tolist()), int((~ok).sum())


def rcf_name_of(G, r, names_rev):
    """RCF (type, x, y, I) of record r, or None when unknown."""
    t = G.klass(r)
    if t == "LB":
        x = G.D.x_of_vx.get(int(G.P.vx[r]))
        return None if x is None else ("LE_BUFFER", x, int(G.P.vy[r]), int(G.Q.index[r]))
    if t == "LI":
        x = G.D.x_of_vx.get(int(G.P.vx[r]))
        return None if x is None else ("LOCAL_INTERCONNECT", x, int(G.P.vy[r]), int(G.Q.index[r]))
    return names_rev.get(r)


# ---------------------------------------------------------------- stage: names
def cmd_names(a):
    import cycloneiv_corpus as cc
    from concurrent.futures import ThreadPoolExecutor
    G = Graph()
    files = sorted(glob.glob(str(CORPUS / "*/routing.rcf")))
    log.info("naming: %d corpus RCFs", len(files))
    votes = collections.defaultdict(collections.Counter)      # (type,x,y,I) -> Counter(record)

    def one(f):
        out = []
        for edges in cc.parse_rcf(f).values():
            rec = {}
            for s, d in edges:
                if s[0] == "W" and s[1] == "LE_BUFFER" and s not in rec:
                    vx = G.D.cm.get(s[2])
                    r = G.lb.get((vx, s[3], s[5])) if vx is not None else None
                    if r is not None:
                        rec[s] = r
            for s, d in edges:
                if s in rec and d[0] == "W" and d[1] in WIRE and d not in rec:
                    fan = G.D.fan_of(rec[s])
                    c = fan[(G.Q.enum[fan] == ENUM[d[1]]) & (G.P.vx[fan] == 115 - d[2]) & (G.P.vy[fan] == d[3])]
                    if len(c) == 1:
                        rec[d] = int(c[0])
                        out.append(((d[1], d[2], d[3], d[5]), int(c[0])))
        return out
    with ThreadPoolExecutor(16) as ex:
        for out in ex.map(one, files):
            for k, r in out:
                votes[k][r] += 1
    names, conflict = {}, 0
    for k, c in votes.items():
        if len(c) == 1:
            names[k] = next(iter(c))
        else:
            conflict += 1
    rev = collections.defaultdict(set)
    for k, r in names.items():
        rev[r].add(k)
    bad = {r for r, ks in rev.items() if len(ks) > 1}
    names = {k: r for k, r in names.items() if r not in bad}
    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / "names.json").write_text(json.dumps({"|".join(map(str, k)): r for k, r in names.items()}))
    log.info("naming table: %d names (%d conflicting RCF names dropped, %d records with two names dropped)",
             len(names), conflict, len(bad))


def load_names():
    t = json.loads((TMP / "names.json").read_text())
    rev = {}
    for k, r in t.items():
        ty, x, y, i = k.split("|")
        rev[r] = (ty, int(x), int(y), int(i))
    return rev


# ---------------------------------------------------------------- stage: plan
def chain_to(G, rev, s, depth=0):
    """Named upstream chain [LB, ..., s] of record s (LB sources: itself); picks the lowest named LB feeder."""
    if G.klass(s) == "LB":
        return [s] if n_of_i(int(G.Q.index[s])) is not None else None
    if rcf_name_of(G, s, rev) is None:
        return None
    srcs, _ = G.fanin(s)
    best = None
    for f in sorted(srcs.tolist()):
        if G.klass(f) == "LB" and n_of_i(int(G.Q.index[f])) is not None and rcf_name_of(G, f, rev) is not None:
            best = [f, s]
            break
    return best


def observed_edges():
    """{dest name: Counter(src name)} over every wire/LI/LE_BUFFER -> wire/LI RCF edge of the corpus (names as in the RCF)."""
    import cycloneiv_corpus as cc
    from concurrent.futures import ThreadPoolExecutor
    files = sorted(glob.glob(str(CORPUS / "*/routing.rcf")))

    def one(f):
        out = []
        for edges in cc.parse_rcf(f).values():
            for s_, d_ in edges:
                if s_[0] == "W" and d_[0] == "W":
                    out.append(((s_[1], s_[2], s_[3], s_[5]), (d_[1], d_[2], d_[3], d_[5])))
        return out
    obs = collections.defaultdict(collections.Counter)
    with ThreadPoolExecutor(16) as ex:
        for out in ex.map(one, files):
            for sn, dn in out:
                obs[dn][sn] += 1
    return obs


def src_ok(G, rev, obs, s, m_name):
    """Forceable chain into mux m_name -> (records [LB] or [LB, wire], tier) or None.  Tier A: every hop (s -> m, LB -> s)
    was seen as an RCF edge in the corpus; tier B: the names are known and the ddb has the edges, but a hop was never seen."""
    nm_s = rcf_name_of(G, s, rev)
    if nm_s is None:
        return None
    seen_sm = nm_s in obs.get(m_name, ())
    if G.klass(s) == "LB":
        return [s], ("A" if seen_sm else "B")
    srcs, _ = G.fanin(s)
    best = None
    for f in sorted(srcs.tolist()):
        if G.klass(f) == "LB":
            nf = rcf_name_of(G, f, rev)
            if nf is None:
                continue
            tier = "A" if (seen_sm and nf in obs.get(nm_s, ())) else "B"
            if best is None or (tier == "A" and best[1] == "B"):
                best = ([f, s], tier)
    return best


def down_li(G, rev, obs, m):
    nm_m = rcf_name_of(G, m, rev)
    return [r for r in G.D.fan_of(m).tolist()
            if G.klass(r) == "LI" and int(G.Q.index[r]) in LI_PORT and rcf_name_of(G, r, rev)
            and nm_m in obs.get(rcf_name_of(G, r, rev), ())]


def cmd_plan(a):
    G = Graph()
    rev = load_names()
    obs = observed_edges()
    P, Q = G.P, G.Q
    log.info("observed corpus edges: %d destination names", len(obs))

    def n_in(m):
        nm_m = rcf_name_of(G, m, rev)
        srcs, _ = G.fanin(m)
        t = collections.Counter((src_ok(G, rev, obs, int(s), nm_m) or (0, None))[1] for s in srcs)
        return t["A"] * 100 + t["B"]
    best = collections.defaultdict(dict)       # (X,Y) -> kind -> (n forceable inputs, idx, rec)
    for r, nm_ in rev.items():
        kind = nm_[0]
        if kind not in ("R4", "C4"):
            continue
        X, Y = nm_[1], nm_[2]
        if not (6 <= X <= 100 and 6 <= Y <= 80) or X not in G.D.cm:
            continue
        if not down_li(G, rev, obs, r):
            continue
        n = n_in(r)
        if n > best[(X, Y)].get(kind, (-1,))[0]:
            best[(X, Y)][kind] = (n, int(Q.index[r]), r)
    for (X, Y), d in list(best.items()):
        vx = G.vx(X)
        cands = []
        for sel in np.flatnonzero((Q.enum == ENUM["LI"]) & (P.vx == vx) & (P.vy == Y)):
            if int(Q.index[sel]) in LI_PORT:
                cands.append((n_in(int(sel)), int(Q.index[sel]), int(sel)))
        if cands:
            d["LI"] = max(cands)
    full = {lab: d for lab, d in best.items() if all(k in d for k in ("R4", "C4", "LI"))}
    ranked = sorted(full, key=lambda lab: (-min(d[0] for d in full[lab].values()), abs(lab[0] - 10) + abs(lab[1] - 10)))
    for lab in ranked[:5]:
        log.info("candidate LAB X%dY%d: forceable (100 x tier A + tier B) R4 %d C4 %d LI %d", lab[0], lab[1],
                 full[lab]["R4"][0], full[lab]["C4"][0], full[lab]["LI"][0])
    lab = ranked[0] if a.lab is None else tuple(int(v) for v in a.lab.split(","))
    plan = {"lab": lab, "muxes": [], "arcs": []}
    for kind in ("R4", "C4", "LI"):
        n, idx, m = full[lab][kind]
        dl = down_li(G, rev, obs, m) if kind != "LI" else []
        L = dl[0] if dl else None
        srcs, ks = G.fanin(m)
        nm_m = rcf_name_of(G, m, rev)
        mx = {"kind": kind, "idx": idx, "mux": m, "mux_name": nm_m, "down": L,
              "down_name": rcf_name_of(G, L, rev) if L else None,
              "fanin": [{"src": int(s), "class": G.klass(int(s)), "name": rcf_name_of(G, int(s), rev)} for s in srcs]}
        plan["muxes"].append(mx)
        for s in sorted(srcs.tolist()):
            ch, tier = src_ok(G, rev, obs, s, nm_m) or (None, None)
            if ch:
                plan["arcs"].append({"mux": m, "kind": kind, "src": s, "class": G.klass(s), "status": "planned", "chain": ch, "tier": tier,
                                     "chain_names": [rcf_name_of(G, r, rev) for r in ch]})
            else:
                why = ("hop never seen in a corpus RCF (name unknown or edge unobserved)" if G.klass(s) in WIRE + ("LB",)
                       else f"source class {G.klass(s)}")
                plan["arcs"].append({"mux": m, "kind": kind, "src": s, "class": G.klass(s), "status": "not-forceable", "why": why})
        log.info("mux %s idx %d %s: fan-in %d, forceable tier A %d tier B %d, down %s", kind, idx, nm_m, len(srcs), n // 100, n % 100,
                 mx["down_name"])
    (TMP / "plan.json").write_text(json.dumps(plan, indent=0, default=int))
    log.info("plan: LAB X%dY%d, %d arcs (%d forceable)", lab[0], lab[1], len(plan["arcs"]),
             sum(x["status"] == "planned" for x in plan["arcs"]))


# ---------------------------------------------------------------- designs
CELL = ('  cycloneiv_lcell_comb #(.lut_mask(16\'h{mask}), .sum_lutc_input("datac"), .dont_touch("on"))\n'
        "    {name} ({ports});\n")


def verilog(port, tag):
    conn = f".data{port.lower()}(u0_o{tag}), " if port else ""
    return (f"module top(output y);\n  wire u0_o{tag};\n" + CELL.format(mask="0000", name=f"u0{tag}", ports=f".combout(u0_o{tag})")
            + CELL.format(mask="FFFF", name=f"u1{tag}", ports=conn + ".combout(y)") + "endmodule\n")


def lc(x, y, n):
    return f"LCCOMB_X{x}_Y{y}_N{n}"


def qsf(u0, u1, extra, seed):
    q = [f"set_location_assignment {lc(*u0)} -to u0{extra['tag']}", f"set_location_assignment {lc(*u1)} -to u1{extra['tag']}",
         "set_location_assignment PIN_B9 -to y"]
    if extra.get("rcf"):
        q = ["set_global_assignment -name ROUTING_BACK_ANNOTATION_MODE NORMAL",
             "set_global_assignment -name ROUTING_BACK_ANNOTATION_FILE ../src/force.rcf"] + q
    return q + [f"set_global_assignment -name SEED {seed}", 'set_global_assignment -name FITTER_EFFORT "FAST FIT"']


def write_design(name, u0, u1, port, tag, rcf=None, seed=1):
    import cycloneiv_forced as cf
    import cycloneiv_fuzz as fz
    import toolchain
    d = CORPUS / name
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "src" / "top.v").write_text(verilog(port, tag))
    if rcf:
        (d / "src" / "force.rcf").write_text(rcf)
    ver = re.search(r"quartus-([\d.]+)", toolchain.quartus_bin())
    q = qsf(u0, u1, {"tag": tag, "rcf": bool(rcf)}, seed)
    import datetime
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "hop specimen {name}"\nexercises = {fz.toml_list(["routing", "forced", "hop_specimen"])}\n'
        f"qsf = {fz.toml_list(q)}\ndevice = \"{cf.DEVICE}\"\ntool = \"quartus\"\n"
        f'tool_version = "{ver.group(1) if ver else "unknown"}"\nbuilt = "{datetime.date.today().isoformat()}"\n')


def rcf_text(base_rcf, chain_names, dest_cell, port, net):
    """base RCF (u0_o has no route there) + the forced u0_o signal."""
    head = base_rcf.rstrip("\n") + "\n"
    els = "".join(f"\t{t}:X{x}Y{y}S0I{i};\n" for t, x, y, i in chain_names)
    return head + f"signal_name = {net} {{\n{els}\tdest = ( {dest_cell}, DATA{port} ), route_port = DATA{port};\n}}\n"


def realised(name, tag):
    """Post-fit route of net u0_o<tag>: ([(type,x,y,I)...], [(dest, port)]) or None."""
    f = CORPUS / name / "routing.rcf"
    if not f.exists():
        return None
    m = re.search(r"signal_name = u0_o%s \{\n(.*?)\n\}" % tag, f.read_text(), re.S)
    if not m:
        return None
    els = [(e[0], int(e[1]), int(e[2]), int(e[3])) for e in re.findall(r"\t(\w+):X(\d+)Y(\d+)S0I(\d+);", m.group(1))]
    ds = re.findall(r"dest = \( (\w+), DATA(\w) \)", m.group(1))
    return els, ds


def other_signals(text, net):
    """RCF text without the forced net's signal block (the part that must be identical base vs spec)."""
    return re.sub(r"signal_name = %s \{\n.*?\n\}\n?" % re.escape(net), "", text, flags=re.S)


def arc_geometry(plan, arc):
    mux = next(m for m in plan["muxes"] if m["mux"] == arc["mux"])
    names = [tuple(n) for n in arc["chain_names"]]
    lb = names[0]
    n0 = n_of_i(lb[3])
    u0 = (lb[1], lb[2], n0)
    if mux["kind"] == "LI":
        path = names + [tuple(mux["mux_name"])]
        dest = tuple(mux["mux_name"])
    else:
        path = names + [tuple(mux["mux_name"]), tuple(mux["down_name"])]
        dest = tuple(mux["down_name"])
    n1 = 6 if (u0[0], u0[1], 6) != (dest[1], dest[2], 6) else 8
    u1 = (dest[1], dest[2], n1)
    port = LI_PORT[dest[3]]
    return u0, u1, port, path


def finish(n):
    for sub in ("quartus/db", "quartus/incremental_db"):
        shutil.rmtree(CORPUS / n / sub, ignore_errors=True)
    (CORPUS / n / "quartus" / "build.rbf").unlink(missing_ok=True)


def build_names(names, jobs):
    import build_pool
    import cycloneiv_fuzz as fz

    def one(n):
        f = fz.build_one(n)
        finish(n)
        log.info("%s: %s", n, "ok" if f is None else f"FAIL at {f}")
        return n, f
    return dict(build_pool.map_adaptive(one, names, max_workers=jobs))


def jobs_of(plan, only_arcs=None):
    out = []
    for arc in plan["arcs"]:
        if arc["status"] != "planned":
            continue
        out.append(arc)
    return out


def nm(arc):
    return f"{PFX}_{arc['kind'].lower()}_{arc['src']}"


def cmd_build(a):
    plan = json.loads((TMP / "plan.json").read_text())
    arcs = jobs_of(plan)
    jobs = min(a.jobs, 16)
    todo_b = []
    for arc in arcs:
        u0, u1, port, path = arc_geometry(plan, arc)
        write_design(nm(arc) + "_b", u0, u1, None, "")
        todo_b.append(nm(arc) + "_b")
    first = arcs[0]
    u0, u1, port, path = arc_geometry(plan, first)
    nulls = []
    if a.only != "arcs":
        # null controls need the first base's own RCF pinned: build that base first, alone
        res = build_names([nm(first) + "_b"], 1)
        if any(res.values()):
            sys.exit(f"base build failed: {res}")
        base_rcf = (CORPUS / (nm(first) + "_b") / "routing.rcf").read_text()
        for tag, seed, kind in (("r", 1, "rename"), ("", 2, "seed")):
            for role in ("b", "s"):
                name = f"{PFX}_null_{kind}_{role}"
                rcf = base_rcf if tag == "" else re.sub(r"\bu1\b", "u1" + tag, base_rcf)
                if role == "s":
                    rcf = rcf_text(rcf, path, "u1" + tag, port, "u0_o" + tag)
                write_design(name, u0, u1, port if role == "s" else None, tag, rcf=rcf, seed=seed)
                nulls.append(name)
        res = build_names(nulls + [nm(first) + "_s"] if False else nulls, jobs)
        log.info("null control builds: %s", res)
        # the original spec of the first arc (built here so the nulls can be compared to it)
        write_design(nm(first) + "_s", u0, u1, port, "", rcf=rcf_text(base_rcf, path, "u1", port, "u0_o"))
        res = build_names([nm(first) + "_s"], 1)
        bad = null_report(first)
        if bad:
            sys.exit(f"NULL CONTROL FAILED: {bad}; nothing else is trusted")
        if a.only == "null":
            return
    todo_b = [n for n in todo_b if not (CORPUS / n / "routing.rcf").exists()]
    log.info("base builds: %d", len(todo_b))
    log.info("base results: %s", {k: v for k, v in build_names(todo_b, jobs).items() if v})
    todo_s = []
    for arc in arcs:
        n = nm(arc) + "_s"
        if (CORPUS / n / "routing.rcf").exists():
            continue
        brcf = CORPUS / (nm(arc) + "_b") / "routing.rcf"
        if not brcf.exists():
            log.info("%s: base missing, spec skipped", nm(arc))
            continue
        u0, u1, port, path = arc_geometry(plan, arc)
        write_design(n, u0, u1, port, "", rcf=rcf_text(brcf.read_text(), path, "u1", port, "u0_o"))
        todo_s.append(n)
    log.info("spec builds: %d", len(todo_s))
    log.info("spec results: %s", {k: v for k, v in build_names(todo_s, jobs).items() if v})


def bits(name):
    import cycloneiv_corpus as cc
    return set(cc.load_plane_only(name).keys.tolist())


def null_report(first):
    """Raw diffs of the four null builds against their originals; returns the non-empty ones."""
    b0, s0 = bits(nm(first) + "_b"), bits(nm(first) + "_s")
    bad = {}
    for kind in ("rename", "seed"):
        for role, ref in (("b", b0), ("s", s0)):
            n = f"{PFX}_null_{kind}_{role}"
            if not (CORPUS / n / "bitstream.rbf").exists():
                bad[n] = "no bitstream"
                continue
            d = bits(n) ^ ref
            log.info("null control %-22s vs original: %d differing cells", n, len(d))
            if d:
                bad[n] = len(d)
    return bad


def honoured(plan, arc):
    """The spec's post-fit u0_o route equals the forced path + dest, and every other net is unchanged vs the base."""
    u0, u1, port, path = arc_geometry(plan, arc)
    r = realised(nm(arc) + "_s", "")
    if r is None:
        return False, "no route for u0_o in the post-fit RCF"
    els, ds = r
    if els != [tuple(p) for p in path] or ds != [("u1", port)]:
        return False, f"realised {els} {ds}"
    sb = CORPUS / (nm(arc) + "_b") / "routing.rcf"
    ss = CORPUS / (nm(arc) + "_s") / "routing.rcf"
    ob = re.sub(r"^###.*\n", "", other_signals(sb.read_text(), "u0_o"), flags=re.M)
    os_ = re.sub(r"^###.*\n", "", other_signals(ss.read_text(), "u0_o"), flags=re.M)
    if ob != os_:
        return False, "other nets rerouted"
    return True, ""


def hop_fit(G_bits, flipped, spec_set=None):
    """Hop-level test: 'exact' = all group cells flipped; else the rigid (dframe, dv) shifts that put all of them
    inside the flipped set ('shift', smallest first), or 'none'."""
    F = set(flipped)
    if not G_bits:
        return "empty", None
    if set(G_bits) <= F:
        return "exact", None
    if spec_set is not None and set(G_bits) <= spec_set:
        return "preset", sum(1 for c in G_bits if c not in F)      # some group cells already set in the base (idle code)
    g0 = G_bits[0]
    sh = []
    for f in sorted(F):
        d = f - g0                  # flat difference; recover (dframe, dv) below
        df, dv = divmod(f, NV)[0] - divmod(g0, NV)[0], divmod(f, NV)[1] - divmod(g0, NV)[1]
        if all((c // NV + df) * NV + (c % NV + dv) in F for c in G_bits):
            sh.append((df, dv))
    sh.sort(key=lambda t: abs(t[0]) + abs(t[1]))
    return ("shift", sh[:2]) if sh else ("none", None)


def cmd_analyse(a):
    plan = json.loads((TMP / "plan.json").read_text())
    G = Graph()
    res = []
    for arc in plan["arcs"]:
        row = {k: arc[k] for k in ("mux", "kind", "src", "class", "status", "tier") if k in arc}
        row["why"] = arc.get("why")
        if arc["status"] != "planned":
            res.append(row)
            continue
        n = nm(arc)
        if not (CORPUS / (n + "_s") / "bitstream.rbf").exists() or not (CORPUS / (n + "_b") / "bitstream.rbf").exists():
            row.update(status="not-built")
            res.append(row)
            continue
        ok, why = honoured(plan, arc)
        B, S_ = bits(n + "_b"), bits(n + "_s")
        on, off = sorted(S_ - B), sorted(B - S_)
        mux = next(m for m in plan["muxes"] if m["mux"] == arc["mux"])
        recs = list(arc["chain"]) + [mux["mux"]] + ([mux["down"]] if mux["kind"] != "LI" else [])
        hops, P, dropped = [], set(), 0
        for s_, d_ in zip(recs[:-1], recs[1:]):
            gb = G.group_bits(s_, d_)
            if gb is None:
                hops.append({"hop": [s_, d_], "bits": None})
                continue
            fit, sh = hop_fit(gb[0], on, S_)
            sib = []
            if fit in ("none", "shift"):        # does another input of the same mux own the cells that flipped?
                srcs_d, _ks = G.fanin(d_)
                for t in srcs_d.tolist():
                    gt = G.group_bits(t, d_)
                    if t != s_ and gt and gt[0] and set(gt[0]) <= set(on) and set(gt[0]) != set(gb[0]):
                        sib.append({"sibling": t, "rec_diff": t - s_, "k_self": G.edge_k(s_, d_), "k_sib": G.edge_k(t, d_), "cells": len(gt[0])})
            hops.append({"hop": [s_, d_], "bits": gb[0], "dropped": gb[1], "classes": [G.klass(s_), G.klass(d_)], "fit": fit,
                         "shift": sh, "siblings": sib})
            P |= set(gb[0])
            dropped += gb[1]
        row.update(honoured=ok, why=why if not ok else None, on=on, off=off, hops=hops, n_pred=len(P), dropped=dropped,
                   pred_missing=sorted(P - set(on)), extra=sorted(set(on) - P), off_n=len(off), geometry=arc_geometry(plan, arc))
        res.append(row)
    # per mux: modal residual R among honoured arcs
    for m in plan["muxes"]:
        rows = [r for r in res if r["mux"] == m["mux"] and r.get("honoured")]
        modal = collections.Counter(tuple(r["extra"]) for r in rows).most_common(1)
        R = set(modal[0][0]) if modal else set()
        for r in rows:
            r["resid_equal"] = set(r["extra"]) == R
            r["exact"] = (not r["pred_missing"]) and r["resid_equal"] and r["off_n"] == 0
        m["modal_resid_n"] = len(R)
    hopstat = collections.defaultdict(collections.Counter)
    for r in res:
        for h in r.get("hops", ()) if r.get("honoured") else ():
            hopstat[tuple(h.get("classes", ["?", "?"]))][h.get("fit", "nobits") + (f" {h['shift'][0]}" if h.get("shift") else "")] += 1
    for r in res:
        for h in r.get("hops", ()) if r.get("honoured") else ():
            if h.get("siblings"):
                log.info("SIBLING src %s -> %s (%s -> %s): flipped cells = group of %s", h["hop"][0], h["hop"][1], h["classes"][0],
                         h["classes"][1], [(x["sibling"], "rec%+d" % x["rec_diff"], "edge k %s->%s" % (x["k_self"], x["k_sib"])) for x in h["siblings"]])
    for k, c in sorted(hopstat.items()):
        log.info("HOP %s -> %s: %s", k[0], k[1], dict(c))
    (TMP / "results.json").write_text(json.dumps({"plan_lab": plan["lab"], "rows": res, "muxes": plan["muxes"]}, default=int))
    for m in plan["muxes"]:
        rs = [r for r in res if r["mux"] == m["mux"]]
        pl = [r for r in rs if r["status"] != "not-forceable"]
        ho = [r for r in pl if r.get("honoured")]
        sizes = sorted(len(r["on"]) for r in ho)
        for t in "AB":
            pt = [r for r in pl if r.get("tier") == t and r["status"] != "not-built"]
            log.info("  tier %s: built %d, honoured %d", t, len(pt), sum(1 for r in pt if r.get("honoured")))
        log.info("MUX %s idx %d %s: fan-in %d, forceable %d, built %d, honoured %d, flipped-set sizes %s, "
                 "asm-subset %d, resid-equal %d, exact %d, modal residual %d cells", m["kind"], m["idx"], m["mux_name"],
                 len(m["fanin"]), len(pl), sum(1 for r in pl if r["status"] != "not-built"), len(ho), sizes,
                 sum(1 for r in ho if not r["pred_missing"]), sum(1 for r in ho if r["resid_equal"]),
                 sum(1 for r in ho if r["exact"]), m["modal_resid_n"])
        for r in ho:
            log.info("  src %d (%s) tier %s: flipped %d, asm-predicted %d, predicted-not-flipped %d, beyond-asm %d, base-only %d, dropped %d, "
                     "resid==modal %s exact %s", r["src"], r["class"], r.get("tier"),
                     len(r["on"]), r["n_pred"], len(r["pred_missing"]), len(r["extra"]), r["off_n"], r["dropped"], r["resid_equal"], r["exact"])
        for r in pl:
            if r["status"] != "not-built" and not r.get("honoured"):
                log.info("  src %d (%s) NOT honoured: %s", r["src"], r["class"], r["why"])


def register_build(conn, name, purpose):
    """corpus_builds row for a build dir (idempotent on design); returns its id."""
    import datetime
    import hashlib
    import tomllib
    from sqlalchemy import insert, select
    import sqlalchemy as sa
    import schema
    # a database created before the postfit_builds -> corpus_builds rename still has the FK pointing at the old table
    fk = [row[2] for row in conn.exec_driver_sql("PRAGMA foreign_key_list(evidence)") if row[3] == "build_base"] \
        if conn.dialect.name == "sqlite" else ["corpus_builds"]
    t = schema.corpus_builds.to_metadata(sa.MetaData(), name=fk[0] if fk else "corpus_builds")
    r = conn.execute(select(t.c.id).where(t.c.design == name)).fetchone()
    if r:
        return r[0]
    d = CORPUS / name
    spec = tomllib.loads((d / "design.toml").read_text())
    shas = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((d / "src").iterdir())}
    return conn.execute(insert(t).values(
        design=name, family="cycloneiv", device=spec["device"], top=spec["top"], toolchain="Quartus Prime " + spec.get("tool_version", ""),
        src_sha256=shas, qsf=spec.get("qsf", []), purpose=purpose, exercises=spec.get("exercises"),
        built_at=datetime.datetime.now().astimezone(), out_dir=str(d.relative_to(REPO)), lift_label=None,
        status="ok")).inserted_primary_key[0]


def cmd_record(a):
    import db
    from provenance import evidence_io as E
    res = json.loads((TMP / "results.json").read_text())
    commit = E.git_head(REPO)
    n = 0
    with db.engine().begin() as conn:
        E.ensure_family(conn, "cycloneiv")
        for r in res["rows"]:
            if r["status"] not in ("planned",) or "on" not in r:
                continue
            name = f"{PFX}_{r['kind'].lower()}_{r['src']}"
            bid = register_build(conn, name + "_b", "hop specimen base")
            sid = register_build(conn, name + "_s", "hop specimen forced single path")
            meta = {"group": "hop_specimen", "lab": res["plan_lab"], "mux_kind": r["kind"], "mux_record": r["mux"],
                    "src_record": r["src"], "src_class": r["class"], "honoured": r["honoured"], "why": r["why"],
                    "n_asm_predicted": r["n_pred"], "predicted_not_flipped": len(r["pred_missing"]),
                    "flipped_beyond_asm": len(r["extra"]), "exact": r.get("exact"), "resid_equal": r.get("resid_equal"),
                    "asm_dropped_out_of_band": r["dropped"], "plane_level": True}
            E.record_specimen(conn, "cycloneiv", "EP4CGX150", name, name + "_b", r["on"], r["off"], meta,
                              f"hop_specimen:{r['kind']}", "scripts/cycloneiv_hop_specimens.py", commit, NV,
                              tool_version="25.1", build_base=bid, build_spec=sid)
            n += 1
    log.info("recorded %d evidence rows (specimen-pair, build_base/build_spec set)", n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("names", "plan", "build", "analyse", "record"))
    ap.add_argument("--only", default="")
    ap.add_argument("--lab", default=None, help="override the planned LAB, X,Y")
    ap.add_argument("--jobs", type=int, default=16)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_hop_specimens.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    main()
