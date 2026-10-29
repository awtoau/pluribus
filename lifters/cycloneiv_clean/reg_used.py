"""Register-used decode of a logic element (#165).  Vendor groups + register-pair specimens; no fitted constant.

There is no dedicated register-used bit in the asmdb LE groups.  What the groups hold is the output select:
  LE_REG_OUT_YGR gi 0 / gi 1 = output select (1 = LUT, 0 = register) of LE_BUFFER 2 le + 0 / 2 le + 1; gi 2 = the same for the third
  output path (the LAB-local one, sink = a LE_LUT_INPUT mux, not decoded).  An unused path reads 0, like a register path.
A flip-flop is present in a configured LE (LE_LUT_FUNCTION cell set, or LE_USE_SYNC_CLEAR and LE_USE_SYNC_LOAD both set = FF-only LE) iff
  - a used LE_BUFFER b (programmed edge out of it) has YGR[b] == 0, or
  - neither LE_BUFFER is used and YGR[2] == 0.
Otherwise the claim is withheld (ambiguous = missing): a clear YGR[2] next to a used LUT buffer cannot be told from an unused path.
Evidence:
  - scripts/cycloneiv_clean_reg_pairs.py: 5 LABs x 75 feature sites x 7 pair builds + base, vo ground truth (types A / C / D; numbers in #165).
  - YGR gi <-> LE_BUFFER parity: corpus rb_000..009, LUT-only LEs with one used buffer, every class 100 % (tests/cycloneiv_clean/test_decoders.py).
"""
import numpy as np

from . import ddb, names
from . import fields as F
from . import plane as P

LAB_BLOCK = 18                                      # source: ASMDB_ARCH_GROUP_BLOCK_TYPE LAB (fields.PLACED)
YGR = "LE_REG_OUT_YGR"                              # source: libdb_asmdb arch-group-type table (gi 0, 1, 2; one bit per LE)
SYNC = ("LE_USE_SYNC_CLEAR", "LE_USE_SYNC_LOAD")    # source: libdb_asmdb arch-group-type table (one bit per LE)
BUFFER = "LE_BUFFER"                                # source: names_table.json (RCF type -> routing.ddb element enum)


def _cells(w, names_, bs, name, gi=None):
    tab = P.load_tables()
    g = next(g for g in w.groups() if g["btype"] == LAB_BLOCK and names_["arch_group_type"].get(g["type"]) == name
             and (gi is None or g["gi"] == gi))
    a = np.stack([F.absolute(bs, np.asarray([o for o in w.mux(g["paths"][le][0])["bits"] if o < 0x80000000][:1], np.int64))[:, 0]
                  for le in range(16)], axis=1)
    r, j, k = P.sof_to_rbf(a.ravel(), tab)
    return (r * P.BITS_PER_FRAME + (j - 1) * P.LANES + k).reshape(a.shape)


class RegUsed:
    def __init__(self, lut, st, rt=None):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        w, n_ = lut.walk, D.enum_tables()
        bs = F.bases(w, LAB_BLOCK)
        rt = rt or ddb.Routing()
        self.lut, self.st = lut, st
        self.ygr = [_cells(w, n_, bs, YGR, gi) for gi in (0, 1, 2)]
        self.sync = [_cells(w, n_, bs, s) for s in SYNC]
        # LE_BUFFER record per (LAB, LE, b): exact element key (A7); LAB index = column rank * 90 + Y - 1
        keys_all = rt.element_keys()
        order = np.argsort(keys_all, kind="stable")
        keys = keys_all[order]
        xs = np.asarray(lut.xs)
        lab = np.arange(len(bs))
        x, y = xs[lab // F.ROWS_PER_COLUMN].astype(np.int64), (lab % F.ROWS_PER_COLUMN + 1).astype(np.int64)
        e = names.enum_of(BUFFER)
        q = np.stack([np.stack([ddb.element_key(e, x, y, 0, 2 * le + b) for b in (0, 1)], axis=-1) for le in range(16)], axis=1)
        i = np.minimum(np.searchsorted(keys, q), len(keys) - 1)
        self.buf = np.where(keys[i] == q, order[i], -1)                  # [labs, 16, 2]
        if (self.buf < 0).any():
            raise SystemExit("LAB without 32 LE_BUFFER records")
        self.slot = np.full(rt.n, -1, np.int64)
        self.slot[self.buf.ravel()] = np.arange(self.buf.size)

    def used(self, edges):
        """bool [labs, 16, 2]: LE_BUFFER with a programmed outgoing edge."""
        s = self.slot[self.st.esrc[np.asarray(edges, np.int64)]]
        u = np.zeros(self.buf.size, bool)
        u[s[s >= 0]] = True
        return u.reshape(self.buf.shape)

    def ff(self, bits, edges):
        """bool [labs, 16]: the LE has a flip-flop (claim); False = no flip-flop or not decidable."""
        y = np.stack([bits[c] == 1 for c in self.ygr], axis=-1)
        u = self.used(edges)
        configured = (self.lut.cells(bits).sum(axis=2) > 0) | ((bits[self.sync[0]] == 1) & (bits[self.sync[1]] == 1))
        reg_buf = (u & ~y[..., :2]).any(axis=-1)
        local_only = ~u.any(axis=-1) & ~y[..., 2]
        return configured & (reg_buf | local_only)
