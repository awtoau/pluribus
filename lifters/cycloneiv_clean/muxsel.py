"""Selection decode of a LAB mux group that carries an input map (asmdb calc group, #165).  Vendor-derived only.

Group layout (source: libdb_asmdb ASMDB_ARCH_GROUP_CALC, walk in asmdb_walk.py): paths[site] = [first-level mux (class 14, `map`),
second-level mux (class 15 / 17)]; data[0] = (aux, nxt) = two class-17 vectors indexed by INPUT number:
  aux[i] = which first-level bit is set for input i (one-hot); nxt[i] = value of the second-level pair for input i.
  0xFFFFFFFE = input does not exist in this mux, 0xFFFFFFFB = second level not constrained.
Second-level state of the plane: no bit set = 0, only bit k set = k + 1, more than one set = invalid.
That state encoding is read off the plane: LAB_PIA_TO_INPUT 175 / 175 edges of gx150_rb_000..009 (tests/cycloneiv_clean/test_decoders.py).
"""
import numpy as np

from . import fields as F
from . import plane as P

# source: asmdb mux vectors (value markers seen in aux / nxt vectors of the LAB calc groups)
ABSENT = 0xFFFFFFFE
FREE = 0xFFFFFFFB
STATES = 4                       # second-level states 0..2 valid (2 bits: none / bit0 / bit1), 3 = both set (invalid)


class MapSelect:
    """One (block type, group, site) mux: cell indices of its first / second level bits for every instance, and the (aux, nxt) table."""

    def __init__(self, w, g, bases, site=0, tables=None):
        tab = tables or P.load_tables()
        self.first_off = [o for o in w.mux(g["paths"][site][0])["bits"] if o < 0x80000000]
        self.second_off = [o for o in w.mux(g["paths"][site][1])["bits"] if o < 0x80000000]
        d = g["data"][0]
        self.aux = np.asarray(w.mux(d["aux"])["bits"], np.int64)
        self.nxt = np.asarray(w.mux(d["nxt"])["bits"], np.int64)
        self.cells0 = self._cells(bases, self.first_off, tab)
        self.cells1 = self._cells(bases, self.second_off, tab)
        n0 = len(self.first_off)
        # (hot bit, state) -> input number; -1 none; -2 more than one input (ambiguous, never guessed)
        self.table = np.full((n0, STATES), -1, np.int64)
        for i, (a, n) in enumerate(zip(self.aux.tolist(), self.nxt.tolist())):
            if a == ABSENT or a >= n0:
                continue
            for s in range(STATES) if n == FREE else ([n] if n < STATES else []):
                self.table[a, s] = i if self.table[a, s] == -1 else -2

    @staticmethod
    def _cells(bases, offs, tab):
        a = F.absolute(bases, np.asarray(offs, np.int64))
        r, j, k = P.sof_to_rbf(a.ravel(), tab)
        return (r * P.BITS_PER_FRAME + (j - 1) * P.LANES + k).reshape(a.shape)

    def select(self, bits):
        """-> int64 [instances]: selected input number, -1 = no (or invalid) selection, -2 = ambiguous table entry."""
        v0 = bits[self.cells0].astype(np.int64)
        v1 = bits[self.cells1].astype(np.int64)
        hot = v0.sum(1) == 1
        j = v0.argmax(1)
        ones = v1.sum(1)
        state = np.where(ones == 0, 0, np.where(ones == 1, v1.argmax(1) + 1, STATES - 1))
        return np.where(hot, self.table[j, np.minimum(state, STATES - 1)], -1)
