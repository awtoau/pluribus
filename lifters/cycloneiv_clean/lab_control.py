"""LOCAL_INTERCONNECT -> LAB_CONTROL_MUX edges from the LAB_PIA_TO_INPUT groups (#165).  Vendor-derived only.

The routing graph (A1) has no fan-out for LOCAL_INTERCONNECT, so these edges are not in the Static table.  They are decoded here:
  - LAB_CONTROL_MUX (x, y, index k) of a LAB = LAB_PIA_TO_INPUT group gi k (9,360 LABs x 4 = 37,440 records, as many as the group has instances).
  - input number i of that group = LOCAL_INTERCONNECT index i at the same (x, y); aux / nxt of the group's input map give the bits (muxsel.py).
The universe of edges (every input the map allows whose two records exist) gets ids after the real edges: `Implicit.esrc / edst`.
"""
import numpy as np

from . import clocks, ddb, muxsel, names
from . import fields as F

GROUP = "LAB_PIA_TO_INPUT"               # source: libdb_asmdb arch-group-type table (gi 0..3, one site per LAB)
LABLINE = "LOCAL_INTERCONNECT"           # source: names_table.json (RCF type -> routing.ddb element enum)
CONTROL = "LAB_CONTROL_MUX"              # source: names_table.json


class Implicit:
    def __init__(self, lut, rt=None, names_=None, n_real=0):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        w = lut.walk
        rt = rt or ddb.Routing()
        names_ = names_ or D.enum_tables()
        bs = F.bases(w, clocks.LAB_BLOCK)
        self.mux = clocks.group_cells(w, names_, clocks.LAB_BLOCK, GROUP, bs)
        self.ks = sorted(self.mux)
        keys_all = rt.element_keys()
        order = np.argsort(keys_all, kind="stable")
        keys = keys_all[order]

        def find(q):
            i = np.minimum(np.searchsorted(keys, q), len(keys) - 1)
            return np.where(keys[i] == q, order[i], -1)

        xs = np.asarray(lut.xs)
        lab = np.arange(len(bs))
        x, y = xs[lab // F.ROWS_PER_COLUMN].astype(np.int64), (lab % F.ROWS_PER_COLUMN + 1).astype(np.int64)
        e_li, e_cm = names.enum_of(LABLINE), names.enum_of(CONTROL)
        src, dst = [], []
        self.eid = {}
        n = n_real
        for k in self.ks:
            m = self.mux[k]
            cm = find(ddb.element_key(e_cm, x, y, 0, k))
            valid = [i for i in range(len(m.aux)) if m.aux[i] != muxsel.ABSENT and m.aux[i] < len(m.first_off)]
            ids = np.full((len(lab), len(m.aux)), -1, np.int64)
            for i in valid:
                li = find(ddb.element_key(e_li, x, y, 0, i))
                ok = (li >= 0) & (cm >= 0)
                cnt = int(ok.sum())
                ids[ok, i] = np.arange(n, n + cnt)
                src.append(li[ok])
                dst.append(cm[ok])
                n += cnt
            self.eid[k] = ids
        self.esrc = np.concatenate(src).astype(np.int32)
        self.edst = np.concatenate(dst).astype(np.int32)
        self.n_real = n_real

    def apply(self, bits):
        """-> programmed implicit edge ids (>= n_real): one per (LAB, k) whose map resolves to exactly one existing input."""
        out = []
        for k in self.ks:
            sel = self.mux[k].select(bits)
            lab = np.flatnonzero(sel >= 0)
            e = self.eid[k][lab, sel[lab]]
            out.append(e[e >= 0])
        return np.concatenate(out)
