"""P2 clean tracer: rbf -> programmed routing edges, nets, LUT INIT cells, IO site kinds.  Vendor-derived inputs only (#165).

Edge <-> group (A1, A2): group k of source record r == fan-out edge k of r; the last (groups - edges) groups of a record are
select-bit pseudo-groups with no edge (scripts/cycloneiv_ddb_blockmap.py `group_edges`, 14,862,095 real groups).
Programmed rule (asm.ddb flag rule, docs/cycloneiv-ddb-format.md): entry is expected 1 iff b0 == +1 (select) or b1 == -1;
an edge is programmed iff it has >= 1 expected-1 entry, every expected-1 entry resolves inside the die and is set in the plane.
Variant `exact` (exclusion bits): additionally every other entry of the group (b0 in {-1, 0}, b1 != -1) is clear.
Anything unresolved (address outside the die, no expected-1 entry, name not exactly one record) is missing, never guessed.
"""
import collections
import concurrent.futures as cf
import os
import re

import numpy as np

from . import ddb
from . import plane as P

# source: A4 / A6 (plane.N_BITS): cell index = r * 6344 + (j - 1) * 8 + k; sentinel N_BITS = "no cell" (reads 0)
SENTINEL = P.N_BITS
CACHE = os.path.join(P.REPO, "tmp", "cycloneiv_clean", "tracer_static.npz")
CHUNK_EDGES = 1_000_000          # edges per numpy block: ~3.5 M entries, ~60 MB of temporaries per worker
ENUM_BITS = 21                   # record ids < 2^21 (1,802,443 records)


def _build_static(die=ddb.DIE):
    import sys
    sys.path.insert(0, ddb.SCRIPTS)
    import cycloneiv_ddb_asm as A
    rt, a = ddb.Routing(die), A.load(die)
    n = np.asarray(a["n"])
    gsize, grec, gstart = A.group_sizes({k: np.asarray(v) for k, v in a.items()})
    cnt = np.where((rt.tpl >= 0) & (rt.first_dest != 0), rt.cnt[np.maximum(rt.tpl, 0)], 0).astype(np.int64)
    ng = np.bincount(grec, minlength=rt.n)
    if (ng < cnt).any():
        raise SystemExit("records with fewer asm groups than graph edges")
    gfirst = np.concatenate([[0], np.cumsum(ng)[:-1]])
    k = np.arange(len(grec), dtype=np.int64) - gfirst[grec]
    real = k < cnt[grec]
    gi = np.flatnonzero(real)
    r, kk = grec[gi].astype(np.int64), k[gi]
    t = rt.tpl[r]
    dst = rt.first_dest[r].astype(np.int64) + rt.offs[rt.eoff[t].astype(np.int64) + kk].astype(np.int64)
    size = gsize[gi].astype(np.int64)
    estart = np.concatenate([[0], np.cumsum(size)])
    # entries of the real groups, in group order
    ent = np.repeat(real, gsize)
    pos, flag = np.asarray(a["pos"]), np.asarray(a["flag"])
    addr = pos[ent] & ddb.ADDR_MASK
    f = flag[ent].astype(np.int64)
    b0, b1 = ((f & 0xFF) ^ 0x80) - 0x80, (((f >> 8) & 0xFF) ^ 0x80) - 0x80
    lit = (b0 == 1) | (b1 == -1)
    first = np.zeros(len(addr), bool)
    first[estart[:-1][size > 0]] = True
    kind = lit.astype(np.uint8) | (first.astype(np.uint8) << 1)
    tab = P.load_tables()
    cell = np.full(len(addr), SENTINEL, np.int64)
    inside = (addr >= 0) & (addr < P.N_BITS)
    for lo in range(0, len(addr), 8_000_000):
        sl = slice(lo, lo + 8_000_000)
        m = inside[sl]
        rr, jj, kk2 = P.sof_to_rbf(addr[sl][m], tab)
        c = np.full(len(m), SENTINEL, np.int64)
        c[m] = rr * P.BITS_PER_FRAME + (jj - 1) * P.LANES + kk2
        cell[sl] = c
    nlit = np.add.reduceat(lit.astype(np.int32), np.minimum(estart[:-1], len(lit) - 1))
    nlit = np.where(size > 0, nlit, 0)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    np.savez(CACHE, esrc=r.astype(np.int32), edst=dst.astype(np.int32), estart=estart, cell=cell.astype(np.uint32),
             kind=kind, nlit=nlit.astype(np.int16), size=size.astype(np.int16), group_index=gi.astype(np.int64))
    return dict(groups=len(grec), real=len(gi), entries=len(addr), outside_die=int((~inside).sum()))


class Static:
    """Design-independent edge table: esrc / edst per real edge, entry ranges, entry cell index and expected value."""

    def __init__(self, path=CACHE):
        if not os.path.exists(path):
            _build_static()
        z = np.load(path)
        self.esrc, self.edst, self.estart = z["esrc"], z["edst"], z["estart"]
        self.cell, self.kind, self.nlit, self.size = z["cell"], z["kind"], z["nlit"], z["size"]
        self.n_edges = len(self.esrc)
        self._key = None

    def edge_ids(self, src, dst):
        """Edge index of each (src, dst) record pair (first match), -1 where the graph has no such edge."""
        if self._key is None:
            key = self.esrc.astype(np.int64) << ENUM_BITS | self.edst
            order = np.argsort(key, kind="stable")
            self._key = (key[order], order)
        sk, order = self._key
        q = np.asarray(src, np.int64) << ENUM_BITS | np.asarray(dst, np.int64)
        i = np.minimum(np.searchsorted(sk, q), len(sk) - 1)
        return np.where(sk[i] == q, order[i], -1)

    def _block(self, bits, a, b):
        e0, e1 = int(self.estart[a]), int(self.estart[b])
        v = bits[self.cell[e0:e1]]
        k = self.kind[e0:e1]
        off = self.estart[a:b + 1] - e0
        out = []
        for pr in ((k & 1) == 1, (k & 3) != 0):          # literal flag rule, flag rule + first entry = select
            for bad in (pr & (v == 0), ~pr & (v == 1)):      # expected-1 entry clear (miss), other entry set (exclusion)
                c = np.concatenate([[0], np.cumsum(bad, dtype=np.int32)])
                out.append(c[off[1:]] - c[off[:-1]])
        return out

    def fire(self, bits, workers=4):
        """bits: uint8 [N_BITS + 1] plane (last = sentinel 0).  -> {variant: programmed edge ids}.
        lit / lit_x: literal flag rule (b0 == +1 or b1 == -1), set-only / with exclusion bits clear.
        sel / sel_x: the same with the group's first entry (select) always expected 1.  Headline variant: sel_x."""
        blocks = [(a, min(a + CHUNK_EDGES, self.n_edges)) for a in range(0, self.n_edges, CHUNK_EDGES)]
        with cf.ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(lambda ab: self._block(bits, *ab), blocks))
        m = [np.concatenate([r[i] for r in res]) for i in range(4)]
        has = self.size > 0
        return {"lit": np.flatnonzero((self.nlit > 0) & (m[0] == 0)),
                "lit_x": np.flatnonzero((self.nlit > 0) & (m[0] == 0) & (m[1] == 0)),
                "sel": np.flatnonzero(has & (m[2] == 0)),
                "sel_x": np.flatnonzero(has & (m[2] == 0) & (m[3] == 0))}


def plane_bits(rbf):
    """uint8 [N_BITS + 1] of an rbf CRAM, index r * 6344 + (j - 1) * 8 + k; sentinel last."""
    from . import sofio
    out = np.zeros(P.N_BITS + 1, np.uint8)
    out[:P.N_BITS] = sofio.rbf_cram(rbf).reshape(-1)
    return out


# ---- RCF ground-truth tree (Quartus routing.rcf) and name -> record -----------------------------------------------------------------

NAME = re.compile(r"^([A-Z][A-Z0-9_]*):X(\d+)Y(\d+)S(\d+)I(\d+)$")
LABEL = re.compile(r"^label = (\S+), (\S+);$")
BRANCH = re.compile(r"^branch_point = (\S+);$")
DEST = re.compile(r"^dest = \( (\S+), (\S+) \)(?:, route_port = (\S+))?;$")


def _tup(s):
    m = NAME.match(s)
    return (m[1], int(m[2]), int(m[3]), int(m[4]), int(m[5])) if m else None


def parse_rcf(path):
    """-> list of nets {name, roots [name tuple], edges [(parent, child)], dests [(last element, cell, port, route_port)]}."""
    nets, cur, alias, prev = [], None, {}, None
    for line in open(path):
        s = line.strip()
        if s.startswith("signal_name"):
            cur = dict(name=s.split("=")[1].split("{")[0].strip(), roots=[], edges=[], dests=[])
            nets.append(cur)
            alias, prev = {}, None
            continue
        if cur is None or not s or s == "}":
            continue
        m = LABEL.match(s)
        if m:
            alias[m[1]] = _tup(m[2])
            el = alias[m[1]]
        elif BRANCH.match(s):
            prev = alias.get(BRANCH.match(s)[1])
            continue
        elif DEST.match(s):
            d = DEST.match(s)
            cur["dests"].append((prev, d[1], d[2], d[3]))
            prev = None
            continue
        else:
            el = _tup(s.rstrip(";"))
        if el is None:
            continue
        if prev is None:
            cur["roots"].append(el)
        else:
            cur["edges"].append((prev, el))
        prev = el
    return nets


class Resolver:
    """A7: (type, x, y, z, index) -> record id by exact key.  reason: ok / unmapped_type / absent / ambiguous."""

    def __init__(self, rt=None):
        from . import names
        self.names = names
        self.rt = rt or ddb.Routing()
        keys = self.rt.element_keys()
        self.order = np.argsort(keys, kind="stable")
        self.sorted = keys[self.order]

    def resolve(self, name_tuples):
        n = len(name_tuples)
        rec = np.full(n, -1, np.int64)
        why = np.empty(n, object)
        q, idx = [], []
        for i, t in enumerate(name_tuples):
            try:
                q.append(self.names.key_of(t))
                idx.append(i)
            except self.names.UnmappedType:
                why[i] = "unmapped_type"
        if q:
            q = np.array(q, np.int64)
            lo, hi = np.searchsorted(self.sorted, q, "left"), np.searchsorted(self.sorted, q, "right")
            for j, i in enumerate(idx):
                c = hi[j] - lo[j]
                if c == 1:
                    rec[i], why[i] = int(self.order[lo[j]]), "ok"
                else:
                    why[i] = "absent" if c == 0 else "ambiguous"
        return rec, why


# ---- tracing ------------------------------------------------------------------------------------------------------------

class Graph:
    """Programmed edges as a forward adjacency (CSR over record ids)."""

    def __init__(self, st, edge_ids):
        s, d = st.esrc[edge_ids].astype(np.int64), st.edst[edge_ids].astype(np.int64)
        o = np.argsort(s, kind="stable")
        self.src, self.dst, self.eid = s[o], d[o], np.asarray(edge_ids)[o]
        self.uniq, self.first = np.unique(self.src, return_index=True)
        self.last = np.append(self.first[1:], len(self.src))
        self.pos = {int(u): i for i, u in enumerate(self.uniq)}
        self.has_parent = set(np.unique(self.dst).tolist())

    def roots(self):
        return [int(u) for u in self.uniq if int(u) not in self.has_parent]

    def reach(self, starts):
        """Edge indices (into st) reachable from the start records through programmed edges."""
        seen_n, out, stack = set(), [], [int(x) for x in starts]
        while stack:
            r = stack.pop()
            i = self.pos.get(r)
            if i is None or r in seen_n:
                continue
            seen_n.add(r)
            a, b = self.first[i], self.last[i]
            out.extend(self.eid[a:b].tolist())
            stack.extend(self.dst[a:b].tolist())
        return out


def tracer_nets(g):
    """{root record: sorted programmed edge ids reachable}: one net per programmed-edge root (no programmed parent)."""
    return {r: sorted(g.reach([r])) for r in g.roots()}


# ---- LUT INIT cells (A3 via fields.py) and IO sites (io_decode value table) ----------------------------------------------------------

class Lut:
    """LE_LUT_FUNCTION cells: cell index [9360 LABs, 16 LEs, 16 mux bits]; LAB index = column rank (ascending X) * 90 + Y - 1."""

    def __init__(self, walk=None):
        import json
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        from . import asmdb_walk as W
        from . import fields as F
        w = walk or W.Walk()
        g = next(f for f in F.fields(w, D.enum_tables(), block_types={18}) if f.name == "LE_LUT_FUNCTION")
        bs = F.bases(w, 18)
        addr = np.stack([F.absolute(bs, g.sites[le][0]) for le in range(16)], axis=1)
        r, j, k = P.sof_to_rbf(addr.ravel(), P.load_tables())
        self.cell = (r * P.BITS_PER_FRAME + (j - 1) * P.LANES + k).reshape(addr.shape)
        labs = json.load(open(os.path.join(P.REPO, "lifters", "data", "cycloneiv_ep4cgx150_labs.json")))["labs"]
        self.xs = sorted({x for x, _ in labs})
        self.col = {x: i for i, x in enumerate(self.xs)}
        self.walk = w

    def cells(self, bits):
        return bits[self.cell]

    def lab(self, x, y):
        c = self.col.get(x)
        return -1 if c is None or not 1 <= y <= 90 else c * 90 + y - 1


# source: io_decode.json `values` rows with setting 'default' (pair builds, docs/cycloneiv-clean-io.md): pattern of each group per base kind
IO_KEY_GROUPS = ("MIO_SET_PULLDOWN_STRENGTH", "MIO_SET_PULLUP_STRENGTH", "MIO_SET_SLEW_RATE", "MIO_USE_PCI_DIODE_CLAMP")


class Io:
    """IO site -> default-pattern class from the CFF bits (read from the rbf).  A site whose four key groups match no decoded
    default pattern is reported unclassified (not used / unknown), never guessed."""

    def __init__(self, chain=None):
        import json
        from . import io as IO
        from . import io_decode as ID
        self.chain = chain or ID.Chain()
        self.cff = IO.Cff()
        t = json.load(open(ID.DECODE_PATH))
        pat = collections.defaultdict(dict)
        for v in t["values"]:
            if v["setting"] == "default" and v["group"] in IO_KEY_GROUPS:
                pat[v["base_kind"]][v["group"]] = v["pattern"]
        self.classes = collections.defaultdict(set)         # key tuple -> base kinds sharing it
        for kind, d in pat.items():
            if all(g in d for g in IO_KEY_GROUPS):
                self.classes[tuple(d[g] for g in IO_KEY_GROUPS)].add(kind)
        self.site_ball = {s: b for b, s in self.chain.ball_site.items() if s}

    def classify(self, rbf):
        """{(block type, site): frozenset of base kinds} for every IO site whose key groups equal a decoded default pattern."""
        val, _ = self.cff.read(rbf)
        out = {}
        for site, grp in self.chain.cff.items():
            if not all(g in grp for g in IO_KEY_GROUPS):
                continue
            key = tuple("".join(str(int(val[a])) for a in grp[g]) for g in IO_KEY_GROUPS)
            if key in self.classes:
                out[site] = frozenset(self.classes[key])
        return out
