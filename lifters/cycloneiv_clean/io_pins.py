"""Cyclone IV GX package ball -> IO site -> class (used / unused / fixed / MISSING) for the pin-membership score (#168, #165).  Vendor-derived only.

- Ball -> pad: the part's package pkg ddb (`pkgpad.pins(count)`, count from device.db `part.pin_count`); pad -> site: die pad table order
  (Row I/O = HIO sites, Column I/O = VIO sites: io_decode/pkgpad chain), Dedicated Clock pads = asmdb blocks 60 (positive) / 61 (negative).
- Site class: `io_fields.Decoder.decode` (HIO / VIO); clock sites: (IOST, PCI clamp) equals an input state or an unused state of the decoded tables.
- Ambiguity is kept: `std_ambiguous` (CFF-identical standards: an equivalence class, ball membership unaffected), direction candidates > 1 = `direction_ambiguous`.
"""
import re

from . import io_decode as ID
from . import pkgpad as K

# source: asmdb block types of the IV die (docs/cycloneiv-clean-io.md: 60 DEDICATED_CLOCK, 61 DEDICATED_NEGATIVE_CLOCK; 10 sites each = 20 Dedicated Clock pads)
CLK_BLOCKS = (60, 61)
# source: pad function strings of the 20 `Dedicated Clock` pads ("DIFFCLK_6p" / "DIFFCLK_6n"): p pads -> block 60, n pads -> block 61, each in pad-table order
CLK_POLARITY = re.compile(r"DIFFCLK_\d+([pn])")
# source: scripts/cycloneiv_clean_io_pairs.py KINDS (pair-build kinds): a dedicated clock pad is an input
INPUT_KINDS = ("in", "regin")
IOST, CLAMP = "MIO_SELECT_IOST_DIRT", "MIO_USE_PCI_DIODE_CLAMP"


class PinMap:
    def __init__(self, io, dec):
        from . import asmdb_walk as W
        self.io, self.dec, self.chain = io, dec, io.chain
        self.pads = K.pads()
        site_pad = K.io_site_pads(self.pads)
        self.pad_site = {j: s for s, j in site_pad.items()}
        names = self.chain.names
        self.clk = {}                       # (block, k) -> {"iost": [cff idx], "clamp": [cff idx]}
        for o in self.chain.walk.groups():
            if o["btype"] not in CLK_BLOCKS or o["cls"] not in (5, 6, 7):
                continue
            nm = names.get(o["type"])
            if nm not in (IOST, CLAMP):
                continue
            n = len(o["bits"]) if o["cls"] == 7 else len(o["paths"])
            for s in range(n):
                bits = [a & 0x1FFFFFFF for a in W._site_bits(self.chain.walk, o, s) if a >> 29 == 5]
                self.clk.setdefault((o["btype"], s), {})["iost" if nm == IOST else "clamp"] = bits
        pol = {"p": [], "n": []}
        for j, p in enumerate(self.pads):
            if p["strs"][3] == "Dedicated Clock":
                pol[CLK_POLARITY.search(p["strs"][4])[1]].append(j)
        for pl, blk in (("p", 60), ("n", 61)):
            for k, j in enumerate(pol[pl]):
                self.pad_site[j] = (blk, k)
        self.used_input = {}                # width -> {(iost, clamp): {standard labels}}
        for s in dec.states:
            if s["kind"] in INPUT_KINDS:
                self.used_input.setdefault(s["width"], {}).setdefault((s["vec"][IOST], s["vec"][CLAMP]), set()).add(s["labels"]["standard"])
        self.unused = {(u["iost_width"], u["vector"][IOST], u["vector"][CLAMP]) for u in dec.unused if u["vector"]}
        self._maps = {}

    def ball_site(self, device):
        """{ball: site} for a part name; site = (5 | 6, k) IO site or (60 | 61, k) clock site."""
        count = K.package_pins(device)
        if count not in self._maps:
            pins = K.pins(count)
            self._maps[count] = {pins[i]["strs"][0]: self.pad_site[j] for i, j in K.pin_pad(pins).items() if j in self.pad_site}
        return self._maps[count]

    def classify(self, val, device):
        """{ball: {"class", "dir", "std_ambiguous"}} for every ball with a site; val = CFF bit values (Cff.read)."""
        out = {}
        for ball, s in self.ball_site(device).items():
            if s[0] in CLK_BLOCKS:
                g = self.clk[s]
                iost = "".join(str(int(val[a])) for a in g["iost"])
                clamp = "".join(str(int(val[a])) for a in g["clamp"])
                std = self.used_input.get(len(iost), {}).get((iost, clamp))
                if std:
                    out[ball] = {"class": "used", "dir": "input", "std_ambiguous": len(std) > 1}
                else:
                    out[ball] = {"class": "unused" if (len(iost), iost, clamp) in self.unused else "MISSING", "dir": None, "std_ambiguous": False}
                continue
            r = self.dec.decode(s, ID.site_vector(self.chain, val, s))
            e = {"class": r["class"], "dir": None, "std_ambiguous": False}
            if r["class"] == "used":
                d = r["direction"]
                e["dir"] = d["value"] if d["status"] != "ambiguous_MISSING" else "ambiguous"
                e["std_ambiguous"] = r["standard"]["status"] == "ambiguous_MISSING"
            out[ball] = e
        return out
