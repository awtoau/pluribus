"""LOCAL_INTERCONNECT -> M4K_LEFT_CONTROL_INPUT edges of the M9K control pins (#165, #169).  Vendor-derived only.

The routing graph has no fan-out for these LOCAL_INTERCONNECT records, so the edges are decoded here:
  - M9K tile (column rank, row) = MEAB instance (m9k.instance); 12 M4K_LEFT_CONTROL_INPUT records per tile (routing.ddb).
  - Group RAM_PIA_TO_INPUT_YGR gi g (g = 0..11, one per control input) selects the LOCAL_INTERCONNECT index (input number = LI index, as bim.py);
    its destination is M4K_LEFT_CONTROL_INPUT index g.  Checked by the gate on the gxm9k_* designs (nets / pips, per M9K control pin).
Data, address and byte-enable pins (RAM_MS_*) have no element in the routing graph; their selections are read by m9kctl.py.
"""
import numpy as np

from . import ddb, ffctl, m9k, names, plane as P
from . import fields as F

GROUP = "RAM_PIA_TO_INPUT_YGR"
N_CTL = 12      # source: M4K_LEFT_CONTROL_INPUT records per M9K tile (routing.ddb), = group indices of GROUP in the MEAB block


class Implicit:
    def __init__(self, walk, rt, n_real=0):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        from .bim import finder
        gt = D.enum_tables()["arch_group_type"]
        tab = P.load_tables()
        bs = F.bases(walk, m9k.MEAB)
        find = finder(rt)
        e_li, e_ctl = names.enum_of("LOCAL_INTERCONNECT"), names.enum_of("M4K_LEFT_CONTROL_INPUT")
        cols = m9k.columns()
        gis = sorted(g["gi"] for g in walk.groups() if g["btype"] == m9k.MEAB and gt.get(g["type"]) == GROUP)
        if gis != list(range(N_CTL)):
            raise SystemExit(f"{GROUP} group indices {gis} != 0..{N_CTL - 1}")
        self.calc = {g["gi"]: ffctl.Calc(walk, g, bs, tab) for g in walk.groups() if g["btype"] == m9k.MEAB and gt.get(g["type"]) == GROUP}
        self.eid = []                       # per gi: {instance: {LI index: edge id}}
        src, dst, n = [], [], n_real
        for gi in range(N_CTL):
            per = {}
            for inst in range(len(bs)):
                x, y = cols[inst // F.ROWS_PER_COLUMN], inst % F.ROWS_PER_COLUMN + 1
                c = find(ddb.element_key(e_ctl, x, y, 0, gi))
                if c < 0:
                    continue
                for li in range(128):
                    r = find(ddb.element_key(e_li, x, y, 0, li))
                    if r >= 0:
                        per.setdefault(inst, {})[li] = n
                        src.append(r)
                        dst.append(c)
                        n += 1
            self.eid.append(per)
        self.esrc, self.edst, self.n_real = np.asarray(src, np.int32), np.asarray(dst, np.int32), n_real

    def apply(self, bits):
        """-> programmed edge ids: one per (instance, control input) whose group selects an existing LOCAL_INTERCONNECT."""
        out = []
        for gi in range(N_CTL):
            sel = self.calc[gi].select(bits)
            for inst, m in self.eid[gi].items():
                e = m.get(int(sel[inst]))
                if e is not None:
                    out.append(e)
        return np.asarray(out, np.int64)
