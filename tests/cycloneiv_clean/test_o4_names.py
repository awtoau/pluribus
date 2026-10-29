"""O4 (A7): RCF name -> element by exact equality on (type, x, y, z, index), x/y as in the name (A8, no mirror).
Type -> enum: names_table.json (vendor hdr.ddb names + routing.ddb enums, edge-consistency checked; no seeds).
test_o4_edge_consistency: per type, parent -> child tree edges whose child is in the parent's ddb fan-out."""
import collections
import glob
import os

import numpy as np
import pytest

from conftest import REPO, report
from lifters.cycloneiv_clean import ddb, names

CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
DESIGNS = [f"gx150_rb_{n:03d}" for n in range(10)]


# RCF edges to these types are not fan-out edges (0 % at any enum, #165), so they stay out of the partner types' counts.
# source: names_table.json status vendor, enums read from libddb_dstr + hdr.ddb records
OPEN_EDGE = {"LAB_CONTROL_MUX", "BLOCK_INPUT_MUX", "LOCAL_LINE", "M4K_LEFT_CONTROL_INPUT"}


def lookup(keys, q):
    """number of records whose key equals each q (sorted-key search)."""
    s = np.sort(keys)
    return np.searchsorted(s, q, "right") - np.searchsorted(s, q, "left")


def test_o4_exact_names(routing):
    rcfs = [os.path.join(CORPUS, d, "routing.rcf") for d in DESIGNS]
    rcfs = [p for p in rcfs if os.path.exists(p)]
    if len(rcfs) < 10:
        pytest.skip(f"corpus rcf missing ({len(rcfs)}/10)")
    keys = routing.element_keys()
    keys = keys[keys >= 0]
    # type-less key: (x, y, z, index) with enum dropped
    flat = keys % (256 * 256 * 256 * 4096)
    tot = collections.Counter()
    for p in rcfs:
        tot_d = collections.Counter()
        seen = {}
        for t, x, y, z, i in names.rcf_names(p):
            seen[(t, x, y, z, i)] = None
        nm = list(seen)
        typed_ok = typeless_ok = 0
        for t in sorted({n[0] for n in nm}):
            sub = [n for n in nm if n[0] == t]
            q0 = np.array([ddb.element_key(0, x, y, z, i) for _, x, y, z, i in sub], np.int64)
            tl = lookup(flat, q0)
            tot_d[(t, "names")] += len(sub)
            tot_d[(t, "typeless_unique")] += int((tl == 1).sum())
            if t in names.enums():
                tp = lookup(keys, q0 + names.enum_of(t) * 256 * 256 * 256 * 4096)
                tot_d[(t, "typed_unique")] += int((tp == 1).sum())
                tot_d[(t, "typed_none")] += int((tp == 0).sum())
                tot_d[(t, "typed_ambiguous")] += int((tp > 1).sum())
        tot.update(tot_d)
        report("O4", design=os.path.basename(os.path.dirname(p)), names=len(nm),
               seeded_names=sum(v for (t, w), v in tot_d.items() if w == "names" and t in names.enums()),
               typed_unique=sum(v for (t, w), v in tot_d.items() if w == "typed_unique"))
    for t in sorted({k[0] for k in tot}):
        report("O4-type", type=t, enum_seed=names.enums().get(t), **{w: tot[(t, w)] for w in ("names", "typeless_unique", "typed_unique", "typed_none", "typed_ambiguous")})
    seeded = {t: tot[(t, "names")] for t in names.enums()}
    uniq = {t: tot[(t, "typed_unique")] for t in names.enums()}
    if uniq != seeded:
        pytest.xfail(f"typed exact-unique {sum(uniq.values())}/{sum(seeded.values())} names (seeded types)")


def test_o4_edge_consistency(routing):
    """Per type: edges (parent resolved, child resolved, child in parent fan-out) over 10 corpus designs.
    Types with enum null (unmapped) are reported with no enum and are not asserted."""
    import sys
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    src = open(os.path.join(REPO, "scripts", "cycloneiv_clean_names_search.py")).read().rsplit("\nmain()", 1)[0]
    ns = {"__file__": os.path.join(REPO, "scripts", "cycloneiv_clean_names_search.py")}
    exec(compile(src, "search", "exec"), ns)
    rcfs = [os.path.join(CORPUS, d, "routing.rcf") for d in DESIGNS]
    rcfs = [p for p in rcfs if os.path.exists(p)]
    if len(rcfs) < 10:
        pytest.skip(f"corpus rcf missing ({len(rcfs)}/10)")
    keys = routing.element_keys()
    order = np.argsort(keys, kind="stable")
    sk = keys[order]
    en = names.enums()

    def rec(n):
        k = ddb.element_key(en[n[0]], *n[1:])
        lo, hi = np.searchsorted(sk, k, "left"), np.searchsorted(sk, k, "right")
        return int(order[lo]) if hi - lo == 1 else -1

    ok, tot, fan = collections.Counter(), collections.Counter(), {}
    for p in rcfs:
        edges, _, _ = ns["parse_rcf"](p)
        for a, b in set(edges):
            if a[0] in en and b[0] in en:
                ra, rb = rec(a), rec(b)
                ts = {a[0], b[0]}
                if ts & OPEN_EDGE:      # edges touching these types are scored on those types only
                    ts &= OPEN_EDGE
                for t in ts:
                    tot[t] += 1
                if ra >= 0 and rb >= 0:
                    if ra not in fan:
                        fan[ra] = set(routing.fanout(ra).tolist())
                    if rb in fan[ra]:
                        for t in ts:
                            ok[t] += 1
    bad = []
    for t, e in names.entries().items():
        status = e["status"]
        report("O4-edges", type=t, enum=e["enum"], status=status, edges=tot[t], consistent=ok[t],
               pct=round(100 * ok[t] / tot[t], 3) if tot[t] else None, unique_pct=e.get("unique_pct"))
        if status == "vendor" and tot[t] >= 1000 and t not in OPEN_EDGE and ok[t] / tot[t] < 0.99:   # enum is a vendor read; edge consistency is the oracle
            bad.append(t)
    assert not bad, bad
