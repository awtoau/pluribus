"""P2 clean tracer: rbf -> programmed routing edges, nets, LUT INIT cells, IO site kinds.  Vendor-derived inputs only (#165).

Edge <-> group (A1, A2): group k of source record r == fan-out edge k of r; the last (groups - edges) groups of a record are
its EXCLUSION groups (dst-side), not edges.
Conduction rule (source: libddb_dygr DYGR_ROUTE_ASM_INFO_BODY::get_bits_from_source_to_dest + check_routing_connection, static decompile):
  - entry value: use_encoded flag F0 clear -> bit must be 1 (one-hot select); F0 set -> bit must equal F1 (encoded_high).
  - F0 / F1 are 1-bit fields serialized as i8 deltas vs the previous bit (DYGR_ROUTE_ASM_BIT::operator<<): the on-disk b0 / b1 bytes are
    deltas, F = (running sum over all entries) & 1.
  - every bit of the DESTINATION's exclusion groups that is not in the source's list must be 0.
An edge needs >= 1 entry that must be 1 (an all-zero pattern is not distinguishable from an unused mux: ambiguous = missing).
Anything unresolved (address outside the die, name not exactly one record) is missing, never guessed.
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
    pos, flag = np.asarray(a["pos"]), np.asarray(a["flag"])
    # F0 (use-encoded) / F1 (encoded-high): running sum of the i8 deltas over all entries, masked to the 1-bit field width
    f = flag.astype(np.int64)
    b0, b1 = ((f & 0xFF) ^ 0x80) - 0x80, (((f >> 8) & 0xFF) ^ 0x80) - 0x80
    f0, f1 = np.cumsum(b0) & 1, np.cumsum(b1) & 1
    want_all = np.where(f0 == 1, f1, 1).astype(np.uint8)
    del f, b0, b1, f0, f1
    ent = np.repeat(real, gsize)
    addr = pos[ent] & ddb.ADDR_MASK
    want = want_all[ent]
    # exclusion entries: groups of the record beyond its edges, keyed (record, address)
    xent = np.repeat(~real, gsize)
    xrec = np.repeat(grec, gsize)[xent].astype(np.int64)
    xaddr = pos[xent] & ddb.ADDR_MASK
    xkey = np.unique(xrec << 31 | xaddr)
    erec = np.repeat(dst, size)                                   # destination record of each list entry
    inx = np.zeros(len(addr), bool)
    for lo in range(0, len(addr), 8_000_000):
        sl = slice(lo, lo + 8_000_000)
        q = erec[sl] << 31 | addr[sl]
        i = np.minimum(np.searchsorted(xkey, q), len(xkey) - 1)
        inx[sl] = xkey[i] == q
    del erec
    tab = P.load_tables()

    def cells(ad):
        c = np.full(len(ad), SENTINEL, np.int64)
        for lo in range(0, len(ad), 8_000_000):
            sl = slice(lo, lo + 8_000_000)
            m = (ad[sl] >= 0) & (ad[sl] < P.N_BITS)
            rr, jj, kk2 = P.sof_to_rbf(ad[sl][m], tab)
            cc = np.full(len(m), SENTINEL, np.int64)
            cc[m] = rr * P.BITS_PER_FRAME + (jj - 1) * P.LANES + kk2
            c[sl] = cc
        return c
    cell = cells(addr)
    xcell = cells(xkey & ddb.ADDR_MASK)
    xr = (xkey >> 31).astype(np.int32)
    flagbits = want | (inx.astype(np.uint8) << 1)               # bit0 = required value, bit1 = also in the destination's exclusion set
    nreq1 = np.add.reduceat(want.astype(np.int32), np.minimum(estart[:-1], len(want) - 1))
    nreq1 = np.where(size > 0, nreq1, 0)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    np.savez(CACHE, esrc=r.astype(np.int32), edst=dst.astype(np.int32), estart=estart, cell=cell.astype(np.uint32),
             kind=flagbits, nlit=nreq1.astype(np.int16), size=size.astype(np.int16), group_index=gi.astype(np.int64),
             xcell=xcell.astype(np.uint32), xrec=xr)
    return dict(groups=len(grec), real=len(gi), entries=len(addr), exclusion_entries=len(xkey), list_entries_in_exclusion=int(inx.sum()))


class Static:
    """Design-independent edge table: esrc / edst per real edge, entry ranges, entry cell index, required value, exclusion cells per record.
    kind bit0 = required value of the entry, bit1 = entry address is also an exclusion bit of the destination; nlit = entries that must be 1."""

    def __init__(self, path=CACHE):
        if not os.path.exists(path):
            _build_static()
        z = np.load(path)
        self.esrc, self.edst, self.estart = z["esrc"], z["edst"], z["estart"]
        self.cell, self.kind, self.nlit, self.size = z["cell"], z["kind"], z["nlit"], z["size"]
        self.xcell, self.xrec = z["xcell"], z["xrec"]
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

    def _block(self, bits, a, b, xset):
        e0, e1 = int(self.estart[a]), int(self.estart[b])
        v = bits[self.cell[e0:e1]]
        k = self.kind[e0:e1]
        off = self.estart[a:b + 1] - e0
        miss = v != (k & 1)                                          # list entry differs from its required value
        c = np.concatenate([[0], np.cumsum(miss, dtype=np.int32)])
        bad_list = c[off[1:]] - c[off[:-1]]
        inx = ((k & 2) != 0) & (v == 1)                              # set exclusion bits that belong to the list itself
        c = np.concatenate([[0], np.cumsum(inx, dtype=np.int32)])
        own = c[off[1:]] - c[off[:-1]]
        bad_x = xset[self.edst[a:b]] - own                           # set bits of the destination's exclusion groups outside the list
        return bad_list, bad_x

    def fire(self, bits, workers=4):
        """bits: uint8 [N_BITS + 1] plane (last = sentinel 0).  -> {variant: programmed edge ids}.
        vendor: list entries equal their required value and the destination's other exclusion bits are clear.
        vendor_nx: list entries only (exclusion bits ignored)."""
        xset = np.bincount(self.xrec, weights=bits[self.xcell], minlength=int(self.edst.max()) + 1).astype(np.int32)
        blocks = [(a, min(a + CHUNK_EDGES, self.n_edges)) for a in range(0, self.n_edges, CHUNK_EDGES)]
        with cf.ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(lambda ab: self._block(bits, *ab, xset), blocks))
        bl = np.concatenate([r[0] for r in res])
        bx = np.concatenate([r[1] for r in res])
        has = (self.size > 0) & (self.nlit > 0)
        return {"vendor_nx": np.flatnonzero(has & (bl == 0)), "vendor": np.flatnonzero(has & (bl == 0) & (bx == 0))}


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
        gc = next(f for f in F.fields(w, D.enum_tables(), block_types={18}) if f.name == "LE_USE_CARRY")
        ac = np.stack([F.absolute(bs, gc.sites[le][0])[:, 0] for le in range(16)], axis=1)
        r, j, k = P.sof_to_rbf(ac.ravel(), P.load_tables())
        self.carry_cell = (r * P.BITS_PER_FRAME + (j - 1) * P.LANES + k).reshape(ac.shape)      # [labs, 16], one cell per LE
        labs = json.load(open(os.path.join(P.REPO, "lifters", "data", "cycloneiv_ep4cgx150_labs.json")))["labs"]
        self.xs = sorted({x for x, _ in labs})
        self.col = {x: i for i, x in enumerate(self.xs)}
        self.walk = w

    def cells(self, bits):
        return bits[self.cell]

    def carry_in(self, bits):
        """bool [labs, 16]: LE_USE_CARRY bit CLEAR = the LUT's C input comes from the carry chain (sum_lutc_input = cin)."""
        return bits[self.carry_cell] == 0

    def lab(self, x, y):
        c = self.col.get(x)
        return -1 if c is None or not 1 <= y <= 90 else c * 90 + y - 1


class Extras:
    """Decoders that add programmed edges outside the flag rule: clock network (clocks.py) and LOCAL_INTERCONNECT -> LAB_CONTROL_MUX
    (lab_control.py, edges absent from the routing graph: ids >= st.n_edges, appended to st.esrc / st.edst)."""

    def __init__(self, st, lut, rt=None):
        from . import bim, clocks, lab_control, reg_used
        if len(st.esrc) != st.n_edges:
            raise SystemExit("Static already extended")
        self.st = st
        self.clocks = clocks.Clocks(st, lut, rt)
        self.imp = lab_control.Implicit(lut, rt, n_real=st.n_edges)
        self.reg = reg_used.RegUsed(lut, st, rt)
        st.esrc = np.concatenate([st.esrc, self.imp.esrc])
        st.edst = np.concatenate([st.edst, self.imp.edst])
        self.bim = bim.Implicit(rt, n_real=len(st.esrc))
        st.esrc = np.concatenate([st.esrc, self.bim.esrc])
        st.edst = np.concatenate([st.edst, self.bim.edst])
        from . import m9k_pia
        self.pia = m9k_pia.Implicit(lut.walk, rt or ddb.Routing(), n_real=len(st.esrc))
        st.esrc = np.concatenate([st.esrc, self.pia.esrc])
        st.edst = np.concatenate([st.edst, self.pia.edst])
        st._key = None
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        from . import clkbuf
        self.clkbuf = clkbuf.ClkbufIn(st, rt or ddb.Routing(), self.bim, lut.walk, D.enum_tables()["arch_group_type"])

    def apply(self, bits, fired):
        """{variant: edge ids} with the clock and LAB-control edges added to every variant."""
        imp = np.concatenate([self.imp.apply(bits), self.bim.apply(bits), self.pia.apply(bits), self.clkbuf.apply(bits)])
        return {v: np.unique(np.concatenate([self.clocks.apply(bits, e), imp])) for v, e in fired.items()}


# source: io_decode.json `values` rows with setting 'default' (pair builds, docs/cycloneiv-clean-io.md): pattern of each group per base kind
IO_KEY_GROUPS = ("MIO_SET_PULLDOWN_STRENGTH", "MIO_SET_PULLUP_STRENGTH", "MIO_SET_SLEW_RATE", "MIO_USE_PCI_DIODE_CLAMP")


class Io:
    """IO site -> default-pattern class from the CFF bits (read from the rbf).  A site whose four key groups match no decoded
    default pattern is reported unclassified (not used / unknown), never guessed."""

    def __init__(self, chain=None):
        import json
        from . import cycloneiv_io as IO
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


HEADLINE_VARIANT = "vendor"     # asm.ddb conduction rule as the vendor assembler states it (module docstring)


class Tracer:
    """One design: rbf -> programmed edges (all four variants), nets (root record -> edge ids), LUT INIT cells, IO site classes."""

    def __init__(self, workers=4):
        self.st, self.lut, self.io, self.workers = Static(), Lut(), Io(), workers
        self.ext = Extras(self.st, self.lut)

    def run(self, rbf):
        bits = plane_bits(rbf)
        fired = self.ext.apply(bits, self.st.fire(bits, workers=self.workers))
        g = Graph(self.st, fired[HEADLINE_VARIANT])
        return dict(edges=fired, edge_src=self.st.esrc, edge_dst=self.st.edst, nets=tracer_nets(g),
                    lut_cells=self.lut.cells(bits), io=self.io.classify(rbf), le_clock_blk=self.ext.clocks.le_blk(bits))


def main():
    """python3.15t -m lifters.cycloneiv_clean.tracer <bitstream.rbf> <out.npz>: edges per variant, net roots, LUT cells (stdout: counts)."""
    import sys
    rbf, out = sys.argv[1], sys.argv[2]
    r = Tracer().run(rbf)
    srcdst = lambda ids: np.stack([r["edge_src"][ids], r["edge_dst"][ids]], axis=1)
    np.savez_compressed(out, lut_cells=r["lut_cells"], **{f"edges_{k}": srcdst(v) for k, v in r["edges"].items()})
    print({k: len(v) for k, v in r["edges"].items()}, "nets", len(r["nets"]), "io sites", len(r["io"]))


if __name__ == "__main__":
    main()
