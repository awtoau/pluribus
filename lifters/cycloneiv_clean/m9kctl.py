"""Cyclone IV GX M9K port decode for the single-port, port-A modes (#165).  asmdb mapped-mux inverse (ffctl.Calc) + specimen-read pin map.

Rules (docs/altera/cycloneIV/cycloneiv-clean-m9k.md; pin map read off the training split of the gxm9k_* specimens, a crc32-selected quarter is held out):
  - word-width class: RAM_DATA_WRITE_MODE is a 6-bit mapped-simple mux, one-hot index 0..4 = by1, by2, by4, by8/9, by16 and wider.
  - port-A data pin k = RAM_MS_DATA_INPUT gi k; port-A address pins: slot s of the 9-entry RAM_MS_WRITE_ADDRESS_INPUT list (gi 12, 0..7) for the
    9 high pins; the (A - 9) low pins of the 10..13-bit address modes share RAM_MS_DATA_INPUT gi 16 - (A - 9) .. 15.
  - A = 13, 12, 11, 10, 9 for classes by1, by2, by4, by8/9, by16/18 (full depth); W = 1, 2, 4 from the class, W = connected data groups - 1 for
    by8/9 (one data group carries address bit 0), W = connected data groups for by16/18.
  - write enable = RAM_PIA_TO_INPUT_YGR gi 11; clock: RAM_CLOCK_FAST_MUX gi 0 value 1 (bit 0) = LOCAL_INTERCONNECT clock via RAM_PIA_TO_INPUT_YGR
    gi 0 (else gi 1), values 12..17 (bit 1 + bit 2 + j) = block clock line j (asmdb map of the mux, asmdb_select).
  - output register: RAM_REG_DATA_OUT bit clear (the one-hot rule stores NOT value).
Byte enable (16-bit words): PORTABYTEENAMASKS[k] = RAM_MS_BYTE_ENABLE_INPUT gi k, no connected group = all bytes written.
Not modelled: B port, dual-port / true-dual-port / ROM modes, widths 32 / 36, byte enables, clear / clock-enable selects, read-during-write modes.
"""
import json
import os

import numpy as np

from . import ddb, ffctl, m9k, plane as P
from . import fields as F

MEAB = m9k.MEAB
CE_LINES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ram_ce_lines.json")
# source: RAM_MS_WRITE_ADDRESS_INPUT group indices in asmdb (walk): gi 0..7 and 12 (9 groups); slot order read off the training split (115 / 115 specimens at A = 9)
WRITE_SLOTS = (12, 0, 1, 2, 3, 4, 5, 6, 7)
CLASS_A = (13, 12, 11, 10, 9, 8)    # source: 8192 / (word width class) addresses = 2**A (by1 .. by16); class 5 = by32 / by36 (256 words, m9k.depth)
# source: ASM_RAM_CE_SELECT_INPUT@0x7fc98, _CORE@0x7ff4a (port A: ENA0 -> 0, ENA2 -> 2; ENA1 / ENA3 raise "can't be set on the A side"),
#         ASM_RAM_CE_SELECT_INPUT_B@0x7fdee, _CORE_B@0x800a2 (port B: ENA1 -> 1, ENA3 -> 3; ENA0 / ENA2 raise "can't be set on the B side"), libcomp_asmram
CE_SELECT_VALUES = {"A": {"ENA0": 0, "ENA2": 2}, "B": {"ENA1": 1, "ENA3": 3}}
# source: ASM_RAM_CE_SELECT_OUTPUT@0x7ea68 / _B@0x7ec3a: output-register CE flag 0x800 -> value 0, else flag 0x1000 -> value 1, neither -> group not written (same bits for both ports)
CE_SELECT_OUTPUT_FLAGS = {0x800: 0, 0x1000: 1}
# source: process_end_of_phase of ASM_RAM_{CLEAR,CLOCK,CE,READ_ENABLE,WRITE_ENABLE}_INVERT libcomp_asmram@0x2ca6a / 0x2caea / 0x2c9ea / 0x2e04e / 0x2df5c: model query (site, kind) with kind = these numbers
INVERT_KIND = {"RAM_CLEAR_INVERT": 0, "RAM_CLOCK_INVERT": 1, "RAM_CE_INVERT": 2, "RAM_READ_ENABLE_INVERT": 8, "RAM_WRITE_ENABLE_INVERT": 0xb}


# source: every non-port MEAB control group of the asmdb walk (names in docs/altera/cycloneIV/cycloneiv-clean-hardblocks.md); read as raw bit columns, values per m9k.WRITERS / the mode docs
CONTROL_GROUPS = (
    "RAM_DATA_WRITE_MODE", "RAM_DATA_WRITE_MODE_B", "RAM_CLOCK_FAST_MUX", "RAM_CLOCK_INVERT", "RAM_REG_DATA_OUT", "RAM_REG_DATA_OUT_B",
    "RAM_CE_FAST_MUX", "RAM_CE_SELECT_INPUT", "RAM_CE_SELECT_INPUT_B", "RAM_CE_SELECT_CORE", "RAM_CE_SELECT_CORE_B", "RAM_CE_SELECT_OUTPUT",
    "RAM_CE_SELECT_OUTPUT_B", "RAM_CE_INVERT", "RAM_NEW_DATA_MODE", "RAM_NEW_DATA_MODE_B", "RAM_USE_PACKED_MODE", "RAM_USE_TRUE_DUAL_PORT_MODE",
    "RAM_SELECT_CLK_DATA_OUT", "RAM_SELECT_CLK_DATA_OUT_B", "RAM_SELECT_CLK_BYTE_ENABLE_DATA_B", "RAM_SELECT_CLK_READ_ENABLE_READ_ADDRESS_B",
    "RAM_RE_FAST_MUX", "RAM_WE_FAST_MUX", "RAM_READ_ENABLE_INVERT", "RAM_WRITE_ENABLE_INVERT", "RAM_CLEAR_FAST_MUX", "RAM_CLEAR_INVERT",
    "RAM_USE_CLR_DATA_OUT", "RAM_USE_CLR_DATA_OUT_B", "RAM_USE_CLR_READ_ADDRESS", "RAM_USE_CLR_READ_ADDRESS_B", "RAM_SELECT_CLR_DATA_OUT",
    "RAM_SELECT_CLR_DATA_OUT_B", "RAM_SELECT_CLR_READ_ADDRESS_B", "RAM_USAGE_MODE")


class M9kCtl:
    def __init__(self, walk, names_=None):
        import sys
        sys.path.insert(0, ddb.SCRIPTS)
        import cycloneiv_clean_dirt as D
        names_ = names_ or D.enum_tables()
        gt = names_["arch_group_type"]
        tab = P.load_tables()
        bs = F.bases(walk, MEAB)
        self.n = len(bs)
        self.calc, self.cols = {}, {}
        self.walk = walk
        for g in walk.groups():
            if g["btype"] != MEAB:
                continue
            nm = gt.get(g["type"])
            if nm in ("RAM_MS_DATA_INPUT", "RAM_MS_WRITE_ADDRESS_INPUT", "RAM_MS_READ_ADDRESS_INPUT", "RAM_PIA_TO_INPUT_YGR", "RAM_MS_BYTE_ENABLE_INPUT",
                      "RAM_MS_DATA_INPUT_B", "RAM_MS_BYTE_ENABLE_INPUT_B"):
                self.calc[(nm, g["gi"])] = ffctl.Calc(walk, g, bs, tab)
            elif nm in CONTROL_GROUPS:
                c = ffctl._cols(bs, walk.mux(g["paths"][0][0])["bits"], tab)
                self.cols[(nm, g["gi"])] = np.stack([c[k] for k in sorted(c)], axis=1)
                if nm == "RAM_CLOCK_FAST_MUX":
                    self.clk_map = list(walk.mux(walk.mux(g["paths"][0][0])["map"])["bits"])

    def decode(self, bits):
        """dict of arrays over the instances (see module docstring)."""
        n = self.n
        o = {}
        dwm = bits[self.cols[("RAM_DATA_WRITE_MODE", -1)]].astype(np.int64)
        o["cls"] = np.where(dwm.sum(1) == 1, dwm.argmax(1), -1)
        o["data"] = np.stack([self.calc[("RAM_MS_DATA_INPUT", k)].select(bits) for k in range(36)], axis=1)
        o["waddr"] = np.stack([self.calc[("RAM_MS_WRITE_ADDRESS_INPUT", g)].select(bits) for g in WRITE_SLOTS], axis=1)
        raddr = [c for (nm, _g), c in self.calc.items() if nm == "RAM_MS_READ_ADDRESS_INPUT"]
        o["read_groups"] = np.stack([c.select(bits) >= 0 for c in raddr], axis=1).sum(1)
        o["raddr"] = {g: c.select(bits) for (nm, g), c in self.calc.items() if nm == "RAM_MS_READ_ADDRESS_INPUT"}
        o["be"] = np.stack([self.calc[("RAM_MS_BYTE_ENABLE_INPUT", k)].select(bits) for k in range(4)], axis=1)   # port-A byte enables: gi 0, 1 (16-bit word), training split
        w11 = self.calc[("RAM_PIA_TO_INPUT_YGR", 11)].select(bits)
        w9 = self.calc[("RAM_PIA_TO_INPUT_YGR", 9)].select(bits)
        # write enable = gi 11, else gi 9 (training split: d1 uses gi 9); the clock group is independent of it (b18_base: clock gi 1, we gi 11)
        o["cg"] = np.zeros(n, np.int64)                              # replaced below once pia is known

        o["we"] = np.where(w11 >= 0, w11, w9)
        o["pia"] = np.stack([self.calc[("RAM_PIA_TO_INPUT_YGR", g)].select(bits) for g in (0, 1)], axis=1)
        o["pia_all"] = np.stack([self.calc[("RAM_PIA_TO_INPUT_YGR", g)].select(bits) for g in range(12)], axis=1)
        o["cg"] = np.where(o["pia"][:, 0] >= 0, 0, np.where(o["pia"][:, 1] >= 0, 1, 0))
        o["clk_fast"] = np.where(o["cg"][:, None] == 0, bits[self.cols[("RAM_CLOCK_FAST_MUX", 0)]], bits[self.cols[("RAM_CLOCK_FAST_MUX", 1)]]).astype(np.int64)
        o["data_b"] = np.stack([self.calc[("RAM_MS_DATA_INPUT_B", k)].select(bits) for k in range(18)], axis=1)
        o["be_b"] = np.stack([self.calc[("RAM_MS_BYTE_ENABLE_INPUT_B", k)].select(bits) for k in range(2)], axis=1)
        o["ctl"] = {nm_gi: bits[c].astype(np.int64) for nm_gi, c in self.cols.items()}              # (group, gi) -> [instances, n bits]
        o["oreg"] = bits[self.cols[("RAM_REG_DATA_OUT", -1)]][:, 0] == 0
        o["oreg_b"] = bits[self.cols[("RAM_REG_DATA_OUT_B", -1)]][:, 0] == 0
        # input-side clock enable (ledger M-017): RAM_CE_SELECT_INPUT bit 0 = ENA0 selected; RAM_CE_FAST_MUX gi 0 bit set = alternate PIA line, clear = preferred line
        ce = json.load(open(CE_LINES))["ce_fast_mux"]["0"]
        o["ce_in"] = bits[self.cols[("RAM_CE_SELECT_INPUT", -1)]][:, 0] == 1
        o["ce_line"] = np.where(bits[self.cols[("RAM_CE_FAST_MUX", 0)]][:, 0] == 1, ce[1], ce[0])
        o["ce_invert"] = bits[self.cols[("RAM_CE_INVERT", 0)]][:, 0] == 1
        nd = (o["data"] >= 0).sum(1)
        o["n_data"] = nd
        cls = o["cls"]
        o["A"] = np.where(cls >= 0, np.asarray(CLASS_A)[np.maximum(cls, 0)], 0)
        w = np.where(cls <= 2, np.asarray([1, 2, 4, 0, 0, 0])[np.maximum(cls, 0)], 0)
        w = np.where(cls == 3, nd - 1, w)
        w = np.where(cls == 4, nd, w)
        w = np.where(cls == 5, np.where(nd >= 32, nd, 0), w)      # by32 / by36: connected data groups; other counts undecoded (0)
        o["W"] = np.where(cls >= 0, w, 0)
        return o

    def clock_line(self, bitsrow):
        """block clock line j when RAM_CLOCK_FAST_MUX gi 0 bits = map[12 + j]; 'pia' when bit 0 set; else None."""
        v = int(sum(int(b) << k for k, b in enumerate(bitsrow)))
        if v & 1:
            return "pia"
        for j in range(6):
            if v == self.clk_map[12 + j]:
                return j
        return None
