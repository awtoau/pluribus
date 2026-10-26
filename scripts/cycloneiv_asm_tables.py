"""Learn the name maps the asm decode needs from oracle designs, and score held-out designs.

Device-level tables (lifters/data/cycloneiv_ep4cgx150_asm_names.json), learnt once from training designs:
- alias: RCF source (type, I) -> vendor wire forms (dir, k, C - X, R + Y).  The RCF names a wire by the
  column (R4) / row (C4) it is DRIVEN from, so one physical wire (one asm record) has several RCF names;
  a decoded record matches an oracle source iff its form is in the alias set.
- unnamed: LE_BUFFER / LOCAL_LINE records carry no icname; record = base[I] + 90 * colrank(X) + Y
  (colrank = LAB columns right to left).
- blocks: (tile class, second-level bit positions relative to the tile anchor) -> RCF destination
  (type, s, i, dx, dy) of the mux.
Bootstrap of the destination identity uses the learner's mux positions (tmp/cycloneiv/rl_gx_m8.json).
"""
import collections
import json
import os
import time

import numpy as np

import cycloneiv_asm_decode as D
import cycloneiv_corpus as cc
import cycloneiv_route_learn as rl

REPO = D.REPO
OUT = os.path.join(REPO, "lifters", "data", "cycloneiv_ep4cgx150_asm_names.json")
LEARNER = os.path.join(REPO, "tmp", "cycloneiv", "rl_gx_m8.json")
VTYPE = {"V4": "C4", "H4": "R4", "V16": "C16", "H24": "R24"}
LAB_DSTS = ("LOCAL_INTERCONNECT", "R4", "C4", "C16", "R24", "LCCOMB", "FF", "LAB_CONTROL_MUX", "LOCAL_LINE", "LE_BUFFER",
            "LAB_CLK", "BLK_CLK_BUF")


def tile(dec, f, v):
    g = dec.g
    return dec.col_of(f), int(round((v - g.vy0) / g.vpitch))


def block_key(dec, G):
    """(tile x, y, relative key) of a group's mux: the non-select entries' positions relative to the tile
    anchor of the select bit (groups without non-select entries key on the select bit itself)."""
    s, n = dec.gstart[G], dec.gsize[G]
    pf, pv = dec.pf[s:s + n], dec.pv[s:s + n]
    b0sel = np.asarray(dec.b0[s:s + n]) == 1
    j = int(np.argmax(b0sel)) if b0sel.any() else 0
    x, y = tile(dec, int(pf[j]), int(pv[j]))
    f0, v0 = dec.g.anchor(x, y)
    rel = sorted((int(pf[k]) - f0, int(pv[k]) - v0) for k in range(n) if not b0sel[k]) or [(int(pf[j]) - f0, int(pv[j]) - v0)]
    return x, y, "|".join(f"{a},{b}" for a, b in rel)


def oracle(name, d, g):
    """{dst node: src node} and {net: [dst nodes]}; node = (type, s, i, x, y) or ('DRV', kind, n, x, y)."""
    pips, nets = {}, collections.defaultdict(list)
    for net, edges in d["rcf"].items():
        for src, dst in edges:
            a, b = rl.node_at(d["vo"], src), rl.node_at(d["vo"], dst)
            if a is None or b is None:
                continue
            bx, by, bkey = b
            ax, ay, akey = a
            dn, sn = bkey + (bx, by), akey + (ax, ay)
            pips[dn] = sn
            nets[net].append(dn)
    return pips, nets


def learner_index():
    """learner table -> {class: [(dst key, anchor offset, mux positions relative to the mux tile anchor)]}."""
    raw = json.load(open(LEARNER))
    out = collections.defaultdict(list)
    for k, v in raw.items():
        if k == "_meta" or not v.get("mux"):
            continue
        cls, typ, s, i = k.split("|")
        s, i = (int(s) if s.lstrip("-").isdigit() else s), (int(i) if i.lstrip("-").isdigit() else i)
        out[cls].append(((typ, s, i), tuple(v.get("anchor", (0, 0))), {(p[0] + rl.WF[0], p[1] + rl.WV[0]) for p in v["mux"]}))
    return out


class Tables:
    def __init__(self, dec, path=OUT):
        t = json.load(open(path))
        self.alias = {tuple(k.split("|")): {tuple(f) for f in v} for k, v in t["alias"].items()}
        self.unnamed = {tuple(k.split("|")): v for k, v in t["unnamed"].items()}
        self.blocks = t["blocks"]
        labcols = sorted(x for x, k in dec.g.kind.items() if k == "LAB")
        self.colrank = {x: i for i, x in enumerate(reversed(labcols))}
        self.rankcol = {i: x for x, i in self.colrank.items()}
        self.dec = dec
        # inverse tables for decoding: (class, dst rel key) -> block rel key; (dir, k) -> [(type, I, C-X, R+Y)]
        self.dst2block = {}
        for bk, dk in self.blocks.items():
            cls, key = bk.split("|", 1)
            self.dst2block[(cls, dk)] = key
        self.form2rcf = collections.defaultdict(list)
        for (typ, i), forms in self.alias.items():
            for dr, k, cx, ry in forms:
                self.form2rcf[(dr, k)].append((typ, int(i), cx, ry))

    def rcf_names(self, rec, x, y):
        """Learner-style source keys 'TYPE|0|I|dx|dy' (relative to tile x, y) an asm record can carry."""
        nm = self.dec.names.get(rec)
        out = []
        if nm is None:
            for (typ, i), base in self.unnamed.items():
                r = rec - base
                if 0 <= r and r // 90 in self.rankcol and 0 <= r % 90 <= self.dec.g.ymax:
                    out.append(f"{typ}|0|{i}|{self.rankcol[r // 90] - x}|{r % 90 - y}")
            return out
        p = D.vendor_parse(nm)
        if p is None or p[3] is None or p[4] is None:
            return out
        _, dr, k, R, C = p
        for typ, i, cx, ry in self.form2rcf.get((dr, k), ()):
            out.append(f"{typ}|0|{i}|{C - cx - x}|{ry - R - y}")
        return out

    def decode_design(self, plane):
        """{(x, y, dst key tuple): record} for every selected mux input the block map can name."""
        gids, recs, _ = active_groups(self.dec, plane)
        out = {}
        for G, r in zip(gids, recs):
            x, y, key = block_key(self.dec, int(G))
            if x not in self.dec.g.kind or not 0 <= y <= self.dec.g.ymax:
                continue
            dk = self.blocks.get(f"{rl.tile_class(self.dec.g, x, y, 8)}|{key}")
            if dk is None:
                continue
            typ, s, i, dx, dy = dk.split("|")
            s = int(s) if s.lstrip("-").isdigit() else s
            i = int(i) if i.lstrip("-").isdigit() else i
            out[(x + int(dx), y + int(dy), (typ, s, i))] = int(r)
        return out

    def src_matches(self, rec, sn):
        """Does asm record `rec` denote the oracle source node sn?"""
        nm = self.dec.names.get(rec)
        typ, _, i, X, Y = sn
        if nm is None:
            base = self.unnamed.get((typ, str(i)))
            return base is not None and X in self.colrank and rec == base + 90 * self.colrank[X] + Y
        p = D.vendor_parse(nm)
        if p is None or p[3] is None or p[4] is None:
            return False
        vt, dr, k, R, C = p
        return (dr, k, C - X, R + Y) in self.alias.get((typ, str(i)), ())


def active_groups(dec, plane):
    """dec.active() minus the select-bit-only groups (no second-level entry: they fire alongside the real
    input group of the same mux and carry no source information)."""
    gids, recs, blocks = dec.active(plane)
    keep = np.asarray(dec.npred[gids] < dec.gsize[gids])
    return gids[keep], recs[keep], blocks[keep]


def learn(dec, names):
    """Pass A: block -> destination by co-occurrence (the true dst is present in the tile every time the
    block is active, others only by chance).  Pass B: source aliases with the dst known."""
    t0 = time.time()
    labcols = sorted(x for x, k in dec.g.kind.items() if k == "LAB")
    colrank = {x: i for i, x in enumerate(reversed(labcols))}
    cooc = collections.defaultdict(collections.Counter)
    act = collections.Counter()           # block key -> activations
    occ = collections.Counter()           # (class, dst rel key) -> occurrences over every LAB tile of the class
    poshit = collections.defaultdict(collections.Counter)   # block key -> learner dst whose mux holds the block's bits
    bycls = learner_index()
    labtiles = [(x, y) for x, k in dec.g.kind.items() if k == "LAB" for y in range(1, dec.g.ymax)]
    for di, name in enumerate(names):
        d = cc.load(name)
        pips, _ = oracle(name, d, dec.g)
        bytile = collections.defaultdict(list)
        for dn in pips:
            if dn[0] in LAB_DSTS:
                bytile[(dn[3], dn[4])].append(f"{dn[0]}|{dn[1]}|{dn[2]}")
        for x, y in labtiles:
            cls = rl.tile_class(dec.g, x, y, 8)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dk in bytile.get((x + dx, y + dy), ()):
                        occ[f"{cls}|{dk}|{dx}|{dy}"] += 1
        gids, recs, blocks = active_groups(dec, d["plane"])
        for G in gids:
            x, y, key = block_key(dec, int(G))
            if x not in dec.g.kind or not 0 <= y <= dec.g.ymax:
                continue
            bk = f"{rl.tile_class(dec.g, x, y, 8)}|{key}"
            act[bk] += 1
            c = cooc[bk]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dk in bytile.get((x + dx, y + dy), ()):
                        c[f"{dk}|{dx}|{dy}"] += 1
            if bk not in poshit:
                rel = {tuple(map(int, q.split(","))) for q in key.split("|")}
                hits = set()
                for dx, dy in ((0, 0), (-1, 0), (0, 1), (-1, 1)):
                    tx, ty = x + dx, y + dy
                    if tx not in dec.g.kind or not 0 <= ty <= dec.g.ymax:
                        continue
                    for (typ, s, i), (ax, ay), mux in bycls.get(rl.tile_class(dec.g, tx, ty, 8), []):
                        if tx + ax == x and ty + ay == y and rel <= mux:
                            hits.add(f"{typ}|{s}|{i}|{dx}|{dy}")
                poshit[bk].update(hits)
        if di % 10 == 9:
            D.log.info("learn A: %d designs, %d block keys (%.0fs)", di + 1, len(act), time.time() - t0)
    # a block names a destination: the learner mux holding its bits when unique (LI / R4 / C4 positions are
    # exact per class), else the dst that appears together with it nearly always, in BOTH directions
    bmap, amb, bypos = {}, 0, 0
    for bk, n in act.items():
        if len(poshit.get(bk, ())) == 1:
            bmap[bk] = next(iter(poshit[bk]))
            bypos += 1
            continue
        if n < 3 or not cooc[bk]:
            continue
        cls = bk.split("|", 1)[0]
        good = [(m, dk) for dk, m in cooc[bk].items() if m >= 0.9 * n and m >= 0.9 * occ.get(f"{cls}|{dk}", 0)]
        if len(good) == 1:
            bmap[bk] = good[0][1]
        elif good:
            amb += 1
    D.log.info("block map: %d keys (%d by learner position, %d ambiguous, %d under-sampled)", len(bmap), bypos, amb,
               sum(1 for n in act.values() if n < 3))
    alias = collections.defaultdict(collections.Counter)
    unnamed = collections.defaultdict(collections.Counter)
    for di, name in enumerate(names):
        d = cc.load(name)
        pips, _ = oracle(name, d, dec.g)
        gids, recs, blocks = active_groups(dec, d["plane"])
        for G, r in zip(gids, recs):
            r = int(r)
            x, y, key = block_key(dec, int(G))
            if x not in dec.g.kind or not 0 <= y <= dec.g.ymax:
                continue
            dk = bmap.get(f"{rl.tile_class(dec.g, x, y, 8)}|{key}")
            if dk is None:
                continue
            typ, s, i, dx, dy = dk.split("|")
            dn = (typ, int(s) if s.lstrip("-").isdigit() else s, int(i) if i.lstrip("-").isdigit() else i, x + int(dx), y + int(dy))
            sn = pips.get(dn)
            if sn is None:
                continue
            nm = dec.names.get(r)
            if nm is None:
                if sn[3] in colrank:
                    unnamed[(sn[0], sn[2])][r - 90 * colrank[sn[3]] - sn[4]] += 1
                continue
            p = D.vendor_parse(nm)
            if p is None or p[3] is None or p[4] is None:
                continue
            vt, dr, k, R, C = p
            alias[(sn[0], sn[2])][(dr, k, C - sn[3], R + sn[4])] += 1
        if di % 10 == 9:
            D.log.info("learn B: %d designs, %d alias keys (%.0fs)", di + 1, len(alias), time.time() - t0)
    out_alias = {}
    for key, c in alias.items():
        tot = sum(c.values())
        keep = [list(f) for f, n in c.items() if n >= 2 and n >= 0.02 * tot]
        out_alias["|".join(map(str, key))] = keep
    out_unnamed = {}
    for key, c in unnamed.items():
        base, n = c.most_common(1)[0]
        if n >= 3 and n >= 0.5 * sum(c.values()):
            out_unnamed["|".join(map(str, key))] = int(base)
    D.log.info("alias keys %d, unnamed bases %d, block keys %d", len(out_alias), len(out_unnamed), len(bmap))
    json.dump({"alias": out_alias, "unnamed": out_unnamed, "blocks": bmap, "designs": len(names)}, open(OUT, "w"), indent=0)
    D.log.info("wrote %s", OUT)


def score(dec, names):
    T = Tables(dec)
    per = collections.defaultdict(collections.Counter)
    why = collections.Counter()
    nets_ok = nets_all = 0
    t0 = time.time()
    for di, name in enumerate(names):
        d = cc.load(name)
        pips, nets = oracle(name, d, dec.g)
        gids, recs, blocks = active_groups(dec, d["plane"])
        decoded = {}
        for G, r in zip(gids, recs):
            x, y, key = block_key(dec, int(G))
            if x not in dec.g.kind or not 0 <= y <= dec.g.ymax:
                continue
            dk = T.blocks.get(f"{rl.tile_class(dec.g, x, y, 8)}|{key}")
            if dk is None:
                why["active group, unknown block"] += 1
                continue
            typ, s, i, dx, dy = dk.split("|")
            dn = (typ, int(s) if s.lstrip("-").isdigit() else s, int(i) if i.lstrip("-").isdigit() else i, x + int(dx), y + int(dy))
            decoded[dn] = int(r)
        for dn, sn in pips.items():
            if dec.g.kind.get(dn[3]) != "LAB" or dn[0] not in LAB_DSTS:
                continue
            r = decoded.get(dn)
            if r is None:
                per[dn[0]]["missing"] += 1
                why[f"missing {dn[0]}"] += 1
            elif T.src_matches(r, sn):
                per[dn[0]]["matched"] += 1
            else:
                per[dn[0]]["wrong"] += 1
                why[f"wrong {dn[0]} <- {sn[0]} (rec {'named' if r in dec.names else 'unnamed'})"] += 1
        for dn in decoded:
            if dn not in pips:
                per[dn[0]]["extra"] += 1
        for net, dns in nets.items():
            if all(dec.g.kind.get(dn[3]) == "LAB" and dn[0] in LAB_DSTS for dn in dns):
                nets_all += 1
                nets_ok += all(dn in decoded and T.src_matches(decoded[dn], pips[dn]) for dn in dns)
        if di % 10 == 9:
            D.log.info("score: %d designs (%.0fs)", di + 1, time.time() - t0)
    tot = collections.Counter()
    for c in per.values():
        tot.update(c)
    den = tot["matched"] + tot["missing"] + tot["extra"] + tot["wrong"]
    D.log.info("designs %d: pips matched %d / (matched %d + missing %d + extra %d + wrong %d) = %.2f%%", len(names), tot["matched"],
               tot["matched"], tot["missing"], tot["extra"], tot["wrong"], 100 * tot["matched"] / max(1, den))
    D.log.info("nets (LAB dsts only): %d / %d all pips matched (%.2f%%)", nets_ok, nets_all, 100 * nets_ok / max(1, nets_all))
    for typ, c in sorted(per.items(), key=lambda kv: -sum(kv[1].values())):
        dn_ = c["matched"] + c["missing"] + c["extra"] + c["wrong"]
        D.log.info("  %-22s matched %7d missing %7d extra %6d wrong %5d  %6.2f%%", typ, c["matched"], c["missing"], c["extra"], c["wrong"],
                   100 * c["matched"] / max(1, dn_))
    for k, v in why.most_common(25):
        D.log.info("    %-60s %d", k, v)
