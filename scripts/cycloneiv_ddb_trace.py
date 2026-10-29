#!/usr/bin/env python3.15t
"""Cyclone IV GX routing trace on the EXACT routing.ddb graph (#141 track 2).

Block -> output-wire map = (asm block, dest record) pairs from scripts/cycloneiv_ddb_blockmap.py:
group k of source record r <-> fan-out edge k of r (canonical order), pseudo-groups at the tail.
No tables are learnt: dest record of every fired group comes from the vendor graph; LI records
are looked up by (tile, template index), enum 282, index < 32.
Remaining non-ddb inputs (reported, not hidden): `defaults` (idle-mux source codes) and `cells`
(LE output family -> cell) from the existing phys map; LE-input muxes (not in asm) from the learner.

  python3.15t scripts/cycloneiv_ddb_trace.py export
  python3.15t scripts/cycloneiv_ddb_trace.py score --designs 'gx150_rb*' --split odd [--limit N]
Scores per pin (LCCOMB pins, ddb tracer vs existing phys tracer vs learner) and per hop by
wire class (chain from every used LI, RCF oracle).  Log tmp/logs/cycloneiv_ddb_trace.log.
"""
import argparse
import collections
import json
import logging
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_asm_decode as AD  # noqa: E402
import cycloneiv_asm_tables as AT  # noqa: E402
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_r4_coltable as CT  # noqa: E402
import cycloneiv_ddb_blockmap as BM  # noqa: E402
import cycloneiv_phys_trace as PT  # noqa: E402
import cycloneiv_route_decode as rd  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_ddb_trace")
DIE = "stingray4"
OUT = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_ddb_map.npz")
WIRE_T = ("R4", "C4", "C16", "R24")
LI_T = "LOCAL_INTERCONNECT"
XM = 115
LI_N = 38                # LOCAL_INTERCONNECT elements per LAB tile (enum 282, template index 0..37)


class Ddb:
    """Phys blocks + exact (block, dest) units + LI record lookup."""

    def __init__(self, need_map=True):
        self.P = PT.Phys(need_map=need_map)
        self.Q = BM.Pairs(self.P)
        Q, P = self.Q, self.P
        self.N = Q.N
        block = P.dec.block
        ge = Q.ge
        self.pairs = Q.pairs
        self.nunits = len(self.pairs)
        self.ublock = (self.pairs // self.N).astype(np.int32)
        self.udest = (self.pairs % self.N).astype(np.int64)
        real = ge["real"]
        # a record's mux may span several blocks (a 30-input mux = 12+12+6 inputs): the tracer
        # unit is the DEST RECORD; exactly one of its blocks fires.
        self.gdest = np.where(real, ge["dest"], -1)
        self.grec = ge["grec"]
        cnt = np.bincount(self.udest, minlength=self.N)
        self.nblk_of = cnt
        self.has_units = cnt > 0
        self.multi_block_dests = int((cnt > 1).sum())
        z = np.load(os.path.join(AD.A.TMP, f"{DIE}_rt_fanout.npz"))
        self.V, self.tpl, self.cnt, self.eoff, self.offs = (z["V"].astype(np.int64), z["tpl"], z["cnt"], z["eoff"],
                                                           z["offs"].astype(np.int64))
        self.T = AT.Tables(P.dec)
        # EXACT fitter LAB column -> vendor tile x: LE_BUFFER record = base[I] + 90 * colrank(X) + Y
        base = self.T.unnamed[("LE_BUFFER", "0")]
        self.cm = {}
        for X, rk in self.T.colrank.items():
            r = base + 90 * rk + 30
            if int(P.vy[r]) == 30 and 0 <= int(P.vx[r]) < 118 and Q.enum[r] == 45:
                self.cm[X] = int(P.vx[r])
        self.cm_cols = np.array(sorted(self.cm))
        self.x_of_vx = {v: X for X, v in self.cm.items()}
        if CT.enabled():
            log.info("R4 column table applied to the asm frames: %s", CT.apply(self))
        sel = np.flatnonzero((Q.enum == 282) & (Q.index < LI_N))
        self.li_of = {(int(P.vx[r]), int(P.vy[r]), int(Q.index[r])): int(r) for r in sel.tolist()}
        self.is_li = np.zeros(self.N, bool)
        self.is_li[sel] = True

    def fan_of(self, r):
        """Exact fan-out destination records of record r (V + template offsets)."""
        t = self.tpl[r]
        return self.V[r] + self.offs[self.eoff[t]:self.eoff[t] + self.cnt[t]]

    def vx_of(self, X):
        """Vendor tile x of fitter column X: exact for LAB columns; others follow the nearest LAB column
        to the left (offset exact to +-1 across M9K / DSP pairs)."""
        if X in self.cm:
            return self.cm[X]
        j = np.searchsorted(self.cm_cols, X) - 1
        if j < 0:
            return XM - X
        xl = int(self.cm_cols[j])
        return self.cm[xl] - (X - xl)

    def li_rec(self, x, y, i):
        """LOCAL_INTERCONNECT (RCF LAB tile x, y; index i) -> record, or -1."""
        return self.li_of.get((XM - x, y, i), -1)


class UnitView:
    """Phys-like facade whose 'blocks' are dest records: lets PhysTracer run unchanged.
    firing() records the fired block of every dest for the default-code check."""

    def __init__(self, D):
        self.D, self.P = D, D.P
        self.nblocks = D.N
        self.rec2block = np.where(D.has_units, np.arange(D.N), -1).astype(np.int32)
        self.fblock = np.zeros(D.N, np.int32)
        self.btx = self.bty = self.bkey = None

    def __getattr__(self, k):
        return getattr(self.P, k)

    def active(self, name, plane=None):
        return self.P.active(name, plane)

    def firing(self, gids):
        D = self.D
        d = D.gdest[gids]
        keep = d >= 0
        gk = gids[keep]
        self.fblock[:] = 0
        self.fblock[d[keep]] = D.P.dec.block[gk]
        P = self.P
        self.btx, self.bty, self.bkey = (np.asarray(a)[self.fblock] for a in (P.btx, P.bty, P.bkey))
        return d[keep], D.grec[gk]

    def make_tracer(self, plane, geom, learner, terminals):
        return DdbTracer(self.D, self, plane, geom, learner, None, terminals)

    def src_code(self, u, s):
        P = self.P
        b = int(self.fblock[u])
        dvx = int(P.vx[s]) - (PT.XMIRROR - int(P.btx[b]))
        dvy = int(P.vy[s]) - int(P.bty[b])
        if abs(dvx) > PT.SWIN or abs(dvy) > PT.SWIN:
            return -1
        return PT.code_off(P.fam[s], dvx, dvy, PT.SWIN)


class DdbTracer(PT.PhysTracer):
    def __init__(self, D, U, plane, geom, learner, valid, terminals):
        self.D = D
        super().__init__(U, plane, geom, learner=learner, valid=valid, terminals=terminals)

    def li_block(self, x, y, i):
        r = self.D.li_rec(x, y, i)
        return r if r >= 0 and self.D.has_units[r] else -1


def export():
    D = Ddb(need_map=False)
    meta = dict(multi_block_dests=D.multi_block_dests, provenance="ddb", die=DIE, source="asm.ddb groups x routing.ddb fan-out graph (Quartus devinfo)",
                rule="group k of source record r == fan-out edge k of r; last ng-ne groups are select-bit pseudo-groups",
                units=int(D.nunits), blocks=int(D.ublock.max()) + 1, nrec=int(D.N),
                files="unit = (asm block id from cycloneiv_asm_decode.prepare, dest record id); block ids are a function of the asm.ddb")
    np.savez_compressed(OUT, block=D.ublock, dest=D.udest.astype(np.int32), meta=np.array(json.dumps(meta)))
    log.info("exported %d units (%d blocks) -> %s (%d dest records spanning >1 block)", D.nunits,
             int(D.ublock.max()) + 1, OUT, D.multi_block_dests)


ENUM_OF = {"R4": 268, "C4": 275, "R24": 273, "C16": 281}       # RCF wire type -> element enum
WIN_OF = {"R4": (3, 1), "C4": (1, 3), "R24": (9, 1), "C16": (1, 9)}  # |dvx|, |dvy| of the dest record
#                                                                 tile vs the RCF driver tile (span + 1)


def count_unreached(children, node, P, hops, why, reason, self_too=True):
    """Scoring: a hop that cannot be resolved (ambiguous / no candidate) and every RCF hop below it is
    MISSING (CLAUDE.md 'Scoring faults'); dropping them from the denominator hid them. scoring=ambiguous_as_missing"""
    st = [(node, self_too)]
    while st:
        n, cnt = st.pop()
        if cnt:
            cls = "LI" if n[0] == LI_T and P.g.kind.get(n[3]) == "LAB" else (n[0] if n[0] in WIRE_T else None)
            if cls:
                hops[cls]["missing"] += 1
                why[cls][reason] += 1
        for c in children.get(n, ()):
            if c[0] in WIRE_T:
                st.append((c, True))
            elif c[0] == LI_T and P.g.kind.get(c[3]) == "LAB":
                hops["LI"]["missing"] += 1
                why["LI"][reason] += 1


def hop_forward(D, T, pips, fired, hops, why, amb):
    """Per-hop outcomes, alias-free: roots are exact LE_BUFFER / LOCAL_LINE records; every RCF hop
    (S -> D) with S's record known resolves D from the EXACT fan-out of S (LI: tile + index;
    wires: element class + position window, unique or reported ambiguous), then checks the plane:
    matched = fired source of D is S; missing = D's mux idle / no edge; wrong = D fired another source.
    Returns the resolved dest records of this design (for the extra count)."""
    P, Q = D.P, D.Q
    children = collections.defaultdict(list)
    sn_of = pips
    for dn, sn in pips.items():
        children[sn].append(dn)
    resolved = set()
    stack = []
    colrank = T.colrank
    for sn in list(children):
        base = T.unnamed.get((sn[0], str(sn[2]))) if sn[0] == "LE_BUFFER" else None
        if base is not None and sn[3] in colrank:
            stack.append((sn, base + 90 * colrank[sn[3]] + sn[4]))
        elif sn[0] == "LE_BUFFER":
            count_unreached(children, sn, P, hops, why, "LE_BUFFER root not resolvable", self_too=False)
    while stack:
        sn, rs = stack.pop()
        if not 0 <= rs < D.N:
            continue
        fan = None
        for dn in children.get(sn, ()):
            typ = dn[0]
            if typ == LI_T:
                if P.g.kind.get(dn[3]) != "LAB":
                    continue
                cls = "LI"
                if fan is None:
                    fan = D.fan_of(rs)
                c = fan[(Q.enum[fan] == 282) & (Q.index[fan] == dn[2]) & (P.vy[fan] == dn[4])]
                if len(c) == 0:
                    hops[cls]["missing"] += 1
                    why[cls]["source has no LI of that index/row in its exact fan-out"] += 1
                    continue
                if len(c) > 1:
                    amb[cls] += 1
                    hops[cls]["missing"] += 1
                    why[cls]["ambiguous: >1 candidate (counted missing)"] += 1
                    continue
                rd = int(c[0])
            elif typ in WIRE_T:
                cls = typ
                if fan is None:
                    fan = D.fan_of(rs)
                tx, ty = XM - dn[3], dn[4]
                dvx, dvy = WIN_OF[typ]
                if typ == "R4" and CT.enabled() and sn_of[dn][0] == "LE_BUFFER":
                    cell = CT.table().get((dn[3], sn_of[dn][3] - dn[3]))       # LB -> R4: (dx, dy 0) from the measured column table
                    if cell is None:
                        CT.NOCELL[(dn[3], sn_of[dn][3] - dn[3])] += 1
                        hops[cls]["missing"] += 1
                        why[cls]["R4 column table: no cell for (dest column, source rel) (counted missing)"] += 1
                        count_unreached(children, dn, P, hops, why, "below an unresolved hop", self_too=False)
                        continue
                    c = fan[(Q.enum[fan] == ENUM_OF[typ]) & (P.vx[fan] - D.vx_of(dn[3]) == cell[0]) & (P.vy[fan] == ty)]
                else:
                    c = fan[(Q.enum[fan] == ENUM_OF[typ]) & (np.abs(P.vx[fan] - tx) <= dvx) & (np.abs(P.vy[fan] - ty) <= dvy)]
                if len(c) == 0:
                    hops[cls]["missing"] += 1
                    why[cls]["no fan-out edge of the source in the dest window"] += 1
                    count_unreached(children, dn, P, hops, why, "below an unresolved hop", self_too=False)
                    continue
                if len(c) > 1:
                    amb[cls] += 1
                    hops[cls]["missing"] += 1
                    why[cls]["ambiguous: >1 candidate (counted missing)"] += 1
                    count_unreached(children, dn, P, hops, why, "below an unresolved hop", self_too=False)
                    continue
                rd = int(c[0])
            else:
                continue
            resolved.add(rd)
            h = hops[cls]
            if not D.has_units[rd]:
                h["missing"] += 1
                why[cls]["dest has no asm driver group"] += 1
            else:
                f = int(fired[rd])
                if f == rs:
                    h["matched"] += 1
                elif f < 0:
                    h["missing"] += 1
                    why[cls]["driver mux idle"] += 1
                else:
                    h["wrong"] += 1
                    why[cls]["fired another source"] += 1
            if typ in WIRE_T:
                stack.append((dn, rd))
    return resolved


def score(names):
    sys.path.insert(0, os.path.join(REPO, "lifters"))
    import cycloneiv_lift as lf
    D = Ddb(need_map=True)
    U = UnitView(D)
    P, geom = D.P, D.P.g
    log.info("(block, dest) units %d over %d blocks; dest records with >1 block: %d", D.nunits, P.nblocks, D.multi_block_dests)
    tables = os.path.join(REPO, "tmp", "cycloneiv", "rl_gx_m8f.json").split(",")
    learner = rd.Decoder(tables)
    lift = lf.CycloneIVLift(geom.die, tables)
    T = D.T
    tiles = [(x, y) for x in sorted(geom.kind) if geom.kind[x] == "LAB" for y in range(1, geom.ymax)]
    tidx = {t: i for i, t in enumerate(tiles)}
    res = {k: collections.defaultdict(collections.Counter) for k in ("ddb", "phys", "learner")}
    why = {k: collections.defaultdict(collections.Counter) for k in res}
    hops, hwhy = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    hamb = collections.Counter()
    unattr = collections.Counter()
    li_x = collections.Counter()
    fired_stats = collections.Counter()
    dres = {}   # per-design ddb pin results -> record_gate_run
    t0 = time.time()
    for di, name in enumerate(names):
        d = cc.load(name)
        plane = d["plane"]
        used, _m = lift.scan(plane, tiles)

        def valid(kind, x, y, n):
            i = tidx.get((x, y))
            return kind not in ("LCCOMB", "FF") or (i is not None and bool(used[i][n // 2]))
        trs = {"ddb": DdbTracer(D, U, plane, geom, learner, valid, lf.TERMINAL_WIRES),
               "phys": PT.PhysTracer(P, plane, geom, learner=learner, valid=valid, terminals=lf.TERMINAL_WIRES),
               "learner": rd.Tracer(learner, plane, geom, terminals=lf.TERMINAL_WIRES)}
        trs["learner"].valid = valid
        for key, x, y, exp in PT.expected_pins(d):
            pt = f"{key[0]}.{key[2]}"
            for which, tr in trs.items():
                got, w = tr.trace(key, x, y)
                bucket, detail = PT.score_pin(exp, got, w)
                res[which][pt][bucket] += 1
                if which == "ddb":
                    dres.setdefault(name, {}).setdefault(pt, collections.Counter())[bucket] += 1
                if bucket in ("missing", "wrong", "terminal"):
                    why[which][pt][f"{bucket}: {detail}"] += 1
        # per-hop (chain from every used LI) + LI extra
        pips, _nets = AT.oracle(name, d, geom)
        dd = trs["ddb"]
        resolved = hop_forward(D, T, pips, dd.fired, hops, hwhy, hamb)
        used_li = {(dn[3], dn[4], dn[2]) for dn in pips if dn[0] == LI_T}
        fu = np.flatnonzero(dd.fired >= 0)
        fired_stats["fired units"] += len(fu)
        fired_stats["fired multi-group units"] += dd.multi
        for u in fu.tolist():
            dest = u
            if dest in resolved:
                continue
            if D.is_li[dest]:
                r = int(dd.fired[u])
                if U.src_code(u, r) in P.defaults.get((PT.tile_class(int(U.btx[u]), int(U.bty[u]), P.xm, P.ym), int(U.bkey[u])), ()):
                    li_x["idle LI at default code (not counted)"] += 1
                else:
                    unattr["LI"] += 1
                continue
            cl = {268: "R4", 275: "C4", 273: "R24", 281: "C16"}.get(int(D.Q.enum[dest]))
            if cl:
                unattr[cl] += 1
        if di % 5 == 4:
            log.info("score: %d / %d designs (%.0fs)", di + 1, len(names), time.time() - t0)
    for which in ("ddb", "phys", "learner"):
        log.info("== %s tracer, %d designs ==", which, len(names))
        tot = collections.Counter()
        for pt in sorted(res[which]):
            c = res[which][pt]
            den = c["matched"] + c["missing"] + c["extra"] + c["wrong"]
            log.info("  %-14s matched %6d / (matched + missing %5d + extra %4d + wrong %4d) = %6.2f%%  terminal %4d",
                     pt, c["matched"], c["missing"], c["extra"], c["wrong"], 100 * c["matched"] / max(1, den), c["terminal"])
            if pt.startswith("LCCOMB"):
                tot.update({k: c[k] for k in ("matched", "missing", "extra", "wrong", "terminal")})
            for k, n in why[which][pt].most_common(6):
                log.info("      %-70s %d", k, n)
        den = tot["matched"] + tot["missing"] + tot["extra"] + tot["wrong"]
        log.info("  LCCOMB pins [%s]: matched %d / (matched %d + missing %d + extra %d + wrong %d) = %.2f%%; terminal %d",
                 which, tot["matched"], tot["matched"], tot["missing"], tot["extra"], tot["wrong"],
                 100 * tot["matched"] / max(1, den), tot["terminal"])
    log.info("== per-hop by dest wire class (forward from exact LE_BUFFER/LOCAL_LINE records over the RCF nets; dest record from the exact fan-out) ==")
    tm = collections.Counter()
    for cls in ("LI",) + WIRE_T:
        c = hops[cls]
        den = c["matched"] + c["missing"] + c["extra"] + c["wrong"]
        tm.update(c)
        log.info("  %-5s matched %7d / (matched + missing %6d + extra %6d + wrong %6d) = %7.3f%%", cls,
                 c["matched"], c["missing"], c["extra"], c["wrong"], 100 * c["matched"] / max(1, den))
        for k, n in hwhy[cls].most_common(5):
            log.info("      %-70s %d", k, n)
    den = tm["matched"] + tm["missing"] + tm["extra"] + tm["wrong"]
    log.info("  ALL   matched %d / (matched %d + missing %d + extra %d + wrong %d) = %.3f%%", tm["matched"], tm["matched"],
             tm["missing"], tm["extra"], tm["wrong"], 100 * tm["matched"] / max(1, den))
    if CT.NOCELL:
        log.info("  R4 column table: hops without a cell by (dest X, rel): total %d; by rel %s", sum(CT.NOCELL.values()),
                 dict(sorted(collections.Counter({r: sum(n for (x, rr), n in CT.NOCELL.items() if rr == r) for r in {k[1] for k in CT.NOCELL}}.items()))))
        log.info("  R4 column table NOCELL %s", json.dumps({f"{x},{r}": n for (x, r), n in CT.NOCELL.most_common()}))
    log.info("  ambiguous hops (>1 candidate in window; counted missing): %s", dict(hamb))
    log.info("  fired wire units not on any resolved path (upper bound on extra: includes pad/clock-driven nets and unreached hops): %s", dict(unattr))
    log.info("  extra detail %s; fired %s", dict(li_x), dict(fired_stats))
    return dres


def record(dres):
    """ddb tracer per-design pin results -> gate_runs (members: cycloneiv_declare_gate.py). Returns run id."""
    os.environ.setdefault("PLURIBUS_SQLITE_PATH", os.path.join(REPO, "databases", "cycloneiv", "gx150.db"))
    sys.path.insert(0, REPO)
    import db
    import schema
    from provenance import corpus as C
    from provenance import evidence_io as E
    results = {n: {pt: {k: c[k] for k in ("matched", "missing", "extra", "wrong")} for pt, c in pts.items()}
               for n, pts in dres.items()}
    schema.init()
    with db.engine().begin() as conn:
        return C.record_gate_run(conn, "cycloneiv", "scripts/cycloneiv_ddb_trace.py", E.git_head(REPO), results,
                                 params={"tracer": "ddb", "hop_override": os.environ.get("PLURIBUS_HOP_OVERRIDE", "0"),
                                         "relax_active": os.environ.get("PLURIBUS_RELAX_ACTIVE", "0"),
                                         "r4_coltable": os.environ.get("PLURIBUS_R4_COLTABLE", "0"),
                                         "scoring": "ambiguous_as_missing"})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("export", "score"))
    ap.add_argument("--designs", default="gx150_rb*")
    ap.add_argument("--split", default="odd")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-record", action="store_true", help="diagnostic run: skip record_gate_run and the exit-4 check")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_ddb_trace.log"))])
    if a.cmd == "export":
        export()
        return 0
    names = [n for n in cc.designs(a.designs) if rl.split_of(n, a.split)]
    if a.limit:
        names = names[:a.limit]
    dres = score(names)
    if a.no_record:
        return 0
    sys.path.insert(0, REPO)
    from provenance import corpus as C
    run_id = None
    try:
        run_id = record(dres)
        log.info("gate_run %s recorded", run_id)
    except SystemExit as e:
        log.error("gate NOT recorded: %s", e)
    return C.gate_exit_code(run_id, "scripts/cycloneiv_ddb_trace.py", log)


if __name__ == "__main__":
    sys.exit(main())
