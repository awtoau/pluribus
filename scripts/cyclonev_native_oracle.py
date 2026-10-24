#!/usr/bin/env python3.15t
"""Native Cyclone V decode vs Quartus oracles (claim 1 of docs/cyclonev-native-decoder.md).

Oracles (read-only, corpus/cyclonev/corpus.db): postfit atoms/conns (`.vo`), RCF routes (`quartus_cdb` back-annotation).
Every field reports matched / missing / extra / wrong; the headline is matched / (matched + missing + extra + wrong).
Rules learned from the oracle (routing element-type map, ...) are fit on split A only and frozen for split B.
"""
import collections
import json
import os
import re
import sqlite3

import cyclonev_native_tables as nt

CORPUS_DB_CANDIDATES = ("corpus/cyclonev/corpus.db", "/mnt/2tb/git/pluribus/corpus/cyclonev/corpus.db")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def corpus_db():
    for c in CORPUS_DB_CANDIDATES:
        p = c if os.path.isabs(c) else os.path.join(REPO, c)
        if os.path.exists(p):
            return p
    raise FileNotFoundError("corpus.db not found")


def connect():
    return sqlite3.connect(f"file:{corpus_db()}?mode=ro", uri=True)


def family(name):
    """Design family: all width/dialect variants of one construct share a split."""
    return re.sub(r"_(sv|v95|vnd|vnd_[a-z0-9]+)_\d+$", "", name) if name.startswith("c_") else name


def split_of(name):
    """Deterministic family-level half: A or B."""
    import zlib
    return "AB"[zlib.crc32(family(name).encode()) & 1]


# ---- routing -----------------------------------------------------------------------------------

_LABEL_RE = re.compile(r"Label_([A-Z0-9_]+):X(\d+)Y(\d+)S(\d+)I(\d+)")


def load_rcf(conn, bid):
    """RCF net trees -> {net: [(parent_elem|None, elem)]} edges; elem = (TYPE, x, y, n, idx)."""
    rows = conn.execute("select net, branch, parent_label, hop, kind, element, x, y, n, idx from rcf_routes "
                        "where build=? order by net, branch, hop", (bid,)).fetchall()
    nets = collections.defaultdict(lambda: collections.defaultdict(list))
    plabel = {}
    for net, br, pl, hop, kind, el, x, y, n, idx in rows:
        if kind in ("elem", "label"):
            nets[net][br].append((el, x, y, n, idx))
        if pl and br not in plabel.setdefault(net, {}):
            plabel[net][br] = pl
    out = {}
    for net, brs in nets.items():
        edges = []
        for br, els in brs.items():
            pl = plabel.get(net, {}).get(br)
            if pl and els:
                m = _LABEL_RE.match(pl)
                if m:
                    edges.append(((m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))), els[0]))
            for a, b in zip(els, els[1:]):
                edges.append((a, b))
        out[net] = edges
    return out


def learn_type_map(samples, min_support=15, min_frac=0.9, max_runner_up=0.5):
    """samples: list of (stat {el: Counter(native types)}, total Counter, coords {el: set((x,y,idx))}).
    Returns {rcf type: native type}. Two RCF types chained back to back at one coordinate are
    different stages of one chain (not 1:1 nodes): both are dropped."""
    stat = collections.defaultdict(collections.Counter)
    tot = collections.Counter()
    coords = collections.defaultdict(set)
    chained = set()
    for st, tt, cc in samples:
        chained |= cc.get("__chained__", set())
        for el, c in st.items():
            stat[el].update(c)
        tot.update(tt)
        for el, cs in cc.items():
            if el != "__chained__":
                coords[el] |= cs
    tmap = {}
    for el, c in stat.items():
        if tot[el] < min_support:
            continue
        ranked = c.most_common(2)
        top = ranked[0][1] / tot[el]
        run = ranked[1][1] / tot[el] if len(ranked) > 1 else 0.0
        if top >= min_frac and run <= max_runner_up:
            tmap[el] = ranked[0][0]
    byn = collections.defaultdict(list)
    for el, n in tmap.items():
        byn[n].append(el)
    for n, els in byn.items():
        for i, a in enumerate(els):
            for b in els[i + 1:]:
                if (a, b) in chained or (b, a) in chained:
                    tmap.pop(a, None)
                    tmap.pop(b, None)
    return tmap


def type_stats(model, tb, rcf_rows, links):
    """Per-design evidence for learn_type_map: RCF element (type,x,y,idx) vs native endpoint nodes at (x,y,z)."""
    tn = tb["routes"]["type_names"]
    ends = collections.defaultdict(set)
    for s, d in links:
        for k in (s, d):
            ends[((k >> 17) & 0x7F, (k >> 10) & 0x7F, k & 0x3FF)].add(tn[k >> 24])
    st = collections.defaultdict(collections.Counter)
    tot = collections.Counter()
    cc = collections.defaultdict(set)
    seen = set()
    for edges in rcf_rows.values():
        for e in edges:
            if e[0][4] is not None and e[0][1:3] == e[1][1:3] and e[0][4] == e[1][4] and e[0][0] != e[1][0]:
                cc["__chained__"].add((e[0][0], e[1][0]))
            for el, x, y, n, idx in e:
                if idx is None or (el, x, y, idx) in seen:
                    continue
                seen.add((el, x, y, idx))
                cc[el].add((x, y, idx))
                tot[el] += 1
                for N in ends.get((x, y, idx), ()):
                    st[el][N] += 1
    return st, tot, cc


def score_routes(tb, tmap, rcf, links):
    """Per-pip (RCF tree edge) and per-net scoring of native links. Returns counters + detail lists."""
    tid = {n: i for i, n in enumerate(tb["routes"]["type_names"])}
    tn = tb["routes"]["type_names"]

    def key(el):
        t, x, y, n, idx = el
        nt_ = tmap.get(t)
        if nt_ is None or idx is None or nt_ not in tid or idx > 1023:
            return None
        return nt.rkey(tid[nt_], x, y, idx)

    mapped_types = {tid[v] for v in tmap.values() if v in tid}
    native_by_dest = collections.defaultdict(set)
    for s, d in links:
        native_by_dest[d].add(s)
    c = collections.Counter()
    detail = {"missing": [], "wrong": [], "extra": []}
    rcf_dests = set()
    covered = {key(e) for edges in rcf.values() for ab in edges for e in ab if key(e) is not None}
    net_ok = 0
    nets_scored = 0
    for net, edges in rcf.items():
        nok, nscored = True, False
        by_dest = collections.defaultdict(set)
        for a, b in edges:
            ka, kb = key(a), key(b)
            if ka is None or kb is None:
                c["unmapped_edge"] += 1
                for e in (a, b):
                    if key(e) is None:
                        c["unmapped_type:" + e[0]] += 1
                continue
            by_dest[kb].add(ka)
        for d, preds in by_dest.items():
            rcf_dests.add(d)
            nat = native_by_dest.get(d, set())
            nscored = True
            if preds == nat:
                c["matched"] += len(preds)
            elif not nat:
                c["missing"] += len(preds)
                nok = False
                detail["missing"].append((net, d, sorted(preds)))
            elif preds & nat:
                c["matched"] += len(preds & nat)
                c["wrong"] += 1
                nok = False
                detail["wrong"].append((net, d, sorted(preds), sorted(nat)))
            else:
                c["wrong"] += 1
                nok = False
                detail["wrong"].append((net, d, sorted(preds), sorted(nat)))
        if nscored:
            nets_scored += 1
            net_ok += nok
    for d, srcs in native_by_dest.items():
        if d in rcf_dests:
            continue
        if (d >> 24) in mapped_types and all((s >> 24) in mapped_types and s in covered for s in srcs):
            c["extra"] += len(srcs)
            detail["extra"].append((d, sorted(srcs)))
        else:
            c["native_unmapped"] += len(srcs)
    c["nets_scored"], c["nets_ok"] = nets_scored, net_ok
    return c, detail


def headline(c):
    tot = c["matched"] + c["missing"] + c["extra"] + c["wrong"]
    return (c["matched"] / tot) if tot else float("nan")
