#!/usr/bin/env python3.15t
"""Cyclone IV GX physical routing tracer on asm.ddb record ids (issue #138).

Identity: asm record = wire (routing.ddb node table: tile + id-run family); block = mux (groups sharing
second-level bits, cycloneiv_asm_decode); a design fires one group per block (Dec.active).
What asm.ddb covers (measured, docs/cycloneiv-bitstream.md): the 17 routing frames of a LAB column only,
i.e. the R4 / C4 / C16 / R24 / LI driver muxes.  Not in asm: the LE-input muxes (frames -17..-1 of the
column; the learner decodes them, LI / LOCAL_LINE names are LAB-local and alias-free) and LI fan-out
(LI records have no groups).  An unused driver mux is programmed to a DEFAULT input in every active LAB.
Tables learnt from the corpus, tile-relative (tile class = X mod 8, Y mod 4), never by wire name:
  defaults (class, block rel key) -> source codes that fire in >= DEFAULT_FRAC of the block's firings
  wires    (class, block rel key) -> (family, dvx, dvy): the record the block drives.  Exact test:
           record used in a design  <=>  block fired on a non-default source (positive intersection over
           firings, negative count over records used without the block firing)
  lis      (class, block rel key) -> (dy, i): LI driver muxes; same test on RCF LOCAL_INTERCONNECT indices
  cells    family -> (M, dy, LE): LE_BUFFER records of an LE, X = M - vx (vote)
verify: every tile's firings against its class entry; disagreements reported, never averaged.
Trace: LE pin -> learner LE-input decode (LI i | LOCAL_LINE | CONST | CIN) -> LI driver block (lis) ->
fired source record (default = unused LI, dropped) -> block driving it (wires) -> ... -> LE_BUFFER (-> LE,
comb / reg from the learner's select bit) or a terminal record (by family).  FF pins stay on the learner.

  python3.15t scripts/cycloneiv_phys_trace.py blocks                    # per-block tile / key tables
  python3.15t scripts/cycloneiv_phys_trace.py learn  [--designs 'gx150_*'] [--split even]
  python3.15t scripts/cycloneiv_phys_trace.py verify [--designs 'gx150_*'] [--split all]
  python3.15t scripts/cycloneiv_phys_trace.py score  [--designs 'gx150_*'] [--split odd] [--tables ...]
Output lifters/data/cycloneiv_ep4cgx150_phys_map.json; log tmp/logs/cycloneiv_phys_trace.log.
Needs tmp/ddb/stingray4_dec_*.npy (cycloneiv_asm_decode.py prepare) and stingray4_rt_nodes.npy
(cycloneiv_ddb_routing.py nodes); peak RSS ~3 GB (the prepared arrays mmap).  Fired-group sets are cached
per design in tmp/cycloneiv/phys/active/.
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
import cycloneiv_asm_decode as D  # noqa: E402
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_route_decode as rd  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

log = logging.getLogger("cycloneiv_phys_trace")
DIE = "stingray4"
OUT = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_phys_map.json")
LI_MAP = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_li_map.json")
WORK = os.path.join(REPO, "tmp", "cycloneiv", "phys")
NODES = os.path.join(D.A.TMP, f"{DIE}_rt_nodes.npy")
XMIRROR = 115            # vendor x = XMIRROR - plane x (docs/cycloneiv-ddb-format.md); offsets absorb any error
GX, GY = 118, 92         # vendor grid
NV = 6368                # plane linear address = frame * NV + v (cycloneiv_asm_decode.prepare)
WIN = 1                  # a wire record's node tile is within +-WIN tiles of its driver block (R4: 0, C4: dy)
SWIN = 3                 # source-code offset range (default detection)
MIN_N = 3                # non-default firings before an intersection counts
DEFAULT_FRAC = 0.5       # a source firing in >= this fraction of a block's firings (n >= DEFAULT_MIN) is a default
DEFAULT_MIN = 60
NEG_RATE = 0.02          # record / LI used without the block firing, as a fraction of its uses: 0 expected
PORTS = ("DATAA", "DATAB", "DATAC", "DATAD", "CLK", "ENA", "CLRN", "SCLR", "SLOAD", "ASDATA", "ALOAD", "PRN", "DATAIN")
PORT_ID = {p: i for i, p in enumerate(PORTS)}
MAX_HOPS = 40
LI_MAX = 64


def tile_class(x, y, xm, ym):
    return (x % xm) * ym + (y % ym) if xm else (y % ym)


def code_off(fam, dvx, dvy, w):
    return (int(fam) * (2 * w + 1) + (dvx + w)) * (2 * w + 1) + (dvy + w)


def decode_off(c, w):
    s = 2 * w + 1
    return c // (s * s), (c // s) % s - w, c % s - w


class Phys:
    """asm decoder + node table + per-block tile tables (+ the learnt map when present)."""

    def __init__(self, map_path=OUT, need_map=True):
        self.dec = D.Dec()
        self.g = self.dec.g
        rec = np.load(NODES)
        self.vx = np.cumsum(rec["dx"]).astype(np.int32)
        self.vy = np.cumsum(rec["dy"]).astype(np.int32)
        self.nrec = len(self.vx)
        tile = self.vx.astype(np.int64) * GY + self.vy
        restarts = np.flatnonzero(np.diff(tile) <= 0) + 1
        self.fbounds = np.concatenate([[0], restarts, [self.nrec]])
        self.fam = np.repeat(np.arange(len(self.fbounds) - 1, dtype=np.int32), np.diff(self.fbounds))
        self.nfam = len(self.fbounds) - 1
        self.idx3 = np.full((self.nfam, GX, GY), -1, np.int32)
        self.idx3[self.fam, self.vx, self.vy] = np.arange(self.nrec, dtype=np.int32)
        self.load_blocks()
        self.map = None
        if need_map and os.path.exists(map_path):
            self.load_map(map_path)

    # -- blocks -------------------------------------------------------------------------
    def load_blocks(self):
        path = os.path.join(WORK, f"{DIE}_blocks.npz")
        if not os.path.exists(path):
            self.build_blocks(path)
        z = np.load(path, allow_pickle=True)
        self.btx, self.bty, self.bkey = z["btx"], z["bty"], z["bkey"]
        self.keys = list(z["keys"])
        self.nblocks = len(self.btx)
        self.key_id = {k: i for i, k in enumerate(self.keys)}
        packed = (self.btx.astype(np.int64) * GY + self.bty) * len(self.keys) + self.bkey
        self.border = np.argsort(packed, kind="stable")
        self.bsorted = packed[self.border]

    def block_at(self, tx, ty, key_id):
        if not (0 <= tx < GX and 0 <= ty < GY):
            return -1
        p = (tx * GY + ty) * len(self.keys) + key_id
        i = np.searchsorted(self.bsorted, p)
        if i < len(self.bsorted) and self.bsorted[i] == p:
            return int(self.border[i])
        return -1

    def build_blocks(self, path):
        """One representative group per block -> its non-select bit positions -> tile (nearest LAB column
        by frame, row by v) and the positions relative to that tile's anchor."""
        dec, g = self.dec, self.g
        t0 = time.time()
        block = dec.block
        nb = int(block.max()) + 1
        nonempty = np.flatnonzero(dec.gsize > 0)
        u, ri = np.unique(block[nonempty], return_index=True)   # representative non-empty group per block
        rep = np.full(nb, -1, np.int64)
        rep[u] = nonempty[ri]
        empty_blocks = int((rep < 0).sum())                     # blocks of empty groups only: no bits, no tile
        rep[rep < 0] = nonempty[0]
        gs, gz = dec.gstart[rep], dec.gsize[rep]
        gz = gz.astype(np.int64)
        total = int(gz.sum())
        starts = np.concatenate([[0], np.cumsum(gz)[:-1]])
        egrp = np.repeat(np.arange(nb), gz)
        ent = np.repeat(gs.astype(np.int64), gz) + (np.arange(total) - np.repeat(starts, gz))
        b0 = np.asarray(dec.b0)[ent]
        pf = np.asarray(dec.pf)[ent].astype(np.int64)
        pv = np.asarray(dec.pv)[ent].astype(np.int64)
        lin = pf * NV + pv
        isA = b0 != 1
        hasA = np.zeros(nb, bool)
        hasA[egrp[isA]] = True
        use = isA | ~hasA[egrp]           # no non-select entry: key on the select bit (prepare() does the same)
        order = np.lexsort((lin[use], egrp[use]))
        eg, el = egrp[use][order], lin[use][order]
        first = np.concatenate([[True], eg[1:] != eg[:-1]])
        k0 = np.full(nb, -1, np.int64)
        k1 = np.full(nb, -1, np.int64)
        k0[eg[first]] = el[first]
        i1 = np.flatnonzero(first) + 1
        ok = i1 < len(eg)
        ok[ok] &= eg[i1[ok]] == eg[i1[ok] - 1]
        k1[eg[i1[ok]]] = el[i1[ok]]
        if (k0 < 0).any():
            raise SystemExit("block without a key position")
        f0, v0 = k0 // NV, k0 % NV
        labcols = np.array(sorted(x for x in g.kind if g.kind[x] == "LAB"))
        labfx = np.array([g.FX[x] for x in labcols])
        ci = np.argmin(np.abs(f0[:, None] - labfx[None, :]), axis=1)
        tx = labcols[ci]
        ty = np.clip((v0 - g.vy0 + g.vpitch // 2) // g.vpitch, 0, g.ymax)
        ax, ay = labfx[ci], g.vy0 + g.vpitch * ty
        r0f, r0v = f0 - ax, v0 - ay
        has1 = k1 >= 0
        r1f = np.where(has1, k1 // NV - ax, 9999)
        r1v = np.where(has1, k1 % NV - ay, 9999)
        rel = np.stack([r0f, r0v, r1f, r1v], axis=1)
        uniq, inv = np.unique(rel, axis=0, return_inverse=True)
        keys = np.array([f"{a},{b}" + (f"|{c},{d}" if c != 9999 else "") for a, b, c, d in uniq.tolist()])
        os.makedirs(WORK, exist_ok=True)
        np.savez(path, btx=tx.astype(np.int16), bty=ty.astype(np.int16), bkey=inv.astype(np.int32).reshape(-1), keys=keys)
        log.info("blocks: %d (%d of empty groups only, keyed on a stand-in), %d distinct rel keys, %.0fs -> %s", nb,
                 empty_blocks, len(keys), time.time() - t0, path)

    # -- per-design firing ---------------------------------------------------------------
    def active(self, name, plane=None):
        """Fired group ids of a design (select-only groups dropped), cached per design name."""
        os.makedirs(os.path.join(WORK, "active"), exist_ok=True)
        path = os.path.join(WORK, "active", f"{name}.npy") if name else None
        if path and os.path.exists(path):
            return np.load(path)
        if plane is None:
            plane = cc.load_plane_only(name)
        gids, _recs, _blocks = self.dec.active(plane)
        keep = np.asarray(self.dec.npred[gids] < self.dec.gsize[gids])
        gids = gids[keep]
        if path:
            np.save(path, gids)
        return gids

    def firing(self, gids):
        """-> (blocks, source records) of fired groups."""
        return self.dec.block[gids], self.dec.grec[gids]

    def src_code(self, b, s):
        """Source record s of block b as a tile-relative code (family, dvx, dvy), or -1 when far away."""
        dvx = int(self.vx[s]) - (XMIRROR - int(self.btx[b]))
        dvy = int(self.vy[s]) - int(self.bty[b])
        if abs(dvx) > SWIN or abs(dvy) > SWIN:
            return -1
        return code_off(self.fam[s], dvx, dvy, SWIN)

    # -- learnt map ------------------------------------------------------------------------
    def load_map(self, path):
        m = json.load(open(path))
        self.map = m
        self.xm, self.ym = m["class"]["x_mod"], m["class"]["y_mod"]
        if m["families"] != self.fbounds.tolist():
            raise SystemExit("node-table families differ from the map's: regenerate the map")

        def key_of(k):
            cls, key = k.split("|", 1)
            kid = self.key_id.get(key)
            return (int(cls), kid) if kid is not None else None
        self.wires = {key_of(k): tuple(v) for k, v in m["wires"].items() if key_of(k)}
        self.lis = {key_of(k): tuple(v) for k, v in m["lis"].items() if key_of(k)}
        # supplement lis from li_map.json when available (issue #139)
        if os.path.exists(LI_MAP):
            lm = json.load(open(LI_MAP))
            n_new = 0
            for k, v in lm["lis"].items():
                kk = key_of(k)
                if kk is not None and kk not in self.lis:
                    self.lis[kk] = tuple(v)
                    n_new += 1
            log.info("li_map: %d new entries from %s (%d total lis)", n_new, LI_MAP, len(self.lis))
        self.li_inv = {(c, v[1]): (kid, v[0]) for (c, kid), v in self.lis.items()}
        self.defaults = {key_of(k): {code_off(*d, SWIN) for d in v} for k, v in m["defaults"].items() if key_of(k)}
        self.cells = {int(f): tuple(v) for f, v in m["cells"].items()}
        self.rec2block = self.build_rec2block()

    def build_rec2block(self):
        """record -> block driving it, from the wires map applied to every block."""
        r2b = np.full(self.nrec, -1, np.int32)
        cls = tile_class(self.btx.astype(np.int64), self.bty.astype(np.int64), self.xm, self.ym)
        nk = len(self.keys)
        packed = cls * nk + self.bkey
        uniq, inv = np.unique(packed, return_inverse=True)
        fam = np.full(len(uniq), -1, np.int32)
        dvx = np.zeros(len(uniq), np.int32)
        dvy = np.zeros(len(uniq), np.int32)
        for i, p in enumerate(uniq.tolist()):
            v = self.wires.get((p // nk, p % nk))
            if v is not None:
                fam[i], dvx[i], dvy[i] = v
        f, ddx, ddy = fam[inv], dvx[inv], dvy[inv]
        vxb = XMIRROR - self.btx.astype(np.int32) + ddx
        vyb = self.bty.astype(np.int32) + ddy
        ok = (f >= 0) & (vxb >= 0) & (vxb < GX) & (vyb >= 0) & (vyb < GY)
        recs = self.idx3[f[ok], vxb[ok], vyb[ok]]
        bl = np.flatnonzero(ok)
        good = recs >= 0
        dup = np.bincount(recs[good], minlength=self.nrec) > 1
        r2b[recs[good]] = bl[good]
        r2b[dup] = -2                       # two blocks claim one record: inconsistent, reported by verify
        self.rec_conflicts = int(dup.sum())
        return r2b

    def rec_of(self, fam, vx, vy):
        if 0 <= vx < GX and 0 <= vy < GY:
            return int(self.idx3[fam, vx, vy])
        return -1


# -- corpus side (learning / scoring only; the tracer never reads the .vo / RCF) -----------
def design_lis(d):
    """{(x, y): {LI index}} LOCAL_INTERCONNECT elements used per LAB (LAB-local names: alias-free)."""
    out = collections.defaultdict(set)
    for _net, edges in d["rcf"].items():
        for s, t in edges:
            for nd in (s, t):
                if nd[0] == "W" and nd[1] == "LOCAL_INTERCONNECT":
                    out[(nd[2], nd[3])].add(nd[5])
    return out


def design_cells(d):
    """{(x, y, le)} LEs with an LCCOMB or FF atom in the .vo."""
    out = set()
    for a in d["vo"].atoms.values():
        m = rl.LOC.match(a.get("location") or "")
        if m and m.group(1) in ("LCCOMB", "FF"):
            out.add((int(m.group(2)), int(m.group(3)), int(m.group(4)) // 2))
    return out


def learn(P, names, xm, ym):
    t0 = time.time()
    # pass A: firings and source codes per key -> defaults
    nfire, srcs_c = collections.Counter(), collections.defaultdict(collections.Counter)
    for di, name in enumerate(names):
        blocks, srcs = P.firing(P.active(name))
        cls = tile_class(P.btx[blocks].astype(np.int64), P.bty[blocks].astype(np.int64), xm, ym)
        for b, s, c in zip(blocks.tolist(), srcs.tolist(), cls.tolist()):
            k = (c, int(P.bkey[b]))
            nfire[k] += 1
            srcs_c[k][P.src_code(b, s)] += 1
    defaults = {}
    for k, n in nfire.items():
        if n >= DEFAULT_MIN:
            d = {c for c, m in srcs_c[k].items() if m >= DEFAULT_FRAC * n and c >= 0}
            if d:
                defaults[k] = d
    log.info("pass A: %d designs, %d keys, %d with a default source (%.0fs)", len(names), len(nfire), len(defaults), time.time() - t0)
    # pass B: positive intersections over non-default firings; cell votes
    wire, li, nd = {}, {}, collections.Counter()
    cell_votes, cell_n = collections.Counter(), collections.Counter()
    for di, name in enumerate(names):
        d = cc.load(name)
        blocks, srcs = P.firing(P.active(name, d["plane"]))
        src_set = np.unique(srcs)
        bytile = collections.defaultdict(list)
        for r in src_set.tolist():
            bytile[(int(P.vx[r]), int(P.vy[r]))].append(r)
        lis = design_lis(d)
        cells = design_cells(d)
        for b, s in zip(blocks.tolist(), srcs.tolist()):
            tx, ty = int(P.btx[b]), int(P.bty[b])
            k = (tile_class(tx, ty, xm, ym), int(P.bkey[b]))
            if P.src_code(b, s) in defaults.get(k, ()):
                continue
            nd[k] += 1
            vxb, vyb = XMIRROR - tx, ty
            cand = set()
            for dx in range(-WIN, WIN + 1):
                for dy in range(-WIN, WIN + 1):
                    for r in bytile.get((vxb + dx, vyb + dy), ()):
                        if r != s:
                            cand.add(code_off(P.fam[r], dx, dy, WIN))
            lc = set()
            for dy in (-1, 0, 1):
                for i in lis.get((tx, ty + dy), ()):
                    lc.add((dy + 1) * LI_MAX + i)
            if k in wire:
                wire[k] &= cand
                li[k] &= lc
            else:
                wire[k], li[k] = cand, lc
        bycell = collections.defaultdict(list)
        for (x, y, le) in cells:
            bycell[(x, y)].append(le)
        for r in src_set.tolist():
            f = int(P.fam[r])
            if P.fbounds[f + 1] - P.fbounds[f] != 9360:        # one record per LAB: the LE-output families
                continue
            cell_n[f] += 1
            vx, vy = int(P.vx[r]), int(P.vy[r])
            for M in range(XMIRROR - 2, XMIRROR + 3):
                for dy in (-1, 0, 1):
                    for le in bycell.get((M - vx, vy + dy), ()):
                        cell_votes[(f, M, dy, le)] += 1
        if di % 20 == 19:
            log.info("pass B: %d designs (%.0fs)", di + 1, time.time() - t0)
    # pass C: negatives.  A survivor record (LI) used in a design while its block did not fire is a
    # contradiction; counted per candidate, never averaged away.
    widx, lidx = collections.defaultdict(list), collections.defaultdict(list)
    for k, cand in wire.items():
        if nd[k] >= MIN_N:
            for c in cand:
                f, dvx, dvy = decode_off(c, WIN)
                widx[(k[0], f, dvx, dvy)].append((k[1], c))
    for k, cand in li.items():
        if nd[k] >= MIN_N:
            for c in cand:
                lidx[(k[0], c // LI_MAX - 1, c % LI_MAX)].append((k[1], c))
    neg_w, neg_l, use_w, use_l = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    for di, name in enumerate(names):
        d = cc.load(name)
        blocks, srcs = P.firing(P.active(name, d["plane"]))
        fired = set(blocks.tolist())
        for r in np.unique(srcs).tolist():
            f, vx, vy = int(P.fam[r]), int(P.vx[r]), int(P.vy[r])
            for dvx in range(-WIN, WIN + 1):
                for dvy in range(-WIN, WIN + 1):
                    tx, ty = XMIRROR - (vx - dvx), vy - dvy
                    c = tile_class(tx, ty, xm, ym)
                    for kid, code in widx.get((c, f, dvx, dvy), ()):
                        use_w[(c, kid, code)] += 1
                        if P.block_at(tx, ty, kid) not in fired:
                            neg_w[(c, kid, code)] += 1
        for (x, y), idxs in design_lis(d).items():
            for i in idxs:
                for dy in (-1, 0, 1):
                    c = tile_class(x, y - dy, xm, ym)
                    for kid, code in lidx.get((c, dy, i), ()):
                        use_l[(c, kid, code)] += 1
                        if P.block_at(x, y - dy, kid) not in fired:
                            neg_l[(c, kid, code)] += 1
        if di % 20 == 19:
            log.info("pass C: %d designs (%.0fs)", di + 1, time.time() - t0)
    # finalise
    wires, lis_map, stats, amb = {}, {}, collections.Counter(), []
    for k, n in nfire.items():
        if nd[k] < MIN_N:
            stats["default-only" if n >= MIN_N else "undersampled"] += 1
            continue
        ws = {c: (neg_w[(k[0], k[1], c)], use_w[(k[0], k[1], c)]) for c in wire[k]}
        ls = {c: (neg_l[(k[0], k[1], c)], use_l[(k[0], k[1], c)]) for c in li[k]}
        wok = [c for c, (ng, u) in ws.items() if ng <= NEG_RATE * u]
        lok = [c for c, (ng, u) in ls.items() if ng <= NEG_RATE * u]
        wdesc = sorted((decode_off(c, WIN), ng, u) for c, (ng, u) in ws.items())
        ldesc = sorted(((c // LI_MAX - 1, c % LI_MAX), ng, u) for c, (ng, u) in ls.items())
        if len(wok) == 1 and not lok:
            wires[k] = decode_off(wok[0], WIN)
            stats["wire"] += 1
        elif len(lok) == 1 and not wok:
            lis_map[k] = (lok[0] // LI_MAX - 1, lok[0] % LI_MAX)
            stats["li"] += 1
        elif not wok and not lok:
            stats["none"] += 1
            amb.append((k, n, nd[k], "none", wdesc, ldesc))
        elif len(wok) == 1 and len(lok) == 1:
            stats["wire+li"] += 1
            amb.append((k, n, nd[k], "wire+li", wdesc, ldesc))
        else:
            stats["ambiguous"] += 1
            amb.append((k, n, nd[k], "ambiguous", wdesc, ldesc))
    cellmap = {}
    for f, n in cell_n.items():
        best = max(((v, M, dy, le) for (ff, M, dy, le), v in cell_votes.items() if ff == f), default=None)
        if best and best[0] >= 0.9 * n and n >= 3:
            cellmap[f] = (best[1], best[2], best[3], best[0], n)
        log.info("cell family %d (ids %d..): used %d, best vote %s", f, P.fbounds[f], n, best)
    log.info("learn done: %d designs, %d keys fired: %s; defaults %d; cell families %d", len(names), len(nfire), dict(stats),
             len(defaults), len(cellmap))
    log.info("wire keys per class: %s", sorted(collections.Counter(k[0] for k in wires).items()))
    log.info("LI keys per class: %s", sorted(collections.Counter(k[0] for k in lis_map).items()))
    for k, n, m, why, w, l in sorted(amb, key=lambda a: -a[2])[:40]:
        log.info("  %-9s class %2d key %-22s fired %5d non-default %5d wires %s lis %s", why, k[0], P.keys[k[1]], n, m, w[:5], l[:5])
    out = {"class": {"x_mod": xm, "y_mod": ym}, "designs": names, "families": P.fbounds.tolist(),
           "wires": {f"{c}|{P.keys[kid]}": list(v) for (c, kid), v in wires.items()},
           "lis": {f"{c}|{P.keys[kid]}": list(v) for (c, kid), v in lis_map.items()},
           "defaults": {f"{c}|{P.keys[kid]}": [list(decode_off(x, SWIN)) for x in v] for (c, kid), v in defaults.items()},
           "cells": {str(f): list(v[:3]) for f, v in cellmap.items()},
           "cell_votes": {str(f): [v[3], v[4]] for f, v in cellmap.items()},
           "stats": dict(stats),
           "unresolved": [{"class": k[0], "key": P.keys[k[1]], "fired": n, "non_default": m, "why": why,
                           "wires": [[list(o), ng, u] for o, ng, u in w[:12]], "lis": [[list(o), ng, u] for o, ng, u in l[:12]]}
                          for k, n, m, why, w, l in sorted(amb, key=lambda a: -a[2])]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=0)
    log.info("wrote %s", OUT)


def verify(P, names):
    """Every non-default firing of a mapped block must have its predicted record used as a source (wires) or
    its predicted LI used (lis) in that design; a tile that fails is a disagreement with its class."""
    t0 = time.time()
    bad_tiles = collections.defaultdict(collections.Counter)
    ok_n, bad_n = collections.Counter(), collections.Counter()
    for di, name in enumerate(names):
        d = cc.load(name)
        blocks, srcs = P.firing(P.active(name, d["plane"]))
        src_set = set(srcs.tolist())
        lis = design_lis(d)
        for b, s in zip(blocks.tolist(), srcs.tolist()):
            tx, ty = int(P.btx[b]), int(P.bty[b])
            k = (tile_class(tx, ty, P.xm, P.ym), int(P.bkey[b]))
            if P.src_code(b, s) in P.defaults.get(k, ()):
                continue
            w = P.wires.get(k)
            if w is not None:
                r = P.rec_of(w[0], XMIRROR - tx + w[1], ty + w[2])
                if r >= 0 and r in src_set and r != s:
                    ok_n["wire"] += 1
                else:
                    bad_n["wire"] += 1
                    bad_tiles[(tx, ty)][("wire", P.keys[k[1]], "no such record" if r < 0 else "record unused")] += 1
                continue
            p = P.lis.get(k)
            if p is not None:
                if p[1] in lis.get((tx, ty + p[0]), ()):
                    ok_n["li"] += 1
                else:
                    bad_n["li"] += 1
                    bad_tiles[(tx, ty)][("li", P.keys[k[1]], f"LI {p[1]} dy {p[0]} unused")] += 1
        if di % 20 == 19:
            log.info("verify: %d designs (%.0fs)", di + 1, time.time() - t0)
    log.info("verify %d designs: wire firings agree %d / disagree %d; LI firings agree %d / disagree %d; tiles with a "
             "disagreement %d; records claimed by two blocks %d", len(names), ok_n["wire"], bad_n["wire"], ok_n["li"],
             bad_n["li"], len(bad_tiles), P.rec_conflicts)
    bycls = collections.Counter()
    for (tx, ty), c in bad_tiles.items():
        bycls[(tx % P.xm if P.xm else 0, ty % P.ym, tx in (1, 116) or ty in (1, 90))] += sum(c.values())
    for k, n in bycls.most_common(20):
        log.info("  class x%%%d=%d y%%%d=%d edge=%s: %d disagreeing firings", P.xm, k[0], P.ym, k[1], k[2], n)
    for (tx, ty), c in sorted(bad_tiles.items(), key=lambda kv: -sum(kv[1].values()))[:30]:
        log.info("  tile X%d Y%d: %s", tx, ty, c.most_common(4))


# -- the tracer ---------------------------------------------------------------------------------
class PhysTracer:
    """trace(key, x, y) -> (driver, reason) with the lifter's driver tuples.  LCCOMB pins: the learner names
    the LI / LOCAL_LINE at the LE-input mux (not in asm), everything from the LI driver mux to the LE_BUFFER
    is walked on record ids.  FF pins and the carry / constant codes come from the learner."""

    def __init__(self, P, plane, geom, learner=None, valid=None, terminals=(), fallback=False):
        self.P, self.plane, self.geom = P, plane, geom
        self.learner = rd.Tracer(learner, plane, geom, terminals=terminals) if learner is not None else None
        self.valid = valid
        self.fallback = fallback
        blocks, srcs = P.firing(P.active(None, plane))
        self.fired = np.full(P.nblocks, -1, np.int32)
        self.fired[blocks] = srcs
        self.multi = int((np.bincount(blocks, minlength=P.nblocks) > 1).sum())
        self.memo = {}
        self.why = collections.Counter()

    @property
    def valid(self):
        return self._valid

    @valid.setter
    def valid(self, fn):
        self._valid = fn
        if self.learner is not None:
            self.learner.valid = fn

    def li_block(self, x, y, i):
        P = self.P
        hit = P.li_inv.get((tile_class(x, y, P.xm, P.ym), i))
        if hit is None:
            return -1
        kid, dy = hit
        return P.block_at(x, y - dy, kid)

    def cell_of(self, r):
        P = self.P
        c = P.cells.get(int(P.fam[r]))
        if c is None:
            return None
        M, dy, le = c
        return M - int(P.vx[r]), int(P.vy[r]) + dy, le, int(P.fam[r])

    def cell_kind(self, X, Y, le, f):
        """comb or reg on an LE output: the learner's LE_BUFFER / LOCAL_LINE select bit."""
        if self.learner is None:
            return None
        key = ("LE_BUFFER", 0, f - 16) if f is not None else ("LOCAL_LINE", 0, le)
        cands, _why = self.learner.dec.sources(self.plane, self.geom, key, X, Y)
        kinds = {c.split("|")[1] for c in cands if c.startswith("DRV|")}
        return kinds.pop() if len(kinds) == 1 else None

    def driver(self, X, Y, le, f):
        kind = self.cell_kind(X, Y, le, f)
        if kind is None:
            return None, "cell output: comb/reg select unreadable"
        n = 2 * le + (kind == "FF")
        if self.valid is not None and not self.valid(kind, X, Y, n):
            return None, "driver cell unused"
        return ("DRV", kind, n, X, Y), "ok"

    def walk(self, r):
        P = self.P
        for _hop in range(MAX_HOPS):
            cell = self.cell_of(r)
            if cell is not None:
                return self.driver(*cell)
            b = int(P.rec2block[r])
            if b == -2:
                return None, f"record claimed by two blocks (fam {P.fam[r]})"
            if b < 0:
                return ("REC", int(P.fam[r]), r, int(P.vx[r]), int(P.vy[r])), "terminal"
            r2 = int(self.fired[b])
            if r2 < 0:
                return None, f"driver mux idle (fam {P.fam[r]})"
            if P.src_code(b, r2) in P.defaults.get((tile_class(int(P.btx[b]), int(P.bty[b]), P.xm, P.ym), int(P.bkey[b])), ()):
                return None, f"driver mux at default (fam {P.fam[r]})"
            r = r2
        return None, "loop"

    def trace(self, key, x, y):
        node = (tuple(key), x, y)
        if node in self.memo:
            return self.memo[node]
        got = self._trace(key, x, y)
        self.memo[node] = got
        self.why[got[1] if got[0] is None else "ok"] += 1
        return got

    def _trace(self, key, x, y):
        kind, n, port = key
        if kind != "LCCOMB" or self.learner is None:
            return self.learner.trace(key, x, y) if self.learner is not None else (None, "no learner")
        cands, why = self.learner.dec.sources(self.plane, self.geom, key, x, y)
        if not cands:
            return None, f"{why}:LE input"
        found, whys = set(), []
        for c in cands:
            k2, dx, dy = rd.parse_src(c)
            if k2[0] == "CONST":
                found.add(("CONST", k2[1], 0, 0, 0))
            elif k2[0] == "CIN":
                found.add(("CIN", 0, 0, x, y))
            elif k2[0] == "LUTOUT":
                found.add(("LUTOUT", 0, 0, x, y))
            elif k2[0] == "DRV":
                found.add(("DRV", k2[1], k2[2], x + dx, y + dy))
            elif k2[0] == "LOCAL_LINE":
                g, w = self.driver(x + dx, y + dy, k2[2], None)
                found.add(g) if g else whys.append(w)
            elif k2[0] == "LOCAL_INTERCONNECT":
                b = self.li_block(x + dx, y + dy, k2[2])
                if b < 0:
                    whys.append(f"LI {k2[2]}: no driver block in the map")
                    continue
                r = int(self.fired[b])
                if r < 0:
                    whys.append("LI driver idle")
                    continue
                P = self.P
                if P.src_code(b, r) in P.defaults.get((tile_class(int(P.btx[b]), int(P.bty[b]), P.xm, P.ym), int(P.bkey[b])), ()):
                    continue                    # LI at its default: unused, not a candidate
                g, w = self.walk(r)
                if g is not None and g[0] == "REC":
                    g = ("WIRE", f"F{g[1]}", g[2], 0, g[3], g[4])
                found.add(g) if g is not None else whys.append(w)
            else:
                whys.append(f"unhandled learner source {k2[0]}")
        if len(found) == 1:
            got = next(iter(found))
            if got[0] == "WIRE":
                return self._fallback(key, x, y, f"terminal record {got[1]}", got)
            return got, "ok"
        if found:
            return self._fallback(key, x, y, "ambiguous driver")
        return self._fallback(key, x, y, whys[0] if whys else "no candidate")

    def _fallback(self, key, x, y, why, got=None):
        if self.fallback and self.learner is not None:
            g2, w2 = self.learner.trace(key, x, y)
            if g2 is not None:
                return g2, f"learner ({why})"
        return (got, why) if got is not None else (None, why)


# -- net-level score ------------------------------------------------------------------------------
def expected_pins(d):
    """[(key, x, y, expected)] for every LCCOMB / FF pin of every placed cell in the .vo.
    expected: ("DRV", kind, n, x, y) | ("CONST", v) | ("LUTOUT",) | ("CIN",) | ("WIRE", net) | None (unconnected)."""
    vo = d["vo"]
    src, atoms = {}, []
    for a in vo.atoms.values():
        m = rl.LOC.match(a.get("location") or "")
        if m and a["type"] in ("cycloneive_lcell_comb", "dffeas"):
            kind, x, y, n = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
            atoms.append((a, kind, x, y, n))
            for p, _b, _d, net, _i, _c in a["conns"]:
                if net and p in ("combout", "cout", "q"):
                    src[vo.canon(net)] = ("DRV", kind, n, x, y)
        elif a["type"] in ("cycloneive_io_ibuf", "cycloneive_clkctrl"):
            port = "o" if a["type"] == "cycloneive_io_ibuf" else "outclk"
            for p, _b, _d, net, _i, _c in a["conns"]:
                if p == port and net:
                    src[vo.canon(net)] = ("WIRE", vo.canon(net))
    out = []
    for a, kind, x, y, n in atoms:
        ports = ("dataa", "datab", "datac", "datad") if kind == "LCCOMB" else ("d", "clk", "ena", "clrn", "sclr", "sload", "asdata")
        conns = {p: (net, const) for p, _b, _d, net, _i, const in a["conns"]}
        for p in ports:
            net, const = conns.get(p, (None, None))
            key = (kind, n, "DATAD" if p == "d" else p.upper())
            if kind == "LCCOMB" and p == "datac" and a["params"].get("sum_lutc_input") == "cin":
                out.append((key, x, y, ("CIN",)))
                continue
            if net is None:
                out.append((key, x, y, ("CONST", int(const)) if const in ("0", "1") else None))
                continue
            s = src.get(vo.canon(net))
            if kind == "FF" and p == "d" and s and s[0] == "DRV" and s[1] == "LCCOMB" and (s[3], s[4], s[2]) == (x, y, n - 1):
                s = ("LUTOUT",)
            out.append((key, x, y, s if s else ("WIRE", "?")))
    return out


def score_pin(exp, got, why):
    """-> (bucket, detail).  bucket in matched / missing / extra / wrong / terminal / skip."""
    if exp is None:
        return ("extra", "driver on an unconnected pin") if got is not None else ("skip", "")
    if exp[0] == "CONST":
        if got is None or (got[0] == "CONST" and got[1] == exp[1]):
            return "matched", "const"
        return ("wrong", "const read as a driver") if got[0] != "CONST" else ("wrong", "wrong const")
    if got is None:
        return "missing", why
    if exp[0] == "WIRE":
        if got[0] in ("WIRE", "REC"):
            return "terminal", f"{got[1]}"
        return "wrong", "cell driver on a pad/clock pin"
    if exp[0] in ("CIN", "LUTOUT"):
        return ("matched", exp[0]) if got[0] == exp[0] else ("wrong", f"{exp[0]} read as {got[0]}")
    if got[0] == "DRV":
        return ("matched", "cell") if got == exp else ("wrong", "other cell")
    return "wrong", f"{got[0]} instead of a cell"


def score(P, names, tables):
    import cycloneiv_lift as lf
    learner = rd.Decoder(tables)
    geom = P.g
    res = {"phys": collections.defaultdict(collections.Counter), "learner": collections.defaultdict(collections.Counter)}
    why = {"phys": collections.defaultdict(collections.Counter), "learner": collections.defaultdict(collections.Counter)}
    t0 = time.time()
    lift = lf.CycloneIVLift(geom.die, tables)
    tiles = [(x, y) for x in sorted(geom.kind) if geom.kind[x] == "LAB" for y in range(1, geom.ymax)]
    tidx = {t: i for i, t in enumerate(tiles)}
    for di, name in enumerate(names):
        d = cc.load(name)
        plane = d["plane"]
        used, _masks = lift.scan(plane, tiles)

        def valid(kind, x, y, n):
            i = tidx.get((x, y))
            return kind not in ("LCCOMB", "FF") or (i is not None and bool(used[i][n // 2]))
        trs = {"phys": PhysTracer(P, plane, geom, learner=learner, valid=valid, terminals=lf.TERMINAL_WIRES),
               "learner": rd.Tracer(learner, plane, geom, terminals=lf.TERMINAL_WIRES)}
        trs["learner"].valid = valid
        for key, x, y, exp in expected_pins(d):
            ptype = f"{key[0]}.{key[2]}"
            for which, tr in trs.items():
                got, w = tr.trace(key, x, y)
                bucket, detail = score_pin(exp, got, w)
                res[which][ptype][bucket] += 1
                if bucket in ("missing", "wrong", "terminal"):
                    why[which][ptype][f"{bucket}: {detail}"] += 1
        log.info("score: %s (%d / %d, %.0fs) multi-fired blocks %d", name, di + 1, len(names), time.time() - t0, trs["phys"].multi)
    for which in ("phys", "learner"):
        log.info("== %s tracer, %d designs ==", which, len(names))
        tot = collections.Counter()
        for pt in sorted(res[which]):
            c = res[which][pt]
            den = c["matched"] + c["missing"] + c["extra"] + c["wrong"]
            log.info("  %-14s matched %6d / (matched + missing %5d + extra %4d + wrong %4d) = %6.2f%%  terminal(pad/clock) %4d  skip %d",
                     pt, c["matched"], c["missing"], c["extra"], c["wrong"], 100 * c["matched"] / max(1, den), c["terminal"], c["skip"])
            if pt.startswith("LCCOMB"):
                tot.update({k: c[k] for k in ("matched", "missing", "extra", "wrong", "terminal")})
            for k, n in why[which][pt].most_common(8):
                log.info("      %-60s %d", k, n)
        den = tot["matched"] + tot["missing"] + tot["extra"] + tot["wrong"]
        log.info("  LCCOMB pins: matched %d / (matched %d + missing %d + extra %d + wrong %d) = %.2f%%; pad/clock-driven (terminal, unverified) %d",
                 tot["matched"], tot["matched"], tot["missing"], tot["extra"], tot["wrong"], 100 * tot["matched"] / max(1, den), tot["terminal"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("blocks", "learn", "verify", "score"))
    ap.add_argument("--designs", default="gx150_*")
    ap.add_argument("--split", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--x-mod", type=int, default=8, help="tile class: X mod N (0 = one class per row phase)")
    ap.add_argument("--y-mod", type=int, default=4)
    ap.add_argument("--tables", default=os.path.join(REPO, "tmp", "cycloneiv", "rl_gx_m8f.json"))
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_phys_trace.log"))])
    split = a.split or {"learn": "even", "verify": "all", "score": "odd"}.get(a.cmd, "all")
    names = [n for n in cc.designs(a.designs) if rl.split_of(n, split)]
    if a.limit:
        names = names[:a.limit]
    P = Phys(need_map=a.cmd in ("verify", "score"))
    if a.cmd == "blocks":
        return
    if a.cmd == "learn":
        learn(P, names, a.x_mod, a.y_mod)
    elif a.cmd == "verify":
        verify(P, names)
    else:
        score(P, names, a.tables.split(","))


if __name__ == "__main__":
    main()
