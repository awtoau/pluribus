"""O4 (A7): RCF name -> element by exact equality on (type, x, y, z, index), x/y as in the name (A8, no mirror).
Reports, per design and per type, how many distinct names resolve to exactly one record.  Type -> enum: SEEDS below are
unverified (taken from the old naming constants), so the type-less count (enum free) is reported beside the typed one."""
import collections
import glob
import os

import numpy as np
import pytest

from conftest import REPO, report
from lifters.cycloneiv_clean import ddb, names

CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
DESIGNS = [f"gx150_rb_{n:03d}" for n in range(10)]
SEEDS = {"LE_BUFFER": 45, "R4": 268, "C4": 275, "R24": 273, "C16": 281, "LOCAL_INTERCONNECT": 282}


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
            if t in SEEDS:
                tp = lookup(keys, q0 + SEEDS[t] * 256 * 256 * 256 * 4096)
                tot_d[(t, "typed_unique")] += int((tp == 1).sum())
                tot_d[(t, "typed_none")] += int((tp == 0).sum())
                tot_d[(t, "typed_ambiguous")] += int((tp > 1).sum())
        tot.update(tot_d)
        report("O4", design=os.path.basename(os.path.dirname(p)), names=len(nm),
               seeded_names=sum(v for (t, w), v in tot_d.items() if w == "names" and t in SEEDS),
               typed_unique=sum(v for (t, w), v in tot_d.items() if w == "typed_unique"))
    for t in sorted({k[0] for k in tot}):
        report("O4-type", type=t, enum_seed=SEEDS.get(t), **{w: tot[(t, w)] for w in ("names", "typeless_unique", "typed_unique", "typed_none", "typed_ambiguous")})
    seeded = {t: tot[(t, "names")] for t in SEEDS}
    uniq = {t: tot[(t, "typed_unique")] for t in SEEDS}
    if uniq != seeded:
        pytest.xfail(f"typed exact-unique {sum(uniq.values())}/{sum(seeded.values())} names (seeded types)")
