"""Cyclone IV GX (EP4CGX150) PLL configuration (#169).  Vendor-derived structure, specimen-confirmed.

- PLL config is CFF (periphery frames), not CRAM: every PLL arch group (block types 43 FAST_PLL, 45 GENERAL_PLL) carries CFF-tagged
  absolute addresses (tag 101, cycloneiv_io.ADDRESS_SPACES); `paths[k]` of a group = PLL instance k of that block type.  No instance base needed.
- Field value = mux bits read LSB first in mux order (bit j of the value = j-th mux bit).
- Counter encodings (libcomp_asm ASM_PLL_M_HIGH_COUNTER / M_LOW / N_HIGH / OUTPUT_COUNTER_* ::process_atom, static decompile):
  high = (count + 1) >> 1, low = count >> 1 for an uneven split; `*_MULT_FACTOR` group = even 0 / odd 2 / bypass.
"""
import numpy as np

from . import fields as F, cycloneiv_io as IO

PLL_BLOCKS = {43: "FAST_PLL", 45: "GENERAL_PLL"}      # source: libdb_asmdb ASMDB_ARCH_GROUP_BLOCK_TYPE (reference/ghidra/globals.tsv)
# PLL_k (Quartus location) -> (block type, path index); source: gxhb_pllsite_{1,2,3,4,5,8} builds, PLL_ENABLE_PLL bit set at exactly this path
PLL_SITE = {1: (43, 0), 2: (43, 5), 3: (45, 0), 4: (45, 1), 5: (43, 1), 8: (43, 4)}
# source: ASM_PLL_*_COUNTER::process_atom decompile + gxhb_pll_* pair builds (postfit.vo m / n / c#_high / c#_low / c#_initial / charge_pump_current_bits)
COUNTER_FIELDS = {"M": ("PLL_M_HIGH_COUNTER", "PLL_M_LOW_COUNTER", "PLL_M_MULT_FACTOR", "PLL_M_PRESET"),
                  "N": ("PLL_N_HIGH_COUNTER", "PLL_N_LOW_COUNTER", "PLL_N_MULT_FACTOR", None)}
# source: ASM_PLL_OUTPUT_COUNTER_* classes (libcomp_asm) = arch-group names; gi = output counter index c0..c4
OUT_FIELDS = ("PLL_OUTPUT_COUNTER_HIGH_COUNTER", "PLL_OUTPUT_COUNTER_LOW_COUNTER", "PLL_OUTPUT_COUNTER_MULT_FACTOR", "PLL_OUTPUT_COUNTER_PRESET")
# source: gxhb_pll_* builds: unused output counter reads high 15 / low 15 / mult factor 3 (21 of 21 specimens, counters 1..4)
UNUSED_COUNTER = (15, 15, 3)


class PllMap:
    """(block type, group name, gi) -> list per PLL path of CFF bit indices (group mux bits, LSB first)."""

    def __init__(self, flds):
        self.g = {}
        for f in flds:
            if f.btype not in PLL_BLOCKS:
                continue
            paths = []
            for site in f.sites:
                arr = np.concatenate([np.asarray(o, np.int64) for o in site]) if site else np.zeros(0, np.int64)
                paths.append((arr & 0x1FFFFFFF) if len(arr) and (arr >> 29 == 5).all() else None)
            self.g[(f.btype, f.name, f.gi)] = paths

    def value(self, cff, btype, path, name, gi=-1):
        idx = self.g[(btype, name, gi)][path]
        return None if idx is None else int(sum(int(cff[i]) << j for j, i in enumerate(idx)))

    def read(self, cff, btype, path):
        """{ 'NAME#gi': int } for every CFF-tagged group of one PLL path."""
        out = {}
        for (bt, nm, gi), paths in self.g.items():
            if bt == btype and path < len(paths) and paths[path] is not None:
                out[f"{nm}#{gi}"] = self.value(cff, bt, path, nm, gi)
        return out

    def enabled(self, cff, btype, path):
        return self.value(cff, btype, path, "PLL_ENABLE_PLL") == 1

    def used(self, cff):
        """[(PLL_k, btype, path)] of PLLs whose enable bit is set."""
        return [(k, bt, p) for k, (bt, p) in sorted(PLL_SITE.items()) if self.enabled(cff, bt, p)]

    def params(self, cff, btype, path):
        """Decoded parameters {m, n, c0..c4: (high, low, initial, kind), charge_pump} of one PLL path."""
        v = lambda nm, gi=-1: self.value(cff, btype, path, nm, gi)      # noqa: E731
        out = {"m": v("PLL_M_HIGH_COUNTER") + v("PLL_M_LOW_COUNTER"), "n": v("PLL_N_HIGH_COUNTER") + v("PLL_N_LOW_COUNTER"),
               "charge_pump": v("PLL_CHARGE_PUMP_CURRENT"), "loop_filter_r": v("PLL_LOOP_FILTER_R"), "loop_filter_c": v("PLL_LOOP_FILTER_C"),
               "usage_mode": v("PLL_USAGE_MODE"),
               "vco_post_scale": 2 if v("PLL_VCO_DIVIDE_BY_2") == 0 else 1}      # writer ASM_PLL_VCO_DIVIDE_BY_2: value = (post_scale == 2); 1-bit one-hot stores NOT value
        for c in range(5):
            h, lo, mf, pre = (v(nm, c) for nm in OUT_FIELDS)
            out[f"c{c}"] = ("bypass", 0, 0, 0) if (h, lo, mf) == UNUSED_COUNTER else ("counter", h, lo, pre)
        return out


def load(walk, names):
    return PllMap(F.fields(walk, names))


def read_cff(rbf, cff=None):
    return (cff or IO.Cff()).read(rbf)[0]


BASIC_PLL = "ddb_stingray_basic.pll"       # source: quartus common/devinfo/cycloneivgx text table (pll GPLL / MPLL blocks)


def basic_tables(path=None):
    """{key: list of ints} of the first `pll GPLL` block: charge_pump_current_bit, loop_filter_resistor_bit, loop_filter_capacitor_bit.
    List index = field value, entry = physical value (0 = unused code, -1 terminator)."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
    import toolchain
    path = path or os.path.join(os.path.dirname(toolchain.quartus_bin()), "common", "devinfo", "cycloneivgx", BASIC_PLL)
    out, seen = {}, 0
    for ln in open(path):
        t = ln.split()
        if t[:1] == ["pll"]:
            seen += 1
        elif seen == 1 and t and t[0] in ("charge_pump_current_bit", "loop_filter_resistor_bit", "loop_filter_capacitor_bit"):
            out[t[0]] = [int(x) for x in t[1:] if x != "-1"]
    return out


BANDWIDTH_GPLL = "ddb_stingray_bandwidth_gpll.pll"      # source: quartus common/devinfo/cycloneivgx text table "V3 - Cyclone IIIGX BW settings": (M*post lo, hi, ICP, R, C, ...)


def bandwidth_rows(path=None):
    """[(lo, hi, icp, r, c)] of the vendor bandwidth settings table (charge-pump / loop-filter field values per M * post-scale range)."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
    import toolchain
    path = path or os.path.join(os.path.dirname(toolchain.quartus_bin()), "common", "devinfo", "cycloneivgx", BANDWIDTH_GPLL)
    rows = []
    for ln in open(path):
        t = ln.split()
        if len(t) >= 5 and all(x.lstrip("-").isdigit() for x in t[:5]):
            rows.append(tuple(int(x) for x in t[:5]))
    return rows


def bandwidth_settings(m, post, rows=None):
    """(icp, r, c) for M * post; None when outside every range."""
    for lo, hi, icp, r, c in rows or bandwidth_rows():
        if lo <= m * post <= hi:
            return icp, r, c
    return None
