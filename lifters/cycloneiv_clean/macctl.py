"""Cyclone IV GX embedded multiplier (MAC) control decode (#165).  asmdb groups + the LAB-style mapped-mux inverse (ffctl.Calc); written for the
18 x 18 single-multiplier mode.

Evidence (docs/cycloneiv-clean-mac.md):
  - A MAC instance is used iff any bit of its control groups is set: MAC cells are in no default-bit list and read 0 in a build without MACs
    (cells are only ever written by the ASM_MAC_* writers, libcomp_asmmac).  Routing cannot detect it: the MAC output elements are DSP_BUFFER.
  - MAC_ROW_DATA_INPUT gi k (36 groups, mapped mux, 46 inputs): input number = LOCAL_INTERCONNECT index of the MAC tile feeding data pin k
    (k < 18 DATAA[k], k >= 18 DATAB[k - 18]); MAC_PIA_TO_CLK / _CE / _CLR / _SIGN gi k the same for the control pins (8 / 16 inputs).
  - MAC_ROW_DATA_INVERT gi k (arch_value 1): data pin k inverted.
  - MAC_SIGN_INVERT gi 0 / 1 (arch_value 1): bit set = unsigned A / B, cleared = signed; MAC_PIA_TO_SIGN gi 0 / 1 selects a dynamic sign pin.
  - MAC_ROW_IREG_{UPPER,LOWER}_DATA gi 0 = A input register, gi 1 = B input register; MAC_ROW_OREG_UPPER_DATA gi 0 / 1 = output register.
  - MAC_USE_NINE_BIT_DATA_WIDTH_PER_ROW: 9-bit rows (two multipliers per MAC); not modelled (flagged).
"""
import numpy as np

from . import asmdb_select as S
from . import clocks, ddb, ffctl, mac, names, plane as P
from . import fields as F

MAC_BLOCK = mac.MAC
# source: libdb_asmdb arch-group-type table, MAC block 41 (calc groups with an input map)
CALC = ("MAC_ROW_DATA_INPUT", "MAC_PIA_TO_CLK", "MAC_PIA_TO_CE", "MAC_PIA_TO_CLR", "MAC_PIA_TO_SIGN")
# source: libdb_asmdb arch-group-type table, MAC block 41 (one-bit groups, arch_value 1); roles from the gxhb_mac* pair builds (docs/cycloneiv-clean-mac.md)
ONE = ("MAC_ROW_DATA_INVERT", "MAC_SIGN_INVERT", "MAC_ROW_IREG_UPPER_DATA", "MAC_ROW_IREG_LOWER_DATA", "MAC_ROW_OREG_UPPER_DATA",
       "MAC_USE_NINE_BIT_DATA_WIDTH_PER_ROW", "MAC_CLK_INVERT", "MAC_CE_INVERT", "MAC_CLR_INVERT", "MAC_IREG_SIGN")
ROWS = 36                    # source: MAC_ROW_DATA_INPUT has 36 groups (asmdb walk); 18 rows per operand
HALF = 18                    # source: 18 x 18 mode: gi < 18 = operand A


class MacCtl:
    def __init__(self, walk, names_=None):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        names_ = names_ or D.enum_tables()
        gt = names_["arch_group_type"]
        tab = P.load_tables()
        bs = F.bases(walk, MAC_BLOCK)
        self.n = len(bs)
        self.calc, self.one = {}, {}
        for g in walk.groups():
            if g["btype"] != MAC_BLOCK:
                continue
            nm = gt.get(g["type"])
            if nm in CALC:
                self.calc[(nm, g["gi"])] = ffctl.Calc(walk, g, bs, tab)
            elif nm in ONE:
                c = ffctl._cols(bs, walk.mux(g["paths"][0][0])["bits"], tab)
                self.one[(nm, g["gi"])] = (c[max(c)], g["data"][0]["av"])
        fm = [g for g in walk.groups() if g["btype"] == MAC_BLOCK and gt.get(g["type"]) == "MAC_CLK_FAST_MUX"][0]
        # MAC_CLK_FAST_MUX: SIMPLE mux (no input map): bit j hot = block clock line j (ASMDB_SIMPLE_MUX::select one-hot)
        self.clkfast = np.stack([c for _, c in sorted(ffctl._cols(bs, walk.mux(fm['paths'][0][0])['bits'], tab).items())], axis=1)

    def val(self, key, bits):
        c, av = self.one[key]
        return bits[c] if av else 1 - bits[c]

    def used(self, bits):
        """bool [instances]: any control cell set."""
        u = np.zeros(self.n, bool)
        for key, (c, _av) in self.one.items():
            u |= bits[c] == 1
        u |= (bits[self.clkfast] == 1).any(axis=1)
        for ca in list(self.calc.values()):
            for lv in ca.cols:
                for cc in lv.values():
                    u |= bits[cc] == 1
        return u

    def decode(self, bits):
        """dict of arrays over the instances."""
        o = {"used": self.used(bits)}
        o["data_sel"] = np.stack([self.calc[("MAC_ROW_DATA_INPUT", k)].select(bits) for k in range(ROWS)], axis=1)
        o["data_inv"] = np.stack([self.val(("MAC_ROW_DATA_INVERT", k), bits) for k in range(ROWS)], axis=1)
        for k, nm in (("clk", "MAC_PIA_TO_CLK"), ("ena", "MAC_PIA_TO_CE"), ("aclr", "MAC_PIA_TO_CLR")):
            o[k + "_sel"] = self.calc[(nm, 0)].select(bits)
        o["sign_sel"] = np.stack([self.calc[("MAC_PIA_TO_SIGN", k)].select(bits) for k in (0, 1)], axis=1)
        o["unsigned"] = np.stack([self.val(("MAC_SIGN_INVERT", k), bits) == 1 for k in (0, 1)], axis=1)
        o["ireg"] = np.stack([(self.val(("MAC_ROW_IREG_UPPER_DATA", k), bits) == 1) | (self.val(("MAC_ROW_IREG_LOWER_DATA", k), bits) == 1) for k in (0, 1)], axis=1)
        o["oreg"] = (self.val(("MAC_ROW_OREG_UPPER_DATA", 0), bits) == 1) | (self.val(("MAC_ROW_OREG_UPPER_DATA", 1), bits) == 1)
        o["nine"] = self.val(("MAC_USE_NINE_BIT_DATA_WIDTH_PER_ROW", -1), bits) == 1
        hot = bits[self.clkfast].astype(np.int64)
        fast = np.where(hot.sum(1) == 1, hot.argmax(1), -1)
        o["clk_fast"] = fast
        # bit 0 = the PIA (LOCAL_INTERCONNECT) clock path, bits 1..6 = block clock line 0..5 (gxhb_mac*_out_reg: bit 6 <-> BLK_CLK_BUF index 5)
        o["clk_line"] = np.where(fast >= 1, fast - 1, -1)
        o["clk_inv"] = self.val(("MAC_CLK_INVERT", 0), bits) == 1
        o["ena_inv"] = self.val(("MAC_CE_INVERT", 0), bits) == 1
        o["aclr_inv"] = self.val(("MAC_CLR_INVERT", 0), bits) == 1
        return o
