"""LOCAL_INTERCONNECT -> DSP_CONTROL_INPUT edges of the MAC control pins (CLK, SIGNA, SIGNB) (#165, #169).

- DSP_CONTROL_INPUT (enum 380, hdr debug name MAC_SEC_INPUT) has 5 records per MAC tile (routing.ddb); the routing graph has no fan-out for the tile's
  LOCAL_INTERCONNECT records, so the edges are decoded here (same shape as m9k_pia.py).
- Group MAC_PIA_TO_{CLK,SIGN gi 0/1} (ffctl.Calc, input number = LOCAL_INTERCONNECT index) selects the source; destination index:
  CLK 0, SIGNA 3, SIGNB 4 (RCF ground truth of gxhb_macp{a,b}_*, gxhb_mac_dyn_signa: pin dest + DSP_CONTROL_INPUT index).
- CE / CLR (indices 1, 2 by exclusion) never occur in a corpus route to a MAC pin: not decoded (open, #169).
"""
import numpy as np

from . import ddb, ffctl, mac, macctl, names, plane as P
from . import fields as F

# source: RCF route of the MAC pin: ... LOCAL_INTERCONNECT:X..I<li>; DSP_CONTROL_INPUT:X..S0I<dst>; dest = (mac_mult, <PIN>) in gxhb_macpb_mult_reg (CLK 0), gxhb_mac_dyn_signa (SIGNA 3), gxhb_macpa_dyn_signb (SIGNB 4)
PINS = {("MAC_PIA_TO_CLK", 0): 0, ("MAC_PIA_TO_SIGN", 0): 3, ("MAC_PIA_TO_SIGN", 1): 4}


class Implicit:
    def __init__(self, walk, rt, n_real=0):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        from .bim import finder
        gt = D.enum_tables()["arch_group_type"]
        tab = P.load_tables()
        bs = F.bases(walk, mac.MAC)
        find = finder(rt)
        e_li, e_ctl = names.enum_of("LOCAL_INTERCONNECT"), names.enum_of("DSP_CONTROL_INPUT")
        cols = mac.columns()
        self.calc = {}
        for g in walk.groups():
            k = (gt.get(g["type"]), g["gi"])
            if g["btype"] == mac.MAC and k in PINS:
                self.calc[k] = ffctl.Calc(walk, g, bs, tab)
        if set(self.calc) != set(PINS):
            raise SystemExit(f"MAC_PIA groups {sorted(self.calc)} != {sorted(PINS)}")
        self.eid = {}                       # per pin key: {instance: {LI index: edge id}}
        src, dst, n = [], [], n_real
        for k, di in PINS.items():
            per = {}
            for inst in range(len(bs)):
                x, y = cols[inst // F.ROWS_PER_COLUMN], inst % F.ROWS_PER_COLUMN + 1
                c = find(ddb.element_key(e_ctl, x, y, 0, di))
                if c < 0:
                    continue
                for li in range(128):
                    r = find(ddb.element_key(e_li, x, y, 0, li))
                    if r >= 0:
                        per.setdefault(inst, {})[li] = n
                        src.append(r)
                        dst.append(c)
                        n += 1
            self.eid[k] = per
        self.esrc, self.edst, self.n_real = np.asarray(src, np.int32), np.asarray(dst, np.int32), n_real
        self.ctl = macctl.MacCtl(walk)
        e_blk = names.enum_of("BLK_CLK_BUF")
        self.blk = {inst: [find(ddb.element_key(e_blk, cols[inst // F.ROWS_PER_COLUMN], inst % F.ROWS_PER_COLUMN + 1, 0, ln)) for ln in range(6)]
                    for inst in range(len(bs))}

    def apply(self, bits):
        """-> programmed edge ids: one per (instance, pin) whose group selects an existing LOCAL_INTERCONNECT."""
        out = []
        for k, ca in self.calc.items():
            sel = ca.select(bits)
            for inst, m in self.eid[k].items():
                e = m.get(int(sel[inst]))
                if e is not None:
                    out.append(e)
        return np.asarray(out, np.int64)

    def clock_recs(self, bits):
        """BLK_CLK_BUF records of the used MACs clocked from a block clock line (MAC_CLK_FAST_MUX, no PIA clock): their structural parents conduct."""
        d = self.ctl.decode(bits)
        sel = np.flatnonzero(d["used"] & (d["clk_line"] >= 0) & (d["clk_sel"] < 0))
        return np.asarray([r for i in sel.tolist() for r in [self.blk[i][int(d["clk_line"][i])]] if r >= 0], np.int64)
