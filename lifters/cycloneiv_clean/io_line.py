"""MIO_LABLINE_TO_* selection of the IO blocks (HIO type 5, VIO type 6): which routing element feeds a pad data / control pin (#165).  Vendor-derived only.

Group: ASMDB_ARCH_GROUP_STD (class 6), one site per IO pad; a write for input number v is `asmdb_select.std_select(walk, group, site, v)`
(source: ASMDB_ARCH_GROUP_STD::select@0x7a3ac; HIO muxes are class 20 ASMDB_HETEROGENEOUS_ENCODED_MUX::select@0x8c334).
Input number = index of the routing element that sources the pin (ASMIO_MIO_LABLINE_TO_DATA::process_atom@0x4d874 passes
ASM_RE_PROXY::get_index of the first useful RE source to ASM_ARCH_GROUP::mux_select); 0..37 = LOCAL_INTERCONNECT of the pad's BIM tile
(same rule as bim.py).  Decode of a plane: the input whose full write pattern equals the plane bits of the site; none or several = -1 / -2.
"""
import numpy as np

from . import asmdb_select as S
from . import muxsel
from . import plane as P

AMBIGUOUS, NONE = -2, -1


class Line:
    def __init__(self, w, names, btype, name, gi=-1, tables=None, n_inputs=None):
        tab = tables or P.load_tables()
        self.g = next(g for g in w.groups() if g["btype"] == btype and names.get(g["type"]) == name and g["gi"] == gi)
        self.n_sites = len(self.g["paths"])
        nxt = w.mux(self.g["data"][0]["nxt"])["bits"] if self.g["data"][0]["nxt"] else None
        first = w.mux(self.g["paths"][0][0])
        self.n_inputs = n_inputs if n_inputs is not None else len(first["bits2"]) if first["cls"] == S.HETERO_ENCODED else len(nxt) if nxt else 0
        self.w = w
        self.offs, self.cells, self.pat = [], [], []
        for s in range(self.n_sites):
            rows = [dict(S.std_select(w, self.g, s, v)) if self._ok(s, v) else None for v in range(self.n_inputs)]
            cols = sorted({o for r in rows if r for o in r})
            self.offs.append(cols)
            self.cells.append(muxsel.MapSelect._cells(np.zeros(1, np.int64), [o for o in cols], tab)[0] if cols else np.zeros(0, np.int64))
            self.pat.append(np.array([[r.get(o, 0) if r else 2 for o in cols] for r in rows], np.int8))   # 2 = input not selectable

    def _ok(self, s, v):
        try:
            S.std_select(self.w, self.g, s, v)
            return True
        except ValueError:
            return False

    def select(self, bits, site):
        """-> input number selected at `site`, NONE (-1) if no pattern equals the plane, AMBIGUOUS (-2) if several do."""
        v = bits[self.cells[site]].astype(np.int8)
        hit = np.flatnonzero((self.pat[site] == v).all(1))
        return int(hit[0]) if len(hit) == 1 else AMBIGUOUS if len(hit) > 1 else NONE
