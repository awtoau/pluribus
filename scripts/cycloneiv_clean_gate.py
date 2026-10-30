#!/usr/bin/env python3.15t
"""Clean P3 gate: score lifters/cycloneiv_clean/tracer.py against Quartus ground truth (docs/cycloneiv-clean-pipeline.md, #165).

  PLURIBUS_SQLITE_PATH=databases/cycloneiv/gx150.db python3.15t scripts/cycloneiv_clean_gate.py --set rb10 [--record]
  python3.15t scripts/cycloneiv_clean_gate.py --set corpus --root <corpus-rebuild-dir>/cycloneiv-<stamp> [--limit N] [--record]

Ground truth per design (Quartus outputs of the build): routing.rcf (pips, nets, LUT pin routing, FF clock nets), postfit.vo
(LUT masks, FF sites, pin locations), build.pin (pin direction).  Plane = bitstream.rbf.  The corpus root is read only.
Per category: matched / (matched + missing + extra + wrong); a missing connection is a fault, ambiguous = missing.
  pips      GT edge (RCF parent -> child, exact names, edge exists in routing.ddb) programmed by the tracer = matched; GT edge not
            programmed and unresolvable (name / not in graph) = missing; GT edge not programmed while another source drives its
            destination = wrong; programmed edge with no GT edge at its destination = extra.
  nets      per RCF net: tracer reach from the net roots equals the GT edge set (matched); only GT edges absent = missing;
            only surplus edges = extra; both = wrong.  Tracer root trees touching no GT edge count as extra nets.
  lut_init  per LE with a combinational GT LUT: tracer cells == .vo lut_mask with cell index 15 - l (O1; the .vo ports are the
            physical post-fit pins: q102~0 sits on datab where the RCF route_port says DATAB, so no RCF permutation applies).
            Arithmetic-mode LEs use the same relation (one LE_LUT_FUNCTION group per LE, no mode variant in the asmdb); the LE_USE_CARRY
            bit is compared with the .vo sum_lutc_input (clear = cin) and logged beside.  Cells differ = wrong; tracer LE with set cells
            and no GT LUT = extra.
  register_clock  per GT FF: the tracer's claim for that (LAB, LE) = BLK_CLK_BUF line chosen by LE_CLOCK_SELECT + LAB_CLOCK_FAST_MUX
            (clocks.py); the programmed tree(s) containing that BLK_CLK_BUF all have the GT clock-net root = matched; no line / no tree =
            missing; some roots match = ambiguous = missing; none match = wrong.  extra = every (LAB, LE) with a register claim and no FF in the .vo.  The claim needs the register-used decode (reg_used.py: YGR output select x used LE_BUFFER); undecidable = no claim = missing.
  pins      GT design-port balls (build.pin x .vo ports, minus `~ALTERA_*~` configuration pseudo-ports, counted in pins_scope) vs the package
            ball -> site map of the design's part (device.db pin count -> pkg ddb) and the full io_fields class of the site (clock pads: blocks
            60 / 61).  matched = site `used` and direction word equal; direction candidates > 1 = missing (`ambiguous_direction`); site not used /
            no site = missing; direction differs = wrong; extra = `used` site whose ball is no design port.  Standard is NOT scored: CFF-identical
            standards (2.5 V = 3.0 / 3.3 V LVTTL / LVCMOS / PCI inputs) are one equivalence class, counted in pins_scope `matched_standard_equivalence_class`.
No rule changes between runs: headline variant `vendor`; `vendor_nx` (no destination exclusion check) is reported beside it.
Log: tmp/logs/cycloneiv_clean_gate.log; results tmp/cycloneiv_clean/gate_<set>.json.
"""
import argparse
import collections
import concurrent.futures as cf
import glob
import json
import logging
import os
import re
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import ddb, names  # noqa: E402
from lifters.cycloneiv_clean import tracer as T  # noqa: E402

log = logging.getLogger("cycloneiv_clean_gate")
HEADLINE = "vendor"                     # asm.ddb conduction rule from the vendor assembler (tracer.py docstring, #165); replaces the delta-byte flag rule
VARIANTS = ("vendor", "vendor_nx")
CATS = ("pips", "nets", "lut_init", "register_clock", "pins")
REGION = 30                             # region bands of dst tile x / y for the failing-scope enumeration
FILES = ("bitstream.rbf", "routing.rcf", "postfit.vo", "build.pin")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_gate.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean")
# source: Quartus lcell input port order; lut_mask index = a + 2 b + 4 c + 8 d (cycloneiv_lcell_comb primitive)
PORTS = ("DATAA", "DATAB", "DATAC", "DATAD")


# source: io_fields.DIRECTION direction words (pair-build kinds) vs the build.pin direction column
DIRWORD = {"input": "input", "output": "output", "bidir": "bidir-or-tristate"}
# source: Quartus pseudo-ports `~ALTERA_DCLK~` (dedicated configuration pin DCLK, listed as an output in every build): not a design port
CONFIG_PSEUDO = "~ALTERA_"


def counts():
    return {"matched": 0, "missing": 0, "extra": 0, "wrong": 0}


def headline(c):
    t = sum(c.values())
    return 100.0 * c["matched"] / t if t else 100.0


# ---- ground truth from the vo / pin files ---------------------------------------------------------------------------------------------

def parse_vo(path):
    text = open(path).read()
    ports = {m[1]: m[2] for m in re.finditer(r"^// (\S+)\t=>  Location: PIN_(\w+),", text, re.M)}
    lcs, ffs = {}, {}
    for blk in text.split("\n// Location: ")[1:]:
        head, _, body = blk.partition("\n")
        m = re.match(r"(LCCOMB|FF)_X(\d+)_Y(\d+)_N(\d+)$", head.strip())
        if not m:
            continue
        x, y, n = int(m[2]), int(m[3]), int(m[4]) // 2        # N = 2 * LE index (+ 1 for the FF half)
        nm = re.match(r"(?:cycloneiv_lcell_comb|dffeas) (\S+?)\s*\(", body)
        if not nm:
            continue
        name = nm[1].lstrip("\\")
        if m[1] == "FF":
            ffs[name] = (x, y, n)
            continue
        con = {p: v for p, v in re.findall(r"\.(data[abcd]|cin)\((.*?)\)", body)}
        mask = re.search(r"\.lut_mask = 16'h([0-9A-Fa-f]{4})", body)
        mode = re.search(r"\.sum_lutc_input = \"(\w+)\"", body)
        cout = re.search(r"\.cout\((.*?)\)\);", body)
        lcs[(x, y, n)] = dict(name=name, mask=int(mask[1], 16) if mask else None, mode=mode[1] if mode else None,
                              arith=bool(cout and cout[1].strip()) or con.get("cin", "gnd").strip() != "gnd" or (mode and mode[1] != "datac"),
                              live=[p.upper() for p in PORTS_LOWER if con.get(p, "gnd").strip() not in ("gnd", "vcc", "")])
    return ports, lcs, ffs


# source: Quartus lcell input port names (cycloneiv_lcell_comb primitive)
PORTS_LOWER = ("dataa", "datab", "datac", "datad")


def parse_ff_q(path):
    """{dffeas instance name: its .q net name without escape / '~q'}: the RCF names a register by its output net (`r1_8_q`) when that differs from the instance (`r1_8`)."""
    out = {}
    for m in re.finditer(r"dffeas (\S+?)\s*\(.*?\.q\((.*?)\)", open(path).read(), re.S):
        out[m[1].lstrip("\\")] = re.sub(r"~q$", "", m[2].strip().lstrip("\\"))
    return out


def parse_pin(path):
    out = {}
    for line in open(path):
        f = [s.strip() for s in line.split(":")]
        if len(f) >= 3 and f[2] in ("input", "output", "bidir"):
            out[f[0]] = (f[1], f[2])
    return out


def lut_expected(mask):
    """Cell vector of one LE: cell[15 - l] = INIT bit l, l = a + 2 b + 4 c + 8 d of the .vo ports (O1: RBLUT index = complement)."""
    return tuple((mask >> (15 - m)) & 1 for m in range(16))


# ---- one design -----------------------------------------------------------------------------------------------------------------------

class Ctx:
    """Shared, read-only per-run state."""

    def __init__(self):
        t0 = time.time()
        self.rt = ddb.Routing()
        self.st = T.Static()
        self.res = T.Resolver(self.rt)
        self.lut = T.Lut()
        self.ext = T.Extras(self.st, self.lut, self.rt)
        self.st.edge_ids([0], [0])          # build the (src, dst) key index (after the implicit edges are appended) before worker threads start
        self.io = T.Io()
        from lifters.cycloneiv_clean import io_decode as ID, io_fields as IF, io_pins as IP
        self.pm = IP.PinMap(self.io, IF.Decoder(json.load(open(ID.DECODE_PATH))))
        self.enum = np.where(self.rt.tpl >= 0, self.rt.enum[np.maximum(self.rt.tpl, 0)].astype(np.int32), -1)
        self.tname = {v: k for k, v in names.enums().items()}
        blk = names.enum_of("BLK_CLK_BUF")
        sel = np.flatnonzero(self.enum == blk)
        self.blk = collections.defaultdict(list)
        for r in sel.tolist():
            self.blk[(int(self.rt.x[r]), int(self.rt.y[r]))].append(r)
        log.info("context ready in %.1fs", time.time() - t0)

    def tn(self, rec):
        return self.tname.get(int(self.enum[rec]), str(int(self.enum[rec])))


def score_design(cx, d, fire_workers):
    t0 = time.time()
    st, rt = cx.st, cx.rt
    bits = T.plane_bits(os.path.join(d, "bitstream.rbf"))
    fired = cx.ext.apply(bits, st.fire(bits, workers=fire_workers))
    nets = T.parse_rcf(os.path.join(d, "routing.rcf"))
    allnames = sorted({e for n in nets for pc in n["edges"] for e in pc} | {r for n in nets for r in n["roots"]})
    idx = {n: i for i, n in enumerate(allnames)}
    rec, why = cx.res.resolve(allnames)
    # GT edges
    gt_edges, unres = {}, collections.Counter()
    net_gt = []
    for n in nets:
        eid, u = set(), 0
        for a, b in n["edges"]:
            ra, rb = rec[idx[a]], rec[idx[b]]
            if ra < 0 or rb < 0:
                u += 1
                unres[("name:" + str(why[idx[a]] if ra < 0 else why[idx[b]]), a[0], b[0])] += 1
                continue
            e = int(st.edge_ids([ra], [rb])[0])
            if e < 0:
                u += 1
                unres[("not_in_graph", a[0], b[0])] += 1
            else:
                eid.add(e)
                gt_edges[e] = True
        roots = [int(rec[idx[r]]) for r in n["roots"]]
        net_gt.append((n, eid, u, roots))
    G = set(gt_edges)
    n_unres = sum(unres.values())
    out = {"design": os.path.basename(d), "gt_edges": len(G), "gt_unresolved": n_unres,
           "unresolved": {"|".join(k): v for k, v in unres.items()}}
    # ---- pips, all variants
    scope = {k: collections.Counter() for k in ("missing", "extra", "wrong")}
    out["pips_variants"] = {}
    for v in VARIANTS:
        Pr = set(fired[v].tolist())
        c = counts()
        c["matched"] = len(G & Pr)
        miss, ext = G - Pr, Pr - G
        # wrong = a missing GT edge paired with a surplus edge at the same destination (one pair per missing edge); the rest keep their own column
        mq, xq = collections.defaultdict(list), collections.defaultdict(list)
        for e in miss:
            mq[int(st.edst[e])].append(e)
        for e in ext:
            xq[int(st.edst[e])].append(e)
        W, ex, mset = [], [], []
        for d_, ms in mq.items():
            k_ = min(len(ms), len(xq.get(d_, ())))
            W += ms[:k_]
            mset += ms[k_:]
        for d_, xs in xq.items():
            ex += xs[min(len(xs), len(mq.get(d_, ()))):]
        c["wrong"], c["extra"], c["missing"] = len(W), len(ex), len(mset) + n_unres
        out["pips_variants"][v] = c
        if v == HEADLINE:
            out["pips"] = c
            for kind, es in (("missing", mset), ("extra", ex), ("wrong", W)):
                for e in es:
                    s_, d_ = int(st.esrc[e]), int(st.edst[e])
                    scope[kind][(cx.tn(s_), cx.tn(d_), int(rt.x[d_]) // REGION, int(rt.y[d_]) // REGION)] += 1
            for (why_, ta, tb), k in unres.items():
                scope["missing"][(ta, tb, "unresolved:" + why_, -1)] += k
    out["mux_ambiguous"] = cx.ext.imp.n_ambiguous(bits)       # LAB_CONTROL_MUX selections whose aux / nxt table entry is ambiguous (-2): not decoded
    out["pips_scope"] = {kind: {"|".join(map(str, k)): v for k, v in c.items()} for kind, c in scope.items()}
    # ---- nets
    g = T.Graph(st, fired[HEADLINE])
    roots = g.roots()
    gt_root_recs = {r for _, _, _, rs in net_gt for r in rs if r >= 0}
    nc = counts()
    covered = set()
    for n, eid, u, rs in net_gt:
        if not n["edges"]:
            continue
        R = set(g.reach([r for r in rs if r >= 0]))
        covered |= R
        miss = (eid - R) or u or any(r < 0 for r in rs)
        extra = R - eid
        nc["matched" if not miss and not extra else "wrong" if miss and extra else "missing" if miss else "extra"] += 1
    for r in roots:
        if r not in gt_root_recs and not (set(g.reach([r])) & G):
            nc["extra"] += 1
    out["nets"] = nc
    # ---- LUT INIT
    ports, lcs, ffs = parse_vo(os.path.join(d, "postfit.vo"))
    cells = cx.lut.cells(bits).astype(np.uint8)
    carry = cx.lut.carry_in(bits)
    lc, why_l = counts(), collections.Counter()
    gt_sites = set()
    for (x, y, nn), L in lcs.items():
        i = cx.lut.lab(x, y)
        gt_sites.add((i, nn))
        if i >= 0:
            why_l["carry_flag_agrees" if (L["mode"] == "cin") == bool(carry[i, nn]) else "carry_flag_differs"] += 1
        if i < 0 or L["mask"] is None:
            lc["missing"] += 1
            why_l["site_or_mask_unresolved"] += 1
        elif L["arith"]:
            ok = tuple(int(b) for b in cells[i, nn]) == lut_expected(L["mask"])
            lc["matched" if ok else "wrong"] += 1
            why_l["arithmetic_cells_equal" if ok else "arithmetic_cells_differ"] += 1
        else:
            ok = tuple(int(b) for b in cells[i, nn]) == lut_expected(L["mask"])
            lc["matched" if ok else "wrong"] += 1
            why_l["cells_equal" if ok else "cells_differ"] += 1
    nz = np.argwhere(cells.sum(axis=2) > 0)
    lc["extra"] = sum(1 for i, nn in nz.tolist() if (i, nn) not in gt_sites)
    out["lut_init"], out["lut_scope"] = lc, dict(why_l)
    # ---- register clock
    node_roots = collections.defaultdict(set)
    for r in roots:
        node_roots[r].add(r)
        for e in g.reach([r]):
            node_roots[int(st.edst[e])].add(r)
    gt_clk = {}
    for n in nets:
        rs = [int(rec[idx[r]]) for r in n["roots"] if rec[idx[r]] >= 0]
        for last, cell, port, rp in n["dests"]:
            if port == "CLK":
                gt_clk[cell] = rs
    rc, why_r = counts(), collections.Counter()
    blk = cx.ext.clocks.le_blk(bits)                    # tracer claim: BLK_CLK_BUF record per (LAB, LE) from LAB clock mux + LE_CLOCK_SELECT
    ffm = cx.ext.reg.ff(bits, fired[HEADLINE])          # register-used claim (reg_used.py); undecidable = no claim
    blk = np.where(ffm, blk, -1)
    gt_sites_ff = set()
    qname = parse_ff_q(os.path.join(d, "postfit.vo"))
    for name, (x, y, nn) in ffs.items():
        i = cx.lut.lab(x, y)
        gt_sites_ff.add((i, nn))
        gr = gt_clk.get(name) or gt_clk.get(qname.get(name))
        if not gr:
            rc["missing"] += 1
            why_r["gt_clock_unresolved"] += 1
            continue
        b = int(blk[i, nn]) if i >= 0 else -1
        if b < 0:
            rc["missing"] += 1
            why_r["no_ff_claim_or_no_clock_line"] += 1
            continue
        cand = node_roots.get(b, set())
        if not cand:
            rc["missing"] += 1
            why_r["selected_line_not_in_a_programmed_tree"] += 1
            continue
        has = cand & set(gr)
        if has == cand:
            rc["matched"] += 1
        elif not has:
            rc["wrong"] += 1
            why_r["clock_net_differs"] += 1
        else:
            rc["missing"] += 1
            why_r["ambiguous_clock_roots"] += 1
    claimed = np.argwhere(blk >= 0)
    rc["extra"] = sum(1 for i, nn in np.argwhere(ffm).tolist() if (i, nn) not in gt_sites_ff)     # decoder-level: every register claim (reg_used) without a vo register, clock line or not
    out["register_clock"], out["clock_scope"] = rc, dict(why_r)
    # ---- pins: full io_fields classification per package ball (io_pins.PinMap)
    pins_gt = parse_pin(os.path.join(d, "build.pin"))
    gt_balls = {b: dirn for nm_, (b, dirn) in pins_gt.items() if nm_ in ports and not nm_.startswith(CONFIG_PSEUDO)}
    all_balls = {b for nm_, (b, dirn) in pins_gt.items() if nm_ in ports}
    dev = re.search(r"device = (\w+);", open(os.path.join(d, "routing.rcf")).read(600))[1]
    val_cff, _ = cx.io.cff.read(os.path.join(d, "bitstream.rbf"))
    cls = cx.pm.classify(val_cff, dev)
    pc, pscope = counts(), collections.Counter()
    for b, dirn in gt_balls.items():
        c = cls.get(b)
        if c is None:
            pc["missing"] += 1
            pscope["missing_no_site"] += 1
        elif c["class"] != "used":
            pc["missing"] += 1
            pscope["missing_site_" + c["class"]] += 1
        elif c["dir"] == "ambiguous":
            pc["missing"] += 1                                  # direction candidates > 1: ambiguous = missing
            pscope["ambiguous_direction"] += 1
        elif c["dir"] == DIRWORD[dirn]:
            pc["matched"] += 1
            if c["std_ambiguous"]:
                pscope["matched_standard_equivalence_class"] += 1
        else:
            pc["wrong"] += 1
    pc["extra"] = sum(1 for b, c in cls.items() if c["class"] == "used" and b not in all_balls)
    pscope["excluded_config_pseudo_ports"] = len(all_balls) - len(gt_balls)
    out["pins"], out["pins_scope"] = pc, dict(pscope)
    out["seconds"] = round(time.time() - t0, 2)
    return out


# ---- run ------------------------------------------------------------------------------------------------------------------------------

# source: Dan 2026-10-30: rb_006 / rb_009 dropped from the corpus (survivors rb_000..005, 007, 008)
RB_SURVIVORS = (0, 1, 2, 3, 4, 5, 7, 8)
# source: Dan 2026-10-30 gate tiers: fast = reference/gate_fast.tsv (100 designs), full = reference/corpus_keep.tsv (kept corpus), dji = image row, extensive = later
TIER_LISTS = {"fast": "gate_fast.tsv", "full": "corpus_keep.tsv"}
TIERS = ("fast", "dji", "full", "extensive")


def tier_designs(tier):
    ds = []
    for line in open(os.path.join(REPO, "reference", TIER_LISTS[tier])).read().splitlines()[1:]:
        d = os.path.join(REPO, "corpus", "cycloneiv", line.split("\t")[0])
        if all(os.path.exists(os.path.join(d, f)) for f in FILES):
            ds.append(d)
        else:
            log.warning("tier %s: %s incomplete / missing, skipped", tier, os.path.basename(d))
    return ds


def design_device(d):
    """design.toml `device` of a corpus design ('' = no key: early designs default to Cyclone IV E, out of the EP4CGX150 scope)."""
    import tomllib
    try:
        return tomllib.load(open(os.path.join(d, "design.toml"), "rb")).get("device", "")
    except (OSError, ValueError):
        return ""


# source: Dan 2026-10-30 scope rule: headline = EP4CGX150 (the DJI die) on the F896 part (the pad / ball tables of the clean pipeline); other packages of the die are separate rows, never mixed in
SCOPES = {"primary": lambda dev: dev.startswith("EP4CGX150DF31"), "other_pkg": lambda dev: dev.startswith("EP4CGX150") and not dev.startswith("EP4CGX150DF31")}


def discover(args):
    ds = _discover(args)
    return [d for d in ds if SCOPES[args.scope](design_device(d))]


def _discover(args):
    if args.set == "rb10":
        return [os.path.join(REPO, "corpus", "cycloneiv", f"gx150_rb_{i:03d}") for i in RB_SURVIVORS]
    if args.tier in TIER_LISTS:
        return tier_designs(args.tier)
    ds = []
    for d in sorted(glob.glob(os.path.join(args.root, "*"))):
        if not os.path.isdir(d) or not all(os.path.exists(os.path.join(d, f)) for f in FILES):
            continue
        try:
            if json.load(open(os.path.join(d, "rebuild.json"))).get("status") != "ok":
                continue
            if "EP4CGX150" not in open(os.path.join(d, "routing.rcf")).read(600):
                continue
        except (OSError, ValueError):
            continue
        ds.append(d)
    if args.members_run:
        # exact member set of an earlier recorded run (gate_runs.params.members, else its gate_results rows): like-with-like comparison
        want = [m for m in run_members(args.members_run) if SCOPES[args.scope](design_device(os.path.join(REPO, "corpus", "cycloneiv", m.split("@")[0])))]
        have = {os.path.basename(d) + "@" + os.path.basename(args.root.rstrip("/")): d for d in ds}
        missing = [m for m in want if m not in have]
        if missing:
            raise SystemExit(f"run {args.members_run}: {len(missing)} members not complete in {args.root}: {missing[:3]}")
        return [have[m] for m in want]
    ds = ds[:: args.stride]
    return ds[: args.limit] if args.limit else ds


def run_members(run_id):
    import db
    from sqlalchemy import select
    import schema as S
    with db.engine().connect() as conn:
        return sorted(r[0] for r in conn.execute(
            select(S.corpus_members.c.name).distinct().join(S.gate_results, S.gate_results.c.member_id == S.corpus_members.c.id)
            .where(S.gate_results.c.run_id == run_id)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=("rb10", "corpus"), default="corpus")
    ap.add_argument("--tier", choices=TIERS, help="fast = reference/gate_fast.tsv; dji = image row (env PLURIBUS_DJI_IMAGE); full = reference/corpus_keep.tsv; extensive = not built yet")
    ap.add_argument("--root", help="corpus-rebuild stamp directory (read only)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--stride", type=int, default=1, help="every n-th complete design in name order (deterministic sample)")
    ap.add_argument("--members-run", type=int, help="score exactly the designs recorded in this gate_runs id (needs PLURIBUS_SQLITE_PATH)")
    ap.add_argument("--scope", choices=tuple(SCOPES), default="primary", help="primary = EP4CGX150DF31 (F896); other_pkg = other EP4CGX150 packages")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--record", action="store_true", help="write gate_runs / gate_results (PLURIBUS_SQLITE_PATH)")
    ap.add_argument("--tag", default="")
    ap.add_argument("--baseline", action="store_true", help="mark the recorded run as a baseline (params.baseline)")
    args = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    if args.tier == "extensive":
        raise SystemExit("tier extensive: extreme-design list not built yet")
    if args.tier == "dji":
        raise SystemExit(run_dji(args))
    if args.tier and not args.tag:
        args.tag = "_" + args.tier
    if not args.tier and args.set == "corpus" and not args.root:
        raise SystemExit("--root (or --tier fast|full) required for --set corpus")
    ds = discover(args)
    log.info("set=%s designs=%d workers=%d", args.set, len(ds), args.workers)
    import heavy_guard
    # declared from the first measured run (tmp/logs/lease_telemetry.jsonl); correct JOB_GB from `heavy_guard.py report`
    gb = heavy_guard.JOB_GB["cyc4_clean_gate_base"] + args.workers * heavy_guard.JOB_GB["cyc4_clean_gate_worker"]
    rows, t0 = [], time.time()
    with heavy_guard.lease(gb, "cyc4_clean_gate", log):
        cx = Ctx()
        stall = 60
        with cf.ThreadPoolExecutor(args.workers) as ex:
            futs = {ex.submit(score_design, cx, d, 2): d for d in ds}
            pending = set(futs)
            while pending:
                done, pending = cf.wait(pending, timeout=stall, return_when=cf.FIRST_COMPLETED)
                if not done:
                    log.error("stall: no design finished in %ds (%d pending, load %s)", stall, len(pending), os.getloadavg())
                    for f in pending:
                        f.cancel()
                    raise SystemExit(3)
                for f in done:
                    try:
                        r = f.result()
                    except Exception as e:  # a design that cannot be scored is a result, not a skip
                        log.error("%s: %s: %s", futs[f], type(e).__name__, e)
                        r = {"design": os.path.basename(futs[f]), "error": f"{type(e).__name__}: {e}"}
                    rows.append(r)
                    if "error" not in r:
                        log.info("%s pips %s nets %s lut %s clk %s pins %s %.1fs", r["design"], r["pips"], r["nets"], r["lut_init"],
                                 r["register_clock"], r["pins"], r["seconds"])
    rows.sort(key=lambda r: r["design"])
    good = [r for r in rows if "error" not in r]
    tot = {c: counts() for c in CATS}
    for r in good:
        for c in CATS:
            for k, v in r[c].items():
                tot[c][k] += v
    var = {v: counts() for v in VARIANTS}
    for r in good:
        for v in VARIANTS:
            for k, x in r["pips_variants"][v].items():
                var[v][k] += x
    scope = {k: collections.Counter() for k in ("missing", "extra", "wrong")}
    for r in good:
        for kind, c in r["pips_scope"].items():
            for key, v in c.items():
                scope[kind][key] += v
    log.info("DESIGNS scored %d / %d (errors %d), %.0fs", len(good), len(rows), len(rows) - len(good), time.time() - t0)
    for c in CATS:
        log.info("HEADLINE %-15s %6.2f%%  %s", c, headline(tot[c]), tot[c])
    for v in VARIANTS:
        log.info("pips variant %-6s %6.2f%%  %s%s", v, headline(var[v]), var[v], "  <- headline" if v == HEADLINE else "")
    for kind in scope:
        log.info("pips %s by (src type, dst type, dst x band, dst y band), top 25 of %d:", kind, len(scope[kind]))
        for k, v in scope[kind].most_common(25):
            log.info("   %7d  %s", v, k)
    log.info("LAB_CONTROL_MUX ambiguous selections (muxsel -2, not decoded): %d", sum(r["mux_ambiguous"] for r in good))
    for key in ("lut_scope", "clock_scope", "pins_scope"):
        agg = collections.Counter()
        for r in good:
            agg.update(r[key])
        log.info("%s %s", key, dict(agg))
    un = collections.Counter()
    for r in good:
        un.update(r["unresolved"])
    log.info("GT edges unresolved (reason|src type|dst type) top 15: %s", un.most_common(15))
    res = dict(set=args.set, root=args.root, designs=len(good), errors=[r for r in rows if "error" in r], totals=tot, pips_variants=var,
               headline={c: round(headline(tot[c]), 4) for c in CATS}, rows=rows,
               scope={k: dict(v.most_common(200)) for k, v in scope.items()})
    path = os.path.join(OUT, f"gate_{args.set}{args.tag}.json")
    json.dump(res, open(path, "w"), indent=0, default=str)
    log.info("wrote %s", path)
    reg = regression(args, tot)
    if args.record:
        record(args, good, tot, var)
    if reg:
        raise SystemExit(4)


def last_run(tier, scope, set_name):
    """summary of the latest gate_runs row of the same tier / scope / set (PLURIBUS_SQLITE_PATH), else None."""
    if not os.environ.get("PLURIBUS_SQLITE_PATH"):
        return None
    import db
    import schema
    from sqlalchemy import select
    with db.engine().connect() as conn:
        for r in conn.execute(select(schema.gate_runs).where(schema.gate_runs.c.script == "scripts/cycloneiv_clean_gate.py").order_by(schema.gate_runs.c.id.desc())):
            p = r.params if isinstance(r.params, dict) else json.loads(r.params or "{}")
            if p.get("tier") == tier and p.get("scope", "primary") == scope and p.get("set") == set_name:
                return r.id, (r.summary if isinstance(r.summary, dict) else json.loads(r.summary or "{}"))
    return None


def regression(args, tot):
    """Rule: any fault column (missing / extra / wrong) of any category above the last run of the SAME tier = regression (logged, exit 4)."""
    tier = args.tier or args.set
    prev = last_run(tier, args.scope, args.set)
    if not prev:
        log.info("regression: no earlier run of tier %s", tier)
        return False
    rid, summ = prev
    bad = [(c, k, summ["totals"][c][k], tot[c][k]) for c in CATS for k in ("missing", "extra", "wrong") if c in summ.get("totals", {}) and tot[c][k] > summ["totals"][c][k]]
    for c, k, a, b in bad:
        log.error("REGRESSION vs run %s: %s %s %d -> %d", rid, c, k, a, b)
    log.info("regression vs run %s (tier %s): %s", rid, tier, "FAIL" if bad else "none")
    return bool(bad)


# dji tier: figure -> True when a rise is worse
DJI_FIGURES = {"crc_frames_failed": True, "header_crc_bad": True, "fanin_conflict_nodes": True, "undriven_used_nodes": True, "loops_scc_gt1": True,
               "self_loop_edges": True, "ff_no_clock_line_MISSING": True, "io_sites_MISSING": True, "tier_A_pct": False, "explained_ABC_pct": False,
               "package_ground_bonded": True, "package_unbonded_not_ground": True, "package_exact": False}


def run_dji(args):
    """Image row: counts / percentages only (no image data in the DB).  Regression = a figure worse than the last dji run."""
    image = os.environ.get("PLURIBUS_DJI_IMAGE")
    if not image:
        raise SystemExit("tier dji: env PLURIBUS_DJI_IMAGE required")
    import subprocess
    import cycloneiv_clean_image as IMG
    res = IMG.run(image, 0)
    subprocess.run([sys.executable, os.path.join(REPO, "scripts", "cycloneiv_clean_setbits.py"), "--n", "1"], check=True, cwd=REPO)
    sb = json.load(open(os.path.join(OUT, "setbits.json")))["third_party_image"]
    c, r, lg = res["container"], res["routing"], res["logic"]
    fig = {"crc_frames_failed": c["cram_frame_crc_total"] - c["cram_frame_crc_pass"], "header_crc_bad": int(not c["header_crc_ok"]),
           "fanin_conflict_nodes": r["variants"][r["headline_variant"]]["fanin_conflict_nodes"], "undriven_used_nodes": r["undriven_used_nodes"],
           "loops_scc_gt1": r["loops"]["scc_gt1"], "self_loop_edges": r["loops"]["self_loop_edges"], "ff_no_clock_line_MISSING": lg["ff_no_clock_line_MISSING"],
           "io_sites_MISSING": res["io"]["fields"]["classes"].get("MISSING", 0), "tier_A_pct": round(100 * sb["tier"]["A"] / sb["set_cells"], 2),
           "explained_ABC_pct": sb["explained_ABC"],
           "decoded_luts_nonzero_init": lg["luts_nonzero_init"], "decoded_ffs_claimed": lg["les_ff_claimed"], "routing_programmed_edges": r["variants"][r["headline_variant"]]["programmed_edges"],
           "io_classes": res["io"]["fields"]["classes"], "tier_cells": sb["tier"]}
    import cycloneiv_decompress as cd
    import numpy as np
    from lifters.cycloneiv_clean import pkginfer
    pk = pkginfer.infer_bytes(np.frombuffer(bytes(cd.decompress(open(image, "rb").read(), {})), np.uint8))
    best = pk["per_package"].get(pk["package"]) if pk["package"] else min(pk["per_package"].values(), key=lambda c: c["ground_bonded"] + c["unbonded_not_ground"] + c["used_unbonded"])
    fig.update({"package_inferred": pk["package"], "package_exact": int(pk["exact"]), "package_ground_sites": pk["ground_sites"],
                "package_unbonded": best["unbonded"], "package_ground_unbonded": best["ground_unbonded"], "package_ground_bonded": best["ground_bonded"],
                "package_unbonded_not_ground": best["unbonded_not_ground"], "package_used_unbonded": best["used_unbonded"]})
    log.info("dji figures %s", json.dumps(fig))
    prev = last_run("dji", "primary", "dji")
    bad = []
    if prev:
        old = prev[1].get("figures", {})
        for k, worse_up in DJI_FIGURES.items():
            if k in old and ((fig[k] > old[k]) if worse_up else (fig[k] < old[k])):
                bad.append((k, old[k], fig[k]))
                log.error("REGRESSION vs run %s: %s %s -> %s", prev[0], k, old[k], fig[k])
    else:
        log.info("regression: no earlier dji run")
    if args.record:
        import db
        import schema
        from provenance import corpus as C
        from provenance import evidence_io as E
        schema.init()
        with db.engine().begin() as conn:
            E.ensure_family(conn, "cycloneiv")
            rid = C.record_gate_run(conn, "cycloneiv", "scripts/cycloneiv_clean_gate.py", E.git_head(REPO), {},
                                    params={"set": "dji", "tier": "dji", "scope": "primary", "tag": args.tag}, summary={"figures": fig})
        log.info("recorded gate_runs id %s (dji)", rid)
    return 4 if bad else 0


def record(args, good, tot, var):
    import db
    import schema
    from provenance import corpus as C
    from provenance import evidence_io as E
    schema.init()
    commit = E.git_head(REPO)
    suffix = "@" + os.path.basename(args.root.rstrip("/")) if args.root else ""
    results = {}
    with db.engine().begin() as conn:
        E.ensure_family(conn, "cycloneiv")
        for r in good:
            name = r["design"] + suffix
            C.ensure_member(conn, "cycloneiv", name, "oracle-build", commit, device="EP4CGX150",
                            source_ref=("corpus-rebuild/" + os.path.basename(args.root.rstrip("/")) if args.root else "corpus/cycloneiv") + "/" + r["design"], gate_script="scripts/cycloneiv_clean_gate.py",
                            required=False)
            results[name] = {c: r[c] for c in CATS}
        run = C.record_gate_run(conn, "cycloneiv", "scripts/cycloneiv_clean_gate.py", commit, results,
                                params={"set": args.set, "root": "corpus-rebuild/" + os.path.basename(args.root.rstrip("/")) if args.root else None,"headline_variant": HEADLINE, "baseline": args.baseline, "tag": args.tag, "scope": args.scope, "tier": args.tier or args.set,
                                        "designs": len(good), "members": sorted(results)},
                                summary={"totals": tot, "pips_variants": var,
                                         "headline": {c: round(headline(tot[c]), 4) for c in CATS}})
    log.info("recorded gate_runs id %s commit %s members %d", run, commit, len(results))


if __name__ == "__main__":
    main()
