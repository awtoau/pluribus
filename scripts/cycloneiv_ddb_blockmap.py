#!/usr/bin/env python3.15t
"""Exact asm group <-> routing.ddb graph-edge correspondence and block -> output-wire map (#141).

Correspondence: group k of source record r (asm order) == fan-out edge k of r (template order);
dest = V(r) + offs[k].  The last (ng - ne) groups of a record are select-bit pseudo-groups
(no edge).  A block (mux) must map to ONE destination wire: that is the self-check.

  python3.15t scripts/cycloneiv_ddb_blockmap.py build      # -> tmp/ddb/<die>_blockmap.npz + report
  python3.15t scripts/cycloneiv_ddb_blockmap.py specimens  # agreement with the exact specimen entries
  python3.15t scripts/cycloneiv_ddb_blockmap.py export     # -> lifters/data/cycloneiv_ep4cgx150_ddb_map.npz
Log tmp/logs/cycloneiv_ddb_blockmap.log.
"""
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_ddb_asm as A  # noqa: E402

log = logging.getLogger("cycloneiv_ddb_blockmap")
DIE = "stingray4"
T = os.path.join(A.TMP, f"{DIE}_dec_")


def group_edges():
    """-> dict of per-group arrays: grec, k (index within record), real (has edge), dest (-1 if pseudo)."""
    grec = np.load(T + "grec.npy")
    z = np.load(os.path.join(A.TMP, f"{DIE}_rt_fanout.npz"))
    V, tpl, cnt, eoff, offs = z["V"].astype(np.int64), z["tpl"], z["cnt"], z["eoff"], z["offs"].astype(np.int64)
    n = len(V)
    ng = np.bincount(grec, minlength=n)
    gfirst = np.concatenate([[0], np.cumsum(ng)[:-1]])
    k = np.arange(len(grec)) - gfirst[grec]
    ne = cnt[tpl].astype(np.int64)
    if (ng < ne).any():
        raise SystemExit(f"{int((ng < ne).sum())} records with fewer asm groups than graph edges")
    real = k < ne[grec]
    pick = np.minimum(eoff[tpl[grec]] + k, len(offs) - 1)
    dest = np.where(real, V[grec] + offs[pick], -1)
    return dict(grec=grec, k=k, real=real, dest=dest, ng=ng, ne=ne, n=n)


def build():
    ge = group_edges()
    block = np.load(T + "block.npy")
    gsize = np.load(T + "gsize.npy")
    real, dest = ge["real"], ge["dest"]
    bi = np.flatnonzero(real)
    b, d = block[bi], dest[bi]
    o = np.argsort(b, kind="stable")
    b, d, bi = b[o], d[o], bi[o]
    st = np.flatnonzero(np.r_[True, b[1:] != b[:-1]])
    en = np.r_[st[1:], len(b)]
    dmin = np.minimum.reduceat(d, st)
    dmax = np.maximum.reduceat(d, st)
    nb = len(st)
    one = dmin == dmax
    log.info("real groups %d / %d (pseudo %d); blocks with >=1 real group %d; single-destination blocks %d (%.4f%%)",
             int(real.sum()), len(real), int((~real).sum()), nb, int(one.sum()), 100.0 * one.sum() / nb)
    # multi-destination blocks: distinct dest count histogram + by source record family
    multi = np.flatnonzero(~one)
    hist = collections.Counter()
    for i in multi[:200000].tolist():
        hist[len(np.unique(d[st[i]:en[i]]))] += 1
    log.info("multi-destination blocks %d; distinct-dest histogram (first 200k) %s", len(multi), dict(hist))
    # block -> dest (single) and the sources feeding it
    out = os.path.join(A.TMP, f"{DIE}_blockmap.npz")
    np.savez(out, block=b[st], dest=dmin, single=one, gfirst=st, gend=en, gidx=bi, gdest=d)
    log.info("wrote %s", out)


XMIRROR = 115


class Pairs:
    """(block, dest record) pairs of every real group, plus the Phys block/record geometry."""

    def __init__(self, P=None):
        import cycloneiv_phys_trace as PT
        self.P = P if P is not None else PT.Phys(need_map=False)
        ge = group_edges()
        self.ge = ge
        block = self.P.dec.block
        real = ge["real"]
        self.N = ge["n"]
        key = np.unique(block[real].astype(np.int64) * self.N + ge["dest"][real])
        self.pairs = key                       # sorted unique b * N + d (the exact units)
        z = np.load(os.path.join(A.TMP, f"{DIE}_rt_fanout.npz"))
        tpl = z["tpl"]
        self.enum = z["enum"][tpl]
        self.index = z["index"][tpl]

    def has(self, b, d):
        k = np.asarray(b, np.int64) * self.N + np.asarray(d, np.int64)
        i = np.searchsorted(self.pairs, k)
        return (i < len(self.pairs)) & (self.pairs[np.minimum(i, len(self.pairs) - 1)] == k)

    def dests(self, b):
        lo = np.searchsorted(self.pairs, b * self.N)
        hi = np.searchsorted(self.pairs, (b + 1) * self.N)
        return self.pairs[lo:hi] - b * self.N


def specimens():
    """Compare the ddb block -> dest pairs with the exact specimen entries (provenance 'specimen').
    Class entries apply to every block of (tile class, key); tile entries to one block.
    Output unit = one specimen output.  matched: output in the block's ddb dest set; wrong: block has
    dests but not this one; missing: block has no real group; extra: ddb dests of the block beyond the
    specimen list (specimen lists are observation-limited, so extra is an upper bound on real faults)."""
    import json
    import cycloneiv_phys_trace as PT
    Q = Pairs()
    P = Q.P
    e = json.load(open(os.path.join(REPO, "tmp", "cycloneiv", "specimens", "exact.json")))
    cls_of = PT.tile_class(P.btx.astype(np.int64), P.bty.astype(np.int64), 8, 4)
    tot = collections.defaultdict(collections.Counter)
    bad = collections.defaultdict(list)

    def judge(kind, b, outs, ctx):
        ds = Q.dests(b)
        used = set()
        for o in outs:
            tx, ty = int(P.btx[b]), int(P.bty[b])
            if kind == "wire":
                fam, dvx, dvy = o
                r = P.rec_of(fam, XMIRROR - tx + dvx, ty + dvy)
                want = {r} if r >= 0 else set()
            else:
                dy, i = o
                want = {int(d) for d in ds if Q.enum[d] == 282 and P.vx[d] == XMIRROR - tx
                        and P.vy[d] == ty + dy and Q.index[d] == i}
            if want & set(ds.tolist()):
                tot[kind]["matched"] += 1
                used |= want
            elif len(ds) == 0:
                tot[kind]["missing"] += 1
                bad[kind].append(("missing", ctx, o, int(b)))
            else:
                tot[kind]["wrong"] += 1
                bad[kind].append(("wrong", ctx, o, [(int(P.fam[d]), int(Q.enum[d]), int(Q.index[d]),
                                                      int(P.vx[d]) - (XMIRROR - tx), int(P.vy[d]) - ty) for d in ds[:3]]))
        tot[kind]["extra"] += len([d for d in ds.tolist() if d not in used])

    for kind, ck, tk in (("wire", "wires", "wires_tile"), ("li", "lis", "lis_tile")):
        for k, v in e[tk].items():
            tile, key = k.split("|", 1)
            tx, ty = map(int, tile.split(","))
            b = P.block_at(tx, ty, P.key_id[key])
            if b < 0:
                tot[kind]["missing"] += len(v["val"])
                bad[kind].append(("no block", k, v["val"], -1))
                continue
            judge(kind, b, v["val"], f"tile {k}")
        for k, v in e[ck].items():
            cls, key = k.split("|", 1)
            kid = P.key_id.get(key)
            if kid is None:
                continue
            for b in np.flatnonzero((cls_of == int(cls)) & (P.bkey == kid)).tolist():
                judge(kind, b, v["val"], f"class {k}")
    for kind, c in tot.items():
        den = sum(c.values())
        log.info("specimens %-4s matched %d / (matched %d + missing %d + extra %d + wrong %d) = %.3f%%", kind,
                 c["matched"], c["matched"], c["missing"], c["extra"], c["wrong"], 100.0 * c["matched"] / max(den, 1))
    for kind, lst in bad.items():
        cc_ = collections.Counter((w, ctx.split()[0], str(o if kind == "li" else o)) for w, ctx, o, _ in lst)
        log.info("%s disagreements: %d (distinct %d)", kind, len(lst), len(cc_))
        for (w, c0, o), n in cc_.most_common(25):
            log.info("   %-8s %-6s out %s  x%d", w, c0, o, n)
    json.dump({k: [list(map(str, x)) for x in v[:400]] for k, v in bad.items()},
              open(os.path.join(REPO, "tmp", "cycloneiv_ddb_specimen_disagree.json"), "w"), indent=0)


if __name__ == "__main__":
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_ddb_blockmap.log"))])
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    {"build": build, "specimens": specimens}[cmd]()
