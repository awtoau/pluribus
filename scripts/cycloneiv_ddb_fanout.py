#!/usr/bin/env python3.15t
"""Cyclone IV GX routing.ddb connectivity: corpus ground truth + expansion-hypothesis harness (#141).

STATUS (2026-10-28): the node -> template assignment and the template-delta semantics are STILL
OPEN - docs/cycloneiv-ddb-format.md "Open: node -> connectivity expansion" lists every tested and
rejected interpretation (this script is the harness that rejected them).  What stands:
- observe: corpus RCF wire arcs (2,984 designs, 1.6 M arcs) -> tmp/ddb/<die>_obs.npz.
- gt: exact LE_BUFFER sources (base[I] + 90*colrank(X) + Y) + subset-test machinery.  With
  position-window dest candidates (pos_cands - the true record is always included) NO expansion
  rule tested so far yields unique (record, template) matches; with learnt-alias candidates it
  yields FALSE uniques (do not reuse that path).
- solve: per-record exhaustive search under the r+cumsum rule - rejected (kept as the harness for
  the next rule candidate).

  python3.15t scripts/cycloneiv_ddb_fanout.py observe   # corpus RCF arcs -> tmp/ddb/<die>_obs.npz
  python3.15t scripts/cycloneiv_ddb_fanout.py gt        # subset-test harness (see STATUS)
  python3.15t scripts/cycloneiv_ddb_fanout.py solve     # exhaustive-search harness (see STATUS)
Log tmp/logs/cycloneiv_ddb_fanout.log; caches tmp/ddb/.
"""
import argparse
import collections
import glob
import json
import logging
import os
import pickle
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_ddb_asm as A  # noqa: E402

log = logging.getLogger("cycloneiv_ddb_fanout")
DIE = "stingray4"
TMP = A.TMP
WT = ("R4", "C4", "C16", "R24")          # wire types with records (H4/V4/H24/V16 families)
TYPI = {t: i for i, t in enumerate(("LE_BUFFER",) + WT)}
NAMES_JSON = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_asm_names.json")


def die(msg):
    log.error(msg)
    raise SystemExit(msg)


class Ddb:
    """Node table + templates + twin + icnames, all from the vendored caches."""

    def __init__(self):
        self.nodes = np.load(os.path.join(TMP, f"{DIE}_rt_nodes.npy"))
        self.vx = np.cumsum(self.nodes["dx"]).astype(np.int32)
        self.vy = np.cumsum(self.nodes["dy"]).astype(np.int32)
        self.N = len(self.vx)
        self.tw = np.load(os.path.join(TMP, f"{DIE}_rt_twin.npy"))
        z = np.load(os.path.join(TMP, f"{DIE}_rt_tpl.npz"))
        self.nd = z["nd"].astype(np.int64)
        self.doff = z["doff"].astype(np.int64)
        self.deltas = z["deltas"].astype(np.int64)
        self.ntpl = len(self.nd)
        # per-template cumulative dest deltas (leading 0 included): C[coff[t] : coff[t]+nd[t]]
        self.coff = np.cumsum(self.nd) - self.nd
        C = np.zeros(int(self.nd.sum()), np.int64)
        csd = np.cumsum(self.deltas)
        tsel = np.flatnonzero(self.nd > 1)
        reps = (self.nd[tsel] - 1).astype(np.int64)
        ar = np.arange(int(reps.sum())) - np.repeat(np.cumsum(reps) - reps, reps)
        q = np.repeat(self.doff[tsel], reps) + ar            # delta index
        p = np.repeat(self.coff[tsel] + 1, reps) + ar        # entry index
        before = csd[self.doff[tsel]] - self.deltas[self.doff[tsel]]  # cumsum before the segment
        C[p] = csd[q] - np.repeat(before, reps)
        self.C = C
        self.ctid = np.repeat(np.arange(self.ntpl, dtype=np.int32), self.nd)
        o = np.argsort(self.C, kind="stable")
        self.sC, self.stid = self.C[o], self.ctid[o]
        grec = np.load(os.path.join(TMP, f"{DIE}_dec_grec.npy"))
        self.ng = np.bincount(grec, minlength=self.N)
        self.names = pickle.load(open(os.path.join(TMP, f"{DIE}_dec_names.pkl"), "rb"))
        self.byname = {v: k for k, v in self.names.items()}
        t = json.load(open(NAMES_JSON))
        self.unnamed = {tuple(k.split("|")): v for k, v in t["unnamed"].items()}
        self.alias = {tuple(k.split("|")): [tuple(f) for f in v] for k, v in t["alias"].items()}
        g = cg.load("ep4cgx150")
        labcols = sorted(x for x, k in g.kind.items() if k == "LAB")
        self.colrank = {x: i for i, x in enumerate(reversed(labcols))}
        self.g = g

    def tpl_of_delta(self, d):
        i0 = np.searchsorted(self.sC, d)
        i1 = np.searchsorted(self.sC, d, "right")
        return self.stid[i0:i1]

    def dests(self, r, t):
        return r + self.C[self.coff[t]:self.coff[t] + self.nd[t]]

    def leb_rec(self, i, x, y):
        base = self.unnamed.get(("LE_BUFFER", str(i)))
        if base is None or x not in self.colrank:
            return -1
        return base + 90 * self.colrank[x] + y

    def fam_setup(self):
        """Family bounds (tile-lex id runs), per-family class from the name prefix, and the
        (fam, x, y) -> record index.  Class: 0 H4, 1 V4, 2 H24, 3 V16, -1 unnamed/other."""
        tile = self.vx.astype(np.int64) * 92 + self.vy
        self.fb = np.concatenate([[0], np.flatnonzero(np.diff(tile) <= 0) + 1, [self.N]])
        self.fam = np.repeat(np.arange(len(self.fb) - 1, dtype=np.int32), np.diff(self.fb))
        self.nfam = len(self.fb) - 1
        self.fcls = np.full(self.nfam, -1, np.int8)
        pref = (("H4", 0), ("V4", 1), ("H24", 2), ("V16", 3))
        for f in range(self.nfam):
            for r in range(int(self.fb[f]), min(int(self.fb[f]) + 60, int(self.fb[f + 1]))):
                nm = self.names.get(r)
                if nm:
                    for p, c in pref:
                        if nm.startswith(p):
                            self.fcls[f] = c
                            break
                    break
        self.idx3 = np.full((self.nfam, 118, 92), -1, np.int32)
        self.idx3[self.fam, self.vx, self.vy] = np.arange(self.N, dtype=np.int32)
        self.cls_fams = {c: np.flatnonzero(self.fcls == c) for c in range(4)}

    # driver sits within +-span of the record tile along the wire axis (record tile = span centre;
    # measured from resolved corpus wires).  H4/V4 span 2; H24/V16 (16-LAB lines) span 8.
    CLS_SPAN = {0: (2, 0), 1: (0, 2), 2: (8, 0), 3: (0, 8)}

    def pos_cands(self, typ, X, Y):
        """ALL records of the RCF type's wire class whose tile is within the span window of the
        driver tile (XMIRROR - X, Y).  Position-based and I-agnostic: the true record is always
        included (unlike the learnt alias forms, whose gaps let a wrong template win — that bug
        produced templates with far scattered dests)."""
        c = {"R4": 0, "C4": 1, "C16": 2, "R24": 3}[typ]
        sx, sy = self.CLS_SPAN[c]
        tx, ty = XMIRROR - X, Y
        xs = np.arange(max(tx - sx - 1, 0), min(tx + sx + 2, 118))
        ys = np.arange(max(ty - sy - 1, 0), min(ty + sy + 2, 92))
        sub = self.idx3[np.ix_(self.cls_fams[c], xs, ys)].ravel()
        return sub[sub >= 0].astype(np.int64)


def observe():
    """All corpus RCF arcs with a wire-record source or dest -> <die>_obs.npz:
    one row per arc (design, styp, si, sx, sy, dtyp, di, dx, dy); types TYPI (LE_BUFFER=0)."""
    rcfs = sorted(glob.glob(os.path.join(REPO, "corpus", "cycloneiv", "*", "routing.rcf")))
    rows, designs = [], []
    t0 = time.time()
    for pi, p in enumerate(rcfs):
        name = os.path.basename(os.path.dirname(p))
        try:
            nets = cc.parse_rcf(p)
        except (ValueError, OSError) as e:
            log.warning("%s: %s", name, e)
            continue
        designs.append(name)
        di = len(designs) - 1
        for _net, edges in nets.items():
            for s, d in edges:
                if (s[0] == "W" and (s[1] in WT or s[1] == "LE_BUFFER")
                        and d[0] == "W" and d[1] in WT):
                    rows.append((di, TYPI[s[1]], s[5], s[2], s[3], TYPI[d[1]], d[5], d[2], d[3]))
        if pi % 500 == 499:
            log.info("observe: %d / %d rcfs, %d arcs (%.0fs)", pi + 1, len(rcfs), len(rows), time.time() - t0)
    arr = np.array(rows, np.int32)
    out = os.path.join(TMP, f"{DIE}_obs.npz")
    np.savez(out, arcs=arr, designs=np.array(designs))
    log.info("observe: %d designs, %d wire arcs -> %s", len(designs), len(arr), out)


XMIRROR = 115        # vendor x = XMIRROR - fitter x (docs/cycloneiv-ddb-format.md)
DWIN = 2             # a dest record's node tile is within +-DWIN of the RCF driver tile


def gt():
    """Iterative exact resolution + template ground truth.
    State: wire (typ, i, x, y) -> record id (exact); record -> template (exact).
    Seed: LE_BUFFER arithmetic (record = base[I] + 90*colrank(X) + Y).  Each pass:
      1. subset test: for a resolved src record, intersect the template sets containing each
         resolved observed dest delta; filter nd == asm group count; unique -> assigned;
      2. dest resolution: an assigned src's template dests near the RCF driver tile
         (vendor (XMIRROR - X, Y) +- DWIN) in the dest's family: unique -> that wire resolved.
         Consistent per-(typ, I) (famkey, dvx, dvy) rules then resolve every wire of that (typ, I).
    -> <die>_gt.pkl {"wire": {(typ,i,x,y): rec}, "tpl": {rec: template}, "rules": {...}}"""
    db = Ddb()
    db.fam_setup()
    fam = db.fam
    ngr, goff, gtx, gty = group_tiles(db.N)
    z = np.load(os.path.join(TMP, f"{DIE}_obs.npz"), allow_pickle=True)
    arcs = z["arcs"]
    log.info("gt: %d arcs, %d designs", len(arcs), len(z["designs"]))
    by_src = collections.defaultdict(set)      # src wire key -> dest wire keys (designs pooled: the
    #                                            union of subsets of the fan-out is still a subset)
    for a in arcs.tolist():
        by_src[tuple(a[1:5])].add(tuple(a[5:9]))
    wire = {}
    for k in by_src:
        if k[0] == 0:
            r = db.leb_rec(k[1], k[2], k[3])
            if r >= 0:
                wire[k] = r
    # dest wire keys too (a dest is a wire even when never a source)
    all_dk = set()
    for dks in by_src.values():
        all_dk |= dks
    log.info("gt: %d src wires (%d LE_BUFFER seeds), %d dest wires", len(by_src), len(wire), len(all_dk))
    tplof = {}
    rules = collections.defaultdict(collections.Counter)   # (typ, i) -> Counter[(fam, dvx, dvy)]
    bad = collections.Counter()
    acands = {}                                            # dest key -> alias candidate records
    ngmask = {}                                            # ng -> bool mask over template ids (nd == ng)
    for pas in range(1, 40):
        new_tpl = new_wire = 0
        t0 = time.time()
        for sk, r in list(wire.items()):
            if r in tplof or not by_src.get(sk):
                continue
            k = int(db.ng[r])
            km = ngmask.get(k)
            if km is None:
                km = ngmask[k] = db.nd == k
            groups = []                       # per dest: candidate record array
            for dk in by_src[sk]:
                rec = wire.get(dk)
                if rec is not None:
                    groups.append(np.array([rec], np.int64))
                    continue
                cs = acands.get(dk)
                if cs is None:
                    cs = acands[dk] = db.pos_cands(
                        ("", "R4", "C4", "C16", "R24")[dk[0]], dk[2], dk[3])
                if len(cs):
                    groups.append(cs)
            if not groups:
                continue
            D = np.concatenate(groups) - r
            i0 = np.searchsorted(db.sC, D)
            i1 = np.searchsorted(db.sC, D, "right")
            cand, p = None, 0
            for g in groups:
                ln = len(g)
                parts = []
                for a, b in zip(i0[p:p + ln], i1[p:p + ln]):
                    if b > a:
                        s = db.stid[a:b]
                        s = s[km[s]]          # only templates with nd == ng(r)
                        if len(s):
                            parts.append(s)
                p += ln
                if not parts:
                    cand = np.zeros(0, np.int32)
                    break
                u = np.unique(np.concatenate(parts)) if len(parts) > 1 else np.unique(parts[0])
                cand = u if cand is None else np.intersect1d(cand, u, assume_unique=True)
                if len(cand) == 0:
                    break
            if cand is None:
                continue
            if len(cand) == 0:
                bad["no template covers dest candidates"] += 1
                continue
            if len(cand) >= 1:
                # locality: every dest must sit within its class window of SOME asm group of r
                # (kills templates whose far scattered dests only happen to cover the candidates)
                gx = gtx[goff[r]:goff[r] + k].astype(np.int64)
                gy = gty[goff[r]:goff[r] + k].astype(np.int64)
                keep = []
                for t in cand.tolist():
                    ds = db.dests(r, t)
                    if ds.min() < 0 or ds.max() >= db.N:
                        continue
                    dcls = db.fcls[fam[ds]]
                    wx = np.where((dcls == 2), 9, np.where(dcls == 3, 2, 4))
                    wy = np.where((dcls == 3), 9, np.where(dcls == 2, 2, 4))
                    dx = np.abs(db.vx[ds][:, None] - gx[None, :]).min(axis=1)
                    dy = np.abs(db.vy[ds][:, None] - gy[None, :]).min(axis=1)
                    if np.all((dx <= wx) & (dy <= wy)):
                        keep.append(t)
                cand = np.array(keep, cand.dtype)
            if len(cand) == 1:
                tplof[r] = int(cand[0])
                new_tpl += 1
        log.info("gt pass %d: subset phase %.0fs", pas, time.time() - t0)
        famty = {1: "H4", 2: "V4", 3: "H24", 4: "V16"}
        for sk, r in list(wire.items()):
            t = tplof.get(r)
            if t is None:
                continue
            ds = db.dests(r, t)
            ok = (ds >= 0) & (ds < db.N)
            for dk in by_src.get(sk, ()):
                if dk in wire:
                    continue
                ty, _i, X, Y = dk
                tx, ty_ = XMIRROR - X, Y
                pre = famty[ty]
                hits = [int(d) for d in ds[ok]
                        if abs(int(db.vx[d]) - tx) <= DWIN and abs(int(db.vy[d]) - ty_) <= DWIN
                        and str(db.names.get(int(d), "")).startswith(pre)]
                if len(set(hits)) == 1:
                    wire[dk] = hits[0]
                    rules[(dk[0], dk[1])][(int(fam[hits[0]]), int(db.vx[hits[0]]) - tx, int(db.vy[hits[0]]) - ty_)] += 1
                    new_wire += 1
        # NOTE: no per-(typ, I) arithmetic rules.  A wire's record-tile offset from its RCF driver
        # tile is NOT constant per (typ, I): wires are driven at varying span positions and the two
        # end records (twins) live in different families.  Tried and reverted: 47 of the learnt
        # rules were inconsistent and mass-applied ones produced 442 template violations.
        log.info("gt pass %d: +%d templates (%d), +%d wires by dest match (%d wires)",
                 pas, new_tpl, len(tplof), new_wire, len(wire))
        if not new_tpl and not new_wire:
            break
    # verify: every resolved dest of an assigned record must be a template dest
    v_ok = v_bad = 0
    wire_by_rec = {}
    for sk, r in wire.items():
        wire_by_rec.setdefault(sk, r)
    for sk, r in wire.items():
        t = tplof.get(r)
        if t is None:
            continue
        ds = set(db.dests(r, t).tolist())
        for dk in by_src.get(sk, ()):
            rec = wire.get(dk)
            if rec is None:
                continue
            if rec in ds:
                v_ok += 1
            else:
                v_bad += 1
    log.info("gt verify: resolved dest in assigned template %d ok / %d violations", v_ok, v_bad)
    multi_rule = {k: c.most_common() for k, c in rules.items() if len(c) > 1}
    log.info("gt: inconsistent rules %d: %s", len(multi_rule), dict(list(multi_rule.items())[:6]))
    log.info("gt: drops %s", dict(bad))
    out = os.path.join(TMP, f"{DIE}_gt.pkl")
    pickle.dump({"wire": wire, "tpl": tplof,
                 "rules": {f"{k[0]}|{k[1]}": c.most_common() for k, c in rules.items()}}, open(out, "wb"))
    log.info("gt: %d wires resolved, %d records assigned -> %s", len(wire), len(tplof), out)


def group_tiles(N):
    """Per-record asm group tiles (vendor coords, LAB-snapped select-bit tile):
    -> (ngr, goff, gtx, gty) with groups of record r at [goff[r], goff[r]+ngr[r])."""
    D = os.path.join(TMP, f"{DIE}_dec")
    gstart = np.load(f"{D}_gstart.npy")
    grec = np.load(f"{D}_grec.npy")
    pf = np.load(f"{D}_pf.npy", mmap_mode="r")
    pv = np.load(f"{D}_pv.npy", mmap_mode="r")
    g = cg.load("ep4cgx150")
    labcols = np.array(sorted(x for x in g.kind if g.kind[x] == "LAB"))
    labfx = np.array([g.FX[x] for x in labcols])
    f0 = np.asarray(pf)[gstart].astype(np.int64)
    v0 = np.asarray(pv)[gstart].astype(np.int64)
    ci = np.argmin(np.abs(f0[:, None] - labfx[None, :]), axis=1)
    gtx = (XMIRROR - labcols[ci]).astype(np.int32)
    gty = np.clip((v0 - g.vy0 + g.vpitch // 2) // g.vpitch, 0, g.ymax).astype(np.int32)
    order = np.argsort(grec, kind="stable")
    ngr = np.bincount(grec, minlength=N)
    goff = np.concatenate([[0], np.cumsum(ngr)[:-1]])
    return ngr, goff, gtx[order], gty[order]


# dest-record tile vs driver/mux tile: the record tile is the span CENTRE, the driver sits within
# +-2 tiles along the wire axis (measured from 112k resolved corpus wires, tmp/allowed.txt).
# FUZZ covers the select-bit tile vs driver tile snap (non-LAB columns snap to the nearest LAB).
SPAN = 2
FUZZ = 1


def solve(args):
    """Assignment by exhaustive template search per record (brute force first, docs/recovery-process.md):
    candidates = templates with nd == asm group count whose dests are valid records and whose dest
    tiles admit a perfect matching with the record's asm group tiles under the span/fuzz windows.
    A record is DECODED when all surviving candidates give the same dest id multiset; else ambiguous.
    -> <die>_rt_asg.npy (int32 template id, -1 = ambiguous/none) + <die>_rt_asg_stats.json"""
    import threading
    db = Ddb()
    N = db.N
    ngr, goff, gtx, gty = group_tiles(N)
    tile = db.vx.astype(np.int64) * 92 + db.vy
    fb = np.concatenate([[0], np.flatnonzero(np.diff(tile) <= 0) + 1, [N]])
    fam = np.repeat(np.arange(len(fb) - 1, dtype=np.int32), np.diff(fb))
    # family axis: 0 = horizontal wire (driver within +-SPAN in x), 1 = vertical, 2 = point (same tile)
    fax = np.full(len(fb) - 1, 2, np.int8)
    for f in range(len(fb) - 1):
        for r in range(int(fb[f]), min(int(fb[f]) + 50, int(fb[f + 1]))):
            nm = db.names.get(r)
            if nm:
                fax[f] = 0 if nm.startswith(("H4", "H24")) else 1 if nm.startswith(("V4", "V16")) else 2
                break
    vx, vy = db.vx.astype(np.int32), db.vy.astype(np.int32)
    nd, coff, C = db.nd, db.coff, db.C
    by_k = {}
    for k in np.unique(nd).tolist():
        ts = np.flatnonzero(nd == k)
        if k >= 1:
            by_k[int(k)] = (ts, C[(coff[ts][:, None] + np.arange(k)[None, :])])  # (nt, k) cum deltas
    asg = np.full(N, -1, np.int32)
    stats = collections.Counter()
    lock = threading.Lock()

    def match_ok(gxs, gys, dts, dfam):
        """Perfect matching groups x dests under axis windows (greedy + augment, k <= ~25)."""
        k = len(gxs)
        adj = []
        for j in range(k):
            dx = gxs - dts[j][0]
            dy = gys - dts[j][1]
            a = fax[dfam[j]]
            if a == 0:
                ok = (np.abs(dx) <= SPAN + FUZZ) & (np.abs(dy) <= FUZZ)
            elif a == 1:
                ok = (np.abs(dx) <= FUZZ) & (np.abs(dy) <= SPAN + FUZZ)
            else:
                ok = (np.abs(dx) <= FUZZ + 1) & (np.abs(dy) <= FUZZ + 1)
            adj.append(np.flatnonzero(ok).tolist())
        m = [-1] * k      # group -> dest
        md = [-1] * k     # dest -> group

        def aug(j, seen):
            for g_ in adj[j]:
                if g_ in seen:
                    continue
                seen.add(g_)
                if m[g_] < 0 or aug(m[g_], seen):
                    m[g_] = j
                    md[j] = g_
                    return True
            return False

        for j in range(k):
            if not aug(j, set()):
                return False
        return True

    def work(lo, hi):
        local = collections.Counter()
        out = {}
        for r in range(lo, hi):
            k = int(ngr[r])
            e = by_k.get(k)
            if e is None or k == 0:
                local["no size"] += 1
                continue
            ts, Ck = e
            ds = r + Ck                                   # (nt, k) dest ids
            valid = np.all((ds >= 0) & (ds < N), axis=1)
            if not valid.any():
                local["no valid"] += 1
                continue
            tsv, dsv = ts[valid], ds[valid]
            gx = gtx[goff[r]:goff[r] + k].astype(np.int64)
            gy = gty[goff[r]:goff[r] + k].astype(np.int64)
            # quick necessary filter: every dest inside the groups' bounding box (+ window)
            dtx, dty = vx[dsv], vy[dsv]
            w = SPAN + FUZZ + 1
            okd = ((dtx >= gx.min() - w) & (dtx <= gx.max() + w)
                   & (dty >= gy.min() - w) & (dty <= gy.max() + w)).all(axis=1)
            tsv, dsv = tsv[okd], dsv[okd]
            win = []
            for t, drow in zip(tsv.tolist(), dsv):
                dts = list(zip(vx[drow].tolist(), vy[drow].tolist()))
                if match_ok(gx, gy, dts, fam[drow]):
                    win.append((t, tuple(sorted(drow.tolist()))))
                    if len(win) > 8:
                        break
            if not win:
                local["none"] += 1
            elif len({w_[1] for w_ in win}) == 1:
                out[r] = win[0][0]
                local["decoded"] += 1
                local["decoded ambiguous-template"] += len(win) > 1
            else:
                local["ambiguous"] += 1
        with lock:
            stats.update(local)
            for r, t in out.items():
                asg[r] = t

    lo, hi = args.lo, args.hi if args.hi else N
    ranges = np.linspace(lo, hi, args.workers + 1).astype(int)
    threads = [threading.Thread(target=work, args=(int(a), int(b))) for a, b in zip(ranges, ranges[1:])]
    t0 = time.time()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    log.info("solve [%d..%d): %s (%.0fs)", lo, hi, dict(stats), time.time() - t0)
    out = os.path.join(TMP, f"{DIE}_rt_asg.npy")
    np.save(out, asg)
    json.dump(dict(stats), open(os.path.join(TMP, f"{DIE}_rt_asg_stats.json"), "w"))
    # cross-check against corpus ground truth
    p = os.path.join(TMP, f"{DIE}_gt.pkl")
    if os.path.exists(p):
        gtd = pickle.load(open(p, "rb"))["tpl"]
        both = [(r, t) for r, t in gtd.items() if lo <= r < hi and asg[r] >= 0]
        agree = sum(1 for r, t in both if asg[r] == t
                    or tuple(sorted((r + db.C[db.coff[asg[r]]:db.coff[asg[r]] + db.nd[asg[r]]]).tolist()))
                    == tuple(sorted((r + db.C[db.coff[t]:db.coff[t] + db.nd[t]]).tolist())))
        log.info("solve vs corpus gt: %d / %d same dest set", agree, len(both))
    log.info("solve: wrote %s", out)


def check():
    """Gate for the EXACT routing.ddb fan-out decode (<die>_rt_fanout.npz, from
    cycloneiv_ddb_routing.py fanout): every corpus RCF arc whose source is an exact
    LE_BUFFER record must have its destination wire inside the decoded fan-out.

    Per arc: dest candidates = pos_cands (position window, I-agnostic; always contains
    the true record) intersected with decoded dests(src) = V - 1 + template offsets.
    Headline: matched / (matched + missing); plus die-wide template-edge-count vs
    asm-group-count cross-check."""
    db = Ddb()
    db.fam_setup()
    z = np.load(os.path.join(TMP, f"{DIE}_rt_fanout.npz"))
    V, tpl, cnt, eoff, offs = z["V"], z["tpl"], z["cnt"], z["eoff"], z["offs"]
    obs = np.load(os.path.join(TMP, f"{DIE}_obs.npz"), allow_pickle=True)
    arcs = obs["arcs"]
    sel = arcs[arcs[:, 1] == TYPI["LE_BUFFER"]]
    by_src = collections.defaultdict(set)
    for a in sel.tolist():
        by_src[tuple(a[1:5])].add(tuple(a[5:9]))
    matched = missing = 0
    nosrc = 0
    miss_by_type = collections.Counter()
    match_by_type = collections.Counter()
    acands = {}
    miss_sample = []
    for sk, dks in by_src.items():
        r = db.leb_rec(sk[1], sk[2], sk[3])
        if r < 0:
            nosrc += len(dks)
            continue
        t = int(tpl[r])
        D = int(V[r]) + offs[eoff[t]:eoff[t] + cnt[t]].astype(np.int64)
        Ds = set(D.tolist())
        for dk in dks:
            cs = acands.get(dk)
            if cs is None:
                cs = acands[dk] = set(db.pos_cands(("", "R4", "C4", "C16", "R24")[dk[0]],
                                                   dk[2], dk[3]).tolist())
            if cs & Ds:
                matched += 1
                match_by_type[dk[0]] += 1
            else:
                missing += 1
                miss_by_type[dk[0]] += 1
                if len(miss_sample) < 12:
                    miss_sample.append((sk, r, dk, sorted(Ds)[:8]))
    tot = matched + missing
    log.info("check: LE_BUFFER-rooted arcs: matched %d / missing %d / total %d (%.4f%%); "
             "%d arcs skipped (no exact src record); by dest type matched %s missing %s",
             matched, missing, tot, 100.0 * matched / max(tot, 1), nosrc,
             dict(match_by_type), dict(miss_by_type))
    for m in miss_sample:
        log.info("check MISS: src %s rec %d dest %s decoded-dests %s", *m)
    # die-wide: template edge count vs asm group count
    ecnt = cnt[tpl].astype(np.int64)
    ng = db.ng.astype(np.int64)
    both = (ng > 0)
    eq = int((ecnt[both] == ng[both]).sum())
    log.info("check: asm cross-check over %d records with fired-capable groups: "
             "template edges == asm groups for %d (%.2f%%); diff hist %s",
             int(both.sum()), eq, 100.0 * eq / max(int(both.sum()), 1),
             collections.Counter((ecnt[both] - ng[both]).tolist()).most_common(6))
    if tot and missing == 0:
        log.info("check: GATE PASS - every exact-source corpus arc is in the decoded fan-out")
    return missing == 0 and tot > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("observe", "gt", "solve", "check"))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--lo", type=int, default=0)
    ap.add_argument("--hi", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_ddb_fanout.log"))])
    if a.cmd == "observe":
        observe()
    elif a.cmd == "gt":
        gt()
    elif a.cmd == "check":
        check()
    else:
        solve(a)


if __name__ == "__main__":
    main()
