#!/usr/bin/env python3.15t
"""Cyclone V native decoder (Bluebird): .rbf bytes -> per-tile named-feature `.bt` model.

No mistral-cv. Tables come from scripts/cyclonev_native_tables.py (Mistral `data/` text as bootstrap
source). Output grammar is the one lifters/cyclonev_lift.py reads (m/o/r/s/i lines).
Oracle-backed corrections to the bootstrap tables: scripts/cyclonev_native_overrides.py.
Format, verification and gaps: docs/cyclonev-native-decoder.md.

  python3.15t scripts/cyclonev_decode.py IN.rbf OUT.bt [--device 5CEBA4U19C8] [--no-overrides] [--claims OUT.json]
"""
import argparse
import json
import logging
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_native_tables as nt  # noqa: E402

log = logging.getLogger("cyclonev_decode")

# ---- rbf container ------------------------------------------------------------------------------


def crc16(buf):
    """CRC-16 as libmistral crc16(): init 0xffff, LSB-first, poly 0xa001 (== CRC-16/MODBUS)."""
    acc = 0xFFFF
    for b in buf:
        acc ^= b
        for _ in range(8):
            acc = (acc >> 1) ^ 0xA001 if acc & 1 else acc >> 1
    return acc


_CRC16_T = None


def _crc16_table():
    global _CRC16_T
    if _CRC16_T is None:
        t = np.zeros(256, np.uint16)
        for i in range(256):
            a = i
            for _ in range(8):
                a = (a >> 1) ^ 0xA001 if a & 1 else a >> 1
            t[i] = a
        _CRC16_T = t
    return _CRC16_T


def crc16_rows(rows):
    """CRC-16 of each row of a (n, len) uint8 array."""
    t = _crc16_table()
    acc = np.full(rows.shape[0], 0xFFFF, np.uint16)
    for k in range(rows.shape[1]):
        acc = (acc >> 8) ^ t[(acc ^ rows[:, k]) & 0xFF]
    return acc


def edcrc_contrib(nbits):
    """GF(2) contribution words of a 1 at stream step k, plus the init term (libmistral crc32(), poly 0xf4acfb13)."""
    poly = 0xF4ACFB13

    def step0(a):
        return ((a << 1) & 0xFFFFFFFF) ^ (poly if a >> 31 else 0)

    c = np.zeros(nbits, np.uint32)
    c[nbits - 1] = poly
    for k in range(nbits - 1, 0, -1):
        c[k - 1] = step0(int(c[k]))
    init = 1
    for _ in range(nbits):
        init = step0(init)
    return c, init


def nibble_decompress(buf, out_len):
    """libmistral rbf_load nibble zero-suppression (low nibble first)."""
    nib = np.empty(len(buf) * 2, np.uint8)
    nib[0::2] = buf & 0xF
    nib[1::2] = buf >> 4
    nib = nib.tolist()
    out = bytearray(out_len)
    p, o, n = 0, 0, len(nib)
    while o < out_len:
        if p >= n:
            raise ValueError("nibble stream ended early")
        k = nib[p]
        p += 1
        v = 0
        if k & 1:
            v = nib[p]
            p += 1
        if k & 2:
            v |= nib[p] << 4
            p += 1
        out[o] = v
        w = 0
        if k & 4:
            w = nib[p]
            p += 1
        if k & 8:
            w |= nib[p] << 4
            p += 1
        out[o + 1] = w
        o += 2
    return bytes(out), p


def nibble_compress(raw):
    """Inverse of nibble_decompress (rbf_save); pads the last byte with 0xf nibbles."""
    a = np.frombuffer(raw, np.uint8)
    sv1, sv2 = a[0::2], a[1::2]
    key = ((sv1 & 0x0F) != 0) * 1 | ((sv1 & 0xF0) != 0) * 2 | ((sv2 & 0x0F) != 0) * 4 | ((sv2 & 0xF0) != 0) * 8
    out = []
    k, s1, s2 = key.tolist(), sv1.tolist(), sv2.tolist()
    for i in range(len(k)):
        m = k[i]
        out.append(m)
        if m & 1:
            out.append(s1[i] & 0xF)
        if m & 2:
            out.append(s1[i] >> 4)
        if m & 4:
            out.append(s2[i] & 0xF)
        if m & 8:
            out.append(s2[i] >> 4)
    while len(out) & 1:
        out.append(0xF)
    n = np.array(out, np.uint8)
    return (n[0::2] | (n[1::2] << 4)).astype(np.uint8).tobytes()


class Geometry:
    def __init__(self, g):
        self.g = g
        self.sx, self.sy = g["cram_sx"], g["cram_sy"]
        self.fs = g["frame_size"]
        self.pram_sizes = list(g["pram_sizes"]) + [0] * (32 - len(g["pram_sizes"]))
        self.mpram = max(self.pram_sizes)
        self.pram_frame_bytes = (self.fs + 2) * 4
        self.oram_frame_bytes = self.pram_frame_bytes + 104
        self.pram_blocks = (self.mpram + self.fs - 1) // self.fs
        self.padding = (64 - (self.sy & 63)) ^ 32
        self.cram_frame_size = self.sy + 256 + self.padding
        self.cfb = self.cram_frame_size // 8
        self.framed_bytes = self.sx * self.cfb
        self.cram_frame_bits = self.fs - 7
        self.offset = self.padding - 32
        self.cram_off = self.oram_frame_bytes + self.pram_frame_bytes * self.pram_blocks

    def slot_pos(self, y):
        """Frame bit position of CRAM row y (y+offset may be negative for y<32: no slot)."""
        yy = y + self.offset
        return 224 + (31 ^ (yy // self.cram_frame_bits)) + 32 * (yy % self.cram_frame_bits)


class Bits:
    """Decoded bit planes: cram (flat sx*sy uint8), pram[32] (uint8), oram[32] (python int, 40 bits)."""

    def __init__(self, geo):
        self.geo = geo
        self.cram = np.zeros(geo.sx * geo.sy, np.uint8)
        self.pram = [np.zeros(n, np.uint8) for n in geo.pram_sizes]
        self.oram = [0] * 32
        self.framed = None          # decompressed CRAM frames (bytes) for accounting
        self.compressed = None
        self.raw = None


def oram_get(oram, strip, bit):
    return (oram[strip] >> bit) & 1


class ContainerError(ValueError):
    pass


def container_problems(a, geo, framed=None):
    """Structural checks of the .rbf container (header, option checksum, PRAM page CRCs, CRAM frame sync)."""
    pr = []
    if not (a[:0x80] == 0xFF).all() or bytes(a[0x80:0x84]) != b"jjjj":
        pr.append("no 0xff*0x80 + 'jjjj' option-frame header")
    if len(a) > 0x128 and cd_crc16(a[0x84:0x126]) != (int(a[0x126]) | (int(a[0x127]) << 8)):
        pr.append("option-frame checksum mismatch")
    for pg in range(geo.pram_blocks):
        off = geo.oram_frame_bytes + pg * geo.pram_frame_bytes
        seg = a[off:off + geo.pram_frame_bytes]
        if len(seg) < geo.pram_frame_bytes or cd_crc16(seg[:-2]) != (int(seg[-2]) | (int(seg[-1]) << 8)):
            pr.append("PRAM page %d CRC mismatch" % pg)
            break
    if framed is not None:
        f = np.frombuffer(framed, np.uint8)
        if bytes(f[:3]) != b"\x84\x3e\x01" or bytes(f[(geo.sx - 1) * geo.cfb:(geo.sx - 1) * geo.cfb + 3]) != b"\x42\x9f\x00":
            pr.append("CRAM frame sync bytes missing")
    return pr


def cd_crc16(buf):
    return crc16(bytes(buf))


def load_rbf(tables, data, geo=None, need_framed=False, strict=True):
    geo = geo or Geometry(tables["geom"])
    b = Bits(geo)
    a = np.frombuffer(data, np.uint8)
    b.raw = a
    if len(a) < geo.cram_off:
        raise ContainerError(f"rbf too short ({len(a)} < {geo.cram_off}): wrong die?")
    b.problems = container_problems(a, geo)
    if strict and b.problems:
        raise ContainerError("not a Cyclone V .rbf of this die: " + "; ".join(b.problems) + " (--force to decode anyway)")
    # ORAM: 32 strips x 40 bits
    for strip in range(32):
        for bit in range(40):
            if a[0x84 + (strip >> 3) + (bit << 2)] & (0x80 >> (strip & 7)):
                b.oram[strip] |= 1 << bit
    # PRAM
    for bit in range(32):
        cnt = geo.pram_sizes[bit]
        if not cnt:
            continue
        i = np.arange(cnt)
        base = geo.mpram - i - 1
        idx = geo.oram_frame_bytes + 4 + (bit >> 3) + base * 4 + (base // geo.fs) * 8
        b.pram[bit] = ((a[idx] & (1 << (bit & 7))) != 0).astype(np.uint8)
    comp_dis = options_compression_dis(tables, b)
    region = a[geo.cram_off:]
    if not strict and len(region) < geo.framed_bytes and comp_dis:
        region = np.concatenate([region, np.zeros(geo.framed_bytes - len(region), np.uint8)])
    if not comp_dis:
        framed, used = nibble_decompress(region, geo.framed_bytes)
        b.compressed = (geo.cram_off, used)
    else:
        if len(region) < geo.framed_bytes:
            raise ValueError("uncompressed CRAM region short")
        framed = bytes(region[:geo.framed_bytes])
    b.framed = framed
    b.problems += container_problems(a, geo, framed)[len(b.problems):] if False else []
    if strict:
        extra = [p for p in container_problems(a, geo, framed) if p.startswith("CRAM frame sync")]
        if extra:
            raise ContainerError("not a Cyclone V .rbf of this die: " + "; ".join(extra) + " (--force to decode anyway)")
    f = np.frombuffer(framed, np.uint8)
    # fold: CRAM (x, y>=32) <- frame x bit slot
    ys = np.arange(32, geo.sy)
    yy = ys + geo.offset
    ya, yb = yy % geo.cram_frame_bits, yy // geo.cram_frame_bits
    pos = 224 + (31 ^ yb) + 32 * ya
    byte_i, bit_i = pos >> 3, (pos & 7).astype(np.uint8)
    cram2 = b.cram.reshape(geo.sy, geo.sx)
    for x in range(geo.sx):
        d = f[x * geo.cfb:(x + 1) * geo.cfb]
        cram2[32:, x] = (d[byte_i] >> bit_i) & 1
    return b


def options_compression_dis(tables, b):
    for m in tables["muxes"]:
        if m["dump_target"] == "opt" and m["mux"] == "compression_dis":
            (x, y), = m["bits"][0]
            return oram_get(b.oram, x, y)
    raise ValueError("compression_dis not in opt-mux")


# ---- naming helpers -----------------------------------------------------------------------------

def rname(tb, key):
    t = tb["routes"]["type_names"][key >> 24]
    return f"{t}.{(key >> 17) & 0x7f:03d}.{(key >> 10) & 0x7f:03d}.{key & 0x3ff:04d}"


def pname(p):
    bt, x, y, pt, bi, pi = p
    if pt is None:
        return f"{bt}.{x:03d}.{y:03d}" if bi == -1 else f"{bt}.{x:03d}.{y:03d}.{bi}"
    if bi == -1:
        return f"{bt}.{x:03d}.{y:03d}:{pt}" if pi == -1 else f"{bt}.{x:03d}.{y:03d}:{pt}.{pi}"
    return f"{bt}.{x:03d}.{y:03d}.{bi}:{pt}" if pi == -1 else f"{bt}.{x:03d}.{y:03d}.{bi}:{pt}.{pi}"


def rparts(key):
    return key >> 24, (key >> 17) & 0x7f, (key >> 10) & 0x7f, key & 0x3ff


HMC_BYPASS = {}
for _n in ("ADDRACLR ADDRDOUT BAACLR BADOUT CASNACLR CASNDOUT CKDOUT CKEACLR CKEDOUT CKNDOUT CSNACLR CSNDOUT DMDOUT "
           "DQDOUT DQOE DQSBDOUT DQSBOE DQSDOUT DQSOE ODTACLR ODTDOUT RASNACLR RASNDOUT RESETNACLR RESETNDOUT "
           "WENACLR WENDOUT").split():
    HMC_BYPASS["PHYDDIO" + _n] = "IOINT" + _n
    HMC_BYPASS["IOINT" + _n] = "PHYDDIO" + _n
HMC_BYPASS["DDIOPHYDQDIN"] = "IOINTDQDIN"
HMC_BYPASS["IOINTDQDIN"] = "DDIOPHYDQDIN"

LAB_GOUT = ["E0", "F0", "A", "B", "C", "D", "E1", "F1"]


# ---- the model -----------------------------------------------------------------------------------

class Model:
    """Tables + decoded planes -> features. `claims` collects every bit position a feature reads."""

    def __init__(self, tables, overrides=None, claims=True, compat=False):
        self.compat = compat
        self.t = tables
        self.geo = Geometry(tables["geom"])
        self.g = tables["geom"]
        self.sx, self.sy = self.geo.sx, self.geo.sy
        self.r = tables["routes"]
        self.tn = self.r["type_names"]
        self.tid = {n: i for i, n in enumerate(self.tn)}
        self.pins = tables["pins"]
        self.tile_types = tables["tile_types"]
        self.idcode = tables["model"]["idcode"]
        self.ov = overrides
        self.mux = {}
        for m in tables["muxes"]:
            self.mux.setdefault(m["dump_target"], []).append(m)
        if overrides:
            overrides.apply(self)
        # p2r / p2p indexes (file order, first match wins as in libmistral)
        self.p2r_rn = {}
        self.p2r_pn = {}
        for pn, rk in tables["p2r"]:
            self.p2r_rn.setdefault(rk, pn)
            self.p2r_pn.setdefault(pn, rk)
        self.p2p_from = {}
        self.p2p_to = {}
        for s, d in tables["p2p"]:
            self.p2p_from.setdefault(s, []).append(d)
            self.p2p_to.setdefault(d, s)
        self.claims = {"cram": [], "pram": [[] for _ in range(32)], "oram": []} if claims else None
        self.mux_index = None

    # -- bit readers --
    def _claim_cram(self, pos, cls):
        if self.claims is not None:
            self.claims["cram"].append((cls, pos))

    def pos2bit(self, p):
        return (2 + 86 * p[1]) * self.sx + self.g["x_to_bx"][p[0]]

    # -- pin lookup --
    def pin_pos(self, p, idx):
        return self.pins.get((p[0], p[1], idx))

    def pin_pnode(self, pn):
        if pn is None:
            return None
        if pn[0] == "GPIO" and pn[4] != -1:
            return self.pin_pos((pn[1], pn[2]), pn[4])
        if pn[0] == "HMC":
            bp = self.hmc_bypass(pn)
            if bp is None:
                return None
            gp = self.p2p_to.get(bp)
            if gp is None:
                for g in self.p2p_from.get(bp, []):
                    if g[0] == "GPIO":
                        gp = g
                        break
            if gp is None or gp[0] != "GPIO" or gp[4] == -1:
                return None
            return self.pin_pos((gp[1], gp[2]), gp[4])
        return None

    def hmc_bypass(self, pn):
        if pn[0] != "HMC" or pn[3] not in HMC_BYPASS:
            return None
        return ("HMC", pn[1], pn[2], HMC_BYPASS[pn[3]], pn[4], pn[5])

    # -- rnode -> pnode (cv-rmux.cc rnode_to_pnode) --
    def rnode_to_pnode(self, key):
        ti, x, y, z = rparts(key)
        t = self.tn[ti]
        tt = self.tile_types.get((x, y), "T_EMPTY")
        P = (x, y)
        if tt in ("T_LAB", "T_MLAB"):
            bt = "LAB" if tt == "T_LAB" else "MLAB"
            if t == "GOUT":
                if z < 80:
                    return (bt, x, y, LAB_GOUT[z & 7], z // 8, -1)
                return (bt, x, y, "DATAIN", -1, z - 80)
            if t == "GIN":
                return (bt, x, y, ("FFT0", "FFT1", "FFB0", "FFB1")[z & 3], z // 4, -1)
            if t == "LD":
                return (bt, x, y, ("FFT1L", "FFB1L")[z & 1], z // 2, -1)
            if t == "TCLK":
                return (bt, x, y, "CLKIN", -1, z) if z < 2 else (bt, x, y, "ACLR", -1, z - 2)
        if tt == "T_DSP":
            if t == "GOUT":
                if z <= 8:
                    return ("DSP", x, y, "DATAIN", 6, z)
                if z <= 17:
                    return ("DSP", x, y, "DATAIN", 7, z - 9)
                if z <= 26:
                    return ("DSP", x, y, "DATAIN", 8, z - 18)
                if z <= 29:
                    return ("DSP", x, y, "DATAIN", 9, z - 27)
                if z == 32:
                    return ("DSP", x, y, "NEGATE", -1, -1)
                if z == 33:
                    return ("DSP", x, y, "LOADCONST", -1, -1)
                if z == 34:
                    return ("DSP", x, y, "ACCUMULATE", -1, -1)
                if z == 35:
                    return ("DSP", x, y, "SUB", -1, -1)
                if 36 <= z <= 37:
                    return ("DSP", x, y, "ACLR", -1, 37 - z + 2)
                if 38 <= z <= 46:
                    return ("DSP", x, y, "DATAIN", 11, 46 - z)
                if 47 <= z <= 55:
                    return ("DSP", x, y, "DATAIN", 10, 55 - z)
                if 56 <= z <= 61:
                    return ("DSP", x, y, "DATAIN", 9, 61 - z + 3)
                return ("DSP", x, y, "UNK_IN", -1, z)
            if t == "GIN":
                if z <= 17:
                    return ("DSP", x, y, "RESULT", -1, z + 18)
                if z <= 36:
                    return ("DSP", x, y, "RESULT", -1, z - 18 + 55)
            if t == "TCLK":
                return ("DSP", x, y, "CLKIN", -1, z) if z <= 2 else ("DSP", x, y, "ACLR", -1, z - 3)
        if tt == "T_DSP2":
            p1 = (x, y - 1)
            if t == "GOUT":
                if z <= 8:
                    return ("DSP", *p1, "DATAIN", 0, z)
                if z <= 17:
                    return ("DSP", *p1, "DATAIN", 1, z - 9)
                if z <= 26:
                    return ("DSP", *p1, "DATAIN", 2, z - 18)
                if z <= 29:
                    return ("DSP", *p1, "DATAIN", 3, z - 27)
                m = {32: ("CLKIN", 5), 33: ("ENABLE", 2), 34: ("CLKIN", 4), 35: ("ENABLE", 1), 36: ("CLKIN", 3),
                     37: ("ENABLE", 0)}
                if z in m:
                    return ("DSP", *p1, m[z][0], -1, m[z][1])
                if 38 <= z <= 46:
                    return ("DSP", *p1, "DATAIN", 5, 46 - z)
                if 47 <= z <= 55:
                    return ("DSP", *p1, "DATAIN", 4, 55 - z)
                if 56 <= z <= 61:
                    return ("DSP", *p1, "DATAIN", 3, 61 - z + 3)
                return ("DSP", *p1, "UNK_IN", -1, z + 64)
            if t == "GIN":
                if z <= 17:
                    return ("DSP", *p1, "RESULT", -1, z)
                if z <= 36:
                    return ("DSP", *p1, "RESULT", -1, z - 18 + 36)
        if tt == "T_M10K":
            if t == "GOUT":
                return self._m10k_gout(x, y, z)
            if t == "GIN":
                return ("M10K", x, y, "DATABOUT", -1, z - 20) if z >= 20 else ("M10K", x, y, "DATAAOUT", -1, z)
            if t == "TCLK":
                return ("M10K", x, y, "CLKIN", -1, z)
        return self.p2r_rn.get(key)

    @staticmethod
    def _m10k_gout(x, y, z):
        def M(port, pi):
            return ("M10K", x, y, port, -1, pi)
        if z < 2:
            return M("BYTEENABLEA", z)
        if z < 5:
            return M("ADDRA", (1, 2, 3)[z - 2])
        if z < 6:
            return M("CLKIN", 6)
        if z < 7:
            return M("ACLR", 0)
        if z < 8:
            return ("M10K", x, y, "ADDRSTALLA", -1, -1)
        if z < 9:
            return ("M10K", x, y, "ADDRSTALLB", -1, -1)
        if z < 17:
            return M("ADDRA", z - 9 + 4)
        if z < 18:
            return M("WREN", 0)
        if z < 20:
            return M("ENABLE", z - 18)
        if z < 21:
            return M("RDEN", 0)
        if z < 23:
            return None
        if z < 25:
            return M("BYTEENABLEB", z - 23)
        if z < 28:
            return M("ADDRB", (3, 2, 1)[z - 25])
        if z < 29:
            return M("CLKIN", 7)
        if z < 30:
            return M("ACLR", 1)
        if z < 38:
            return M("ADDRB", 4 + (7 - (z - 30)))
        if z < 39:
            return M("WREN", 1)
        if z < 41:
            return M("ENABLE", z - 39 + 2)
        if z < 42:
            return M("RDEN", 1)
        if z < 43:
            return M("ADDRA", 0)
        if z < 64:
            bits = (0, 20, 10, 30, 1, 21, 11, 31, 2, 22, 12, 32, 3, 23, 13, 33, 4, 24, 14, 34, 5)
            bit = bits[z - 43]
            return M("DATAAIN" if bit < 20 else "DATABIN", bit if bit < 20 else bit - 20)
        if z < 65:
            return M("ADDRB", 0)
        if z < 84:
            bits = (39, 19, 29, 9, 38, 18, 28, 8, 37, 17, 27, 7, 36, 16, 26, 6, 35, 15, 25)
            bit = bits[z - 65]
            return M("DATAAIN" if bit < 20 else "DATABIN", bit if bit < 20 else bit - 20)
        return None

    # -- options / settings --
    def _bits_matrix(self, plane, bases, offs):
        return plane[bases[:, None] + offs[None, :]]

    def _decode_group(self, btype, mlist, tiles, mode, solve):
        """Read all muxes of `mlist` over `tiles` = [(pos, base, variant)]. Yields setting dicts (non-default only)."""
        out = []
        for m in mlist:
            span, stype, bc = m["span"], m["stype"], m["bcount"]
            vt = [t for t in tiles if m["variant"] in (-1, t[2])]
            if not vt:
                continue
            for i in range(span):
                midx = -1 if span == 1 else i
                bits = m["bits"][i]
                M = self._matrix(mode, vt, bits)
                self._read_rows(out, btype, m, vt, M, midx, i, stype, bc, solve)
        return out

    def _matrix(self, mode, vt, bits):
        n, bc = len(vt), len(bits)
        if mode == "cram":
            bases = np.array([t[1] for t in vt], np.int64)
            offs = np.array([b[1] * self.sx + b[0] for b in bits], np.int64)
            pos = bases[:, None] + offs[None, :]
            self._claim_cram(pos, "bmux")
            return self.bits.cram[pos]
        if mode == "oram":
            M = np.zeros((n, bc), np.uint8)
            for k, (x, y) in enumerate(bits):
                M[:, k] = oram_get(self.bits.oram, x, y)
            if self.claims is not None:
                self.claims["oram"].extend((x, y) for x, y in bits)
            return M
        if mode == "dcram":
            dc = self.t["dcram"]
            M = np.zeros((n, bc), np.uint8)
            for r, t in enumerate(vt):
                for k, b in enumerate(bits):
                    pos = dc[(t[1] & 0xFFFF) + b]
                    M[r, k] = self.bits.cram[pos]
                    self._claim_cram(np.array([pos]), "bmux")
            return M
        M = np.zeros((n, bc), np.uint8)       # pram
        for r, t in enumerate(vt):
            base = t[1]
            strip = (base >> 16) & 31
            pl = self.bits.pram[strip]
            for k, b in enumerate(bits):
                pos = (base & 0xFFFF) + b
                if base & (1 << 23):
                    pos = dqs16_adjust(pos, b, bool(base & (1 << 22)))
                M[r, k] = pl[pos]
                if self.claims is not None:
                    self.claims["pram"][strip].append(pos)
        return M

    def _read_rows(self, out, btype, m, vt, M, midx, idx, stype, bc, solve):
        name = m["mux"].upper()
        n = len(vt)
        if stype == "r":
            packed = np.packbits(M, axis=1, bitorder="little")
            for r in range(n):
                rb = bytes(packed[r])
                if not solve.ram_default(btype, vt[r], idx, m, rb, M[r]):
                    out.append((btype, vt[r][0], name, midx, "r", bc, rb))
            return
        weights = (1 << np.arange(bc, dtype=np.uint64)) if bc <= 63 else None
        if weights is None:
            raise ValueError(f"{name}: {bc}-bit non-RAM mux")
        vals = (M.astype(np.uint64) * weights[None, :]).sum(axis=1)
        if stype == "b":
            for r in range(n):
                v = int(vals[r])
                if v != solve.bool_default(btype, vt[r], idx, m):
                    out.append((btype, vt[r][0], name, midx, "b", v))
            return
        ents = m["values"]
        dflt = m.get("default_value_idx")
        lookup = {mask: k for k, (mask, _) in enumerate(ents)}
        for r in range(n):
            v = int(vals[r])
            k = lookup.get(v)
            if stype == "m":
                sel = ents[k][1].upper() if k is not None else "BMNONE"
                if k is None:
                    isdef = False
                elif dflt is None:
                    dn = solve.m_default(btype, vt[r], idx, m)
                    isdef = dn is not None and sel == dn
                else:
                    isdef = k == dflt
                if not isdef:
                    out.append((btype, vt[r][0], name, midx, "m", sel))
            else:
                num = ents[k][1] if k is not None else -1
                isdef = k is not None and dflt is not None and k == dflt
                if not isdef:
                    out.append((btype, vt[r][0], name, midx, "n", num))

    def settings(self):
        if getattr(self, "_settings", None) is None:
            self._settings = self._settings_uncached()
        return self._settings

    def _settings_uncached(self):
        t, g = self.t, self.g
        S = Solve(self)
        res = []
        for tp, key, mk in (("T_LAB", "LAB", "lab"), ("T_MLAB", "MLAB", "mlab"), ("T_M10K", "M10K", "m10k"),
                            ("T_DSP", "DSP", "dsp")):
            tiles = [(p, self.pos2bit(p), -1) for p in t["pos"][tp]]
            res += self._decode_group(key, self.mux[mk], tiles, "cram", S)
        pram_groups = []
        gp = [(r["pos"], r["pram"], (r["pram"] >> 24) & 1) for r in t["iob"] if r["idx"] == 0 and r["btype"] == "gpio"]
        pram_groups.append(("GPIO", "gpio", gp, "pram"))
        pram_groups.append(("DQS16", "dqs16", [(p, b, -1) for p, b in t["dqs16"]], "pram"))
        fx = {k: v for (k, _), v in zip(nt.FIXED_BLOCKS, t["fixed"])}
        for key, mk, src in (("FPLL", "fpll", "fpll"), ("CMUXCR", "cmuxcr", "cmuxc"), ("CMUXVR", "cmuxvr", "cmuxv"),
                             ("CMUXVG", "cmuxvg", "cmuxv"), ("CMUXHR", "cmuxhr", "cmuxh"), ("CMUXHG", "cmuxhg", "cmuxh"),
                             ("DLL", "dll", "dll"), ("HSSI", "hssi", "hssi"), ("CBUF", "cbuf", "cbuf"),
                             ("LVL", "lvl", "lvl"), ("SERPAR", "serpar", "serpar"), ("TERM", "term", "term"),
                             ("HIP", "hip", "hip"), ("HMC", "hmc", "hmc")):
            pram_groups.append((key, mk, [(p, b, -1) for p, b in fx[src] if p is not None], "pram"))
        for key, mk, tiles, mode in pram_groups:
            res += self._decode_group(key, self.mux[mk], tiles, mode, S)
        p3 = [(p, b, (b >> 24) & 1) for p, b in fx["pma3"] if p is not None]
        res += self._decode_group("PMA3", self.mux["pma3"], p3, "pram", S)
        res += self._decode_group("PMA3", self.mux["pma3c"], [(p, 18 * ((b >> 24) & 3), -1) for p, b, _ in p3],
                                  "dcram", S)
        return res

    def options(self):
        S = Solve(self)
        return self._decode_group("BNONE", self.mux["opt"], [((0, 0), 0, -1)], "oram", S)

    # -- routing --
    def route_values(self):
        """Per mux: (val, slot, src) arrays."""
        r = self.r
        pats = self.t["patterns"]
        n = len(r["dest"])
        val = np.zeros(n, np.uint32)
        slot = np.full(n, -1, np.int32)
        src = np.zeros(n, np.uint32)
        W = self.sx
        for p in np.unique(r["pat"]):
            if p == 0xFE:
                continue
            pat = pats[p]
            idx = np.nonzero(r["pat"] == p)[0]
            fw = r["fw"][idx].astype(np.int64)
            v = np.zeros(len(idx), np.uint32)
            xy = self.t["rxy"][pat["o_xy"] * 2:(pat["o_xy"] + pat["bits"]) * 2].reshape(-1, 2)
            allpos = []
            for k in range(pat["bits"]):
                pos = fw + int(xy[k, 0]) + int(xy[k, 1]) * W
                allpos.append(pos)
                v |= self.bits.cram[pos].astype(np.uint32) << k
            if self.claims is not None:
                self._claim_cram(np.concatenate(allpos), "route")
            vh = (v % pat["hashdiv"]).astype(np.int64)
            s = self.t["rvhash"][pat["o_vhash"] + vh].astype(np.int32)
            ok = s >= 0
            vals = self.t["rvals"]
            sj = np.where(ok, s, 0)
            ok &= vals[pat["o_vals"] + sj] == v
            ok &= sj < pat["span"]
            s = np.where(ok, s, -1)
            val[idx] = v
            slot[idx] = s
            sel = r["src"][r["src_off"][idx] + np.where(ok, s, 0)]
            src[idx] = np.where(ok, sel, 0)
        return val, slot, src

    def routes(self):
        r = self.r
        val, slot, src = self.route_values()
        pats = self.t["patterns"]
        pat = r["pat"]
        dest = r["dest"]
        defv = np.array([p["defv"] for p in pats] + [0] * 256, np.uint32)[pat]
        isdef = val == defv
        mux_of = {int(k): i for i, k in enumerate(dest)}
        self.mux_index = mux_of
        self.route_val, self.route_slot, self.route_src, self.route_isdef = val, slot, src, isdef
        reg = pat != 0xFE
        sel = reg & (slot >= 0) & (src != 0)
        links = []
        unknown = []
        raw_src = []
        tn = self.tid
        dcmux, tclk, sclk = tn.get("DCMUX", -1), tn.get("TCLK", -1), tn.get("SCLK", -1)
        for i in np.nonzero(sel)[0]:
            d, s = int(dest[i]), int(src[i])
            raw_src.append(s)
            if self.compat:
                # libmistral passes an rnode_coords where an rnode_index is expected (bool -> index 1): the
                # "is default" test reads a fixed node, not the mux in question; on e50f it is always true.
                if (d >> 24) == sclk or ((d >> 24) == dcmux and (s >> 24) == tclk):
                    continue
            else:
                if (d >> 24) == dcmux and (s >> 24) == tclk:
                    j = mux_of.get(s)
                    if j is not None and isdef[j]:
                        continue
                if (d >> 24) == sclk and isdef[i]:
                    continue
            links.append((s, d))
        for i in np.nonzero(reg & ~sel & ~isdef)[0]:
            unknown.append((int(dest[i]), int(val[i]), int(pat[i])))
        # pattern 0xfe chains: active iff a downstream selected mux reaches them
        fe = {int(dest[i]): int(r["src"][r["src_off"][i]]) for i in np.nonzero(pat == 0xFE)[0]}
        active = set()
        stack = [s for s in raw_src if s in fe]
        while stack:
            x = stack.pop()
            if x in active:
                continue
            active.add(x)
            up = fe[x]
            if up in fe:
                stack.append(up)
        for x in active:
            if fe[x]:
                links.append((fe[x], x))
        if not self.compat:
            # LAB clock source taken from fabric (CLKA/CLKB_SEL = DIN): a mux the routing tables do not carry
            tid = self.tid
            for st in self.settings():
                if st[0] in ("LAB", "MLAB") and st[2] in ("CLKA_SEL", "CLKB_SEL") and st[5] in ("DIN0", "DIN1"):
                    k = 0 if st[2] == "CLKA_SEL" else 1
                    x, y = st[1]
                    links.append((nt.rkey(tid["GOUT"], x, y, 80 + k), nt.rkey(tid["TCLK"], x, y, k)))
        self.route_unknown = unknown
        return links

    def forced_ones(self):
        """Constant-1 CRAM bits (`<die>-1.txt`): claimed as feature class `one`; returns how many are set."""
        pos = np.array(self.t["ones"], np.int64)
        if len(pos):
            self._claim_cram(pos, "one")
        return int(self.bits.cram[pos].sum()), len(pos)

    def inverters(self):
        res = []
        for node, pos, dflag in self.t["inv"]:
            if self.claims is not None:
                self._claim_cram(np.array([pos]), "inv")
            v = int(self.bits.cram[pos])
            res.append((node, v, self.inv_default(node, dflag)))
        return res

    def inv_default(self, node, dflag):
        if dflag in ("0", "1"):
            return int(dflag)
        pn = self.p2r_rn.get(node)
        kind = None
        if pn is not None:
            b, pt = pn[0], pn[3]
            if b in ("CTRL", "CMUXCR", "CMUXHG", "CMUXHR", "CMUXVG", "CMUXVR", "DLL", "DQS16", "HIP", "LVL", "SERPAR",
                     "TERM"):
                return 0
            if b == "FPLL":
                return 1 if pt in ("CLKEN", "EXTSWITCH0") else 0
            if b == "HSSI":
                return 1 if ((pt == "PMA_PMA_RESERVED_IN" and pn[5] == 0) or pt == "SMRT_PACK_PLD_8G_TXELECIDLE") else 0
            if b == "GPIO":
                kind = "GP"
            elif b == "HMC":
                kind = "HMC"
        else:
            t = self.tn[node >> 24]
            if t in ("DCMUX", "GOUT"):
                return 0
        if kind is None:
            return -1
        pnode = self.rnode_to_pnode(node)
        if pnode is None:
            return 0
        if kind == "GP":
            if pnode[3] not in ("DATAOUT", "OEIN"):
                return 0
            wired = self.pin_pos((pnode[1], pnode[2]), pnode[4]) is not None
            if pnode[3] == "DATAOUT" or pnode[5] == 0:
                return 0 if wired else 1
            return 1 if wired else 0
        bp = self.hmc_bypass(pnode)
        if bp is None:
            return 0
        gpio = self.p2p_to.get(bp)
        if gpio is None:
            for gp in self.p2p_from.get(bp, []):
                if gp[0] == "GPIO":
                    gpio = gp
                    break
        if gpio is None or gpio[3] not in ("OEIN", "DATAOUT"):
            return 0
        wired = self.pin_pos((gpio[1], gpio[2]), gpio[4]) is not None
        if gpio[3] == "DATAOUT":
            return 0 if wired else 1
        return 1 if wired else 0

    # -- the .bt text --
    def bt_lines(self):
        self.ones_set = self.forced_ones()
        L = [f"m {self.t['model']['name']}"]
        for s in self.options():
            if s[4] == "r":
                L.append(f"o {s[2]} {fmt_ram(s[6], s[5])}")
            else:
                L.append(f"o {s[2]} {s[5]}")
        for sk, dk in self.routes():
            sp, dp = self.rnode_to_pnode(sk), self.rnode_to_pnode(dk)
            line = f"r {pname(sp) if sp else rname(self.t, sk)} {pname(dp) if dp else rname(self.t, dk)}"
            ps, pd = self.pin_pnode(sp), self.pin_pnode(dp)
            if ps:
                line += f" ; {ps}"
            if pd:
                line += (" " if ps else " ; ") + pd
            L.append(line)
        for s in self.settings():
            btype, pos, name, midx, kind = s[0], s[1], s[2], s[3], s[4]
            head = f"s {btype}.{pos[0]:03d}.{pos[1]:03d}:{name}" + ("" if midx == -1 else f".{midx}")
            val = fmt_ram(s[6], s[5]) if kind == "r" else s[5]
            line = f"{head} {val}"
            if btype == "GPIO" and midx != -1:
                pin = self.pin_pos(pos, midx)
                if pin:
                    line += f" ; {pin}"
            if btype == "DQS16" and midx != -1:
                g = self.p2p_from.get(("DQS16", pos[0], pos[1], None, midx, -1), [])
                if g:
                    pin = self.pin_pos((g[0][1], g[0][2]), g[0][4])
                    if pin:
                        line += f" ; {pin}"
            L.append(line)
        for node, v, d in self.inverters():
            if v == d:
                continue
            p = self.rnode_to_pnode(node)
            line = f"i {pname(p) if p else rname(self.t, node)} {v}"
            pin = self.pin_pnode(p)
            if pin:
                line += f" ; {pin}"
            if p is not None and p[0] == "HMC":
                p1 = self.hmc_bypass(p)
                if p1:
                    line += f" ; {pname(p1)}"
                    gpio = self.p2p_to.get(p1)
                    if gpio is None:
                        for gp in self.p2p_from.get(p1, []):
                            if gp[0] == "GPIO":
                                gpio = gp
                                break
                    if gpio is not None and gpio[0] == "GPIO":
                        line += f" {pname(gpio)}"
            L.append(line)
        return L


def fmt_ram(rb, bits):
    top = (bits - 1) >> 3
    s = f"{rb[top]:02x}" if ((bits - 1) & 7) >= 4 else f"{rb[top]:x}"
    for b in range(top - 1, -1, -1):
        if (b & 3) == 3:
            s += "."
        s += f"{rb[b]:02x}"
    return s


def dqs16_adjust(pos, offset, up):
    if up:
        return pos + (3 * 191 if offset >= 768 else 2 * 191 if offset >= 512 else 191 if offset >= 256 else 0)
    return pos - (3 * 191 + 256 * 5 + 836 if offset >= 768 else 2 * 191 + 256 * 4 if offset >= 512
                  else 191 + 256 * 2 if offset >= 256 else 0)


class Solve:
    """Defaults that depend on the block/pin (cv-bmux.cc bmux_*_solve_default)."""

    def __init__(self, model):
        self.m = model
        self.iob = {(r["pos"], r["idx"]): r for r in model.t["iob"] if r["btype"] == "gpio"}

    def bool_default(self, btype, tile, idx, m):
        d = m.get("default_value")
        if d is not None:
            return d
        pos, base = tile[0], tile[1]
        name = m["mux"]
        if btype == "GPIO" and name == "use_weak_pullup":
            return 1 if self.m.pin_pos(pos, idx) else 0
        if btype == "FPLL":
            return 1 if base & (1 << 24) else 0
        if btype == "TERM":
            return 0 if base & (1 << 24) else 1
        if btype == "PMA3":
            return (base >> 29) & 1
        if btype == "DQS16":
            ty = (base >> 24) & 1
            if name in ("rb_2x_clk_dqs_inv", "rb_aclr_lfifo_en"):
                return 1 if ty else 0
            if name == "rb_lfifo_bypass":
                return 0 if ty else 1
        return -2

    def m_default(self, btype, tile, idx, m):
        pos, base = tile[0], tile[1]
        name = m["mux"]
        if btype == "GPIO":
            if name == "drive_strength":
                return "OFF" if self.m.pin_pos(pos, idx) else "PROG_GND"
            if name == "iocsr_std":
                r = self.iob.get((pos, idx))
                if r is not None:
                    return "NVR_LOW" if r["pram"] & (1 << 25) else "NVR_HIGH"
        if btype == "PMA3":
            if name == "ffpll_iqclk_direction":
                bdef = ["UP", "UP", "DOWN", "UP", "TRISTATE", "TRISTATE"]
                return bdef[((base >> 26) & 3) * 2 + idx]
            if name == "hclk_top_out_driver":
                return "DOWN_EN" if (base >> 28) & 1 else "TRISTATE"
        return None

    def ram_default(self, btype, tile, idx, m, rb, row):
        d = m.get("default_value")
        if d is None:
            name = m["mux"]
            if btype == "HSSI":
                hv = [[0x096, 0x226, 0x3B6], [0x0FA, 0x28A, 0x41A], [0x064, 0x1F4, 0x384]]
                d = {"pcs8g_base_addr": hv[0][idx], "pld_pcs_if_base_addr": hv[1][idx],
                     "pma_pcs_if_base_addr": hv[2][idx]}.get(name)
            elif btype == "PMA3" and name == "dprio_reg_pld_pma_if_baddr":
                d = (0x000, 0x190, 0x320)[idx]
            elif btype == "BNONE":
                if name == "idcode":
                    d = self.m.idcode
                elif name == "opt_a":
                    d = 0x1DFF
            if d is None:
                return False
        if d == -1:
            return bool(row.all())
        if d == 0:
            return not row.any()
        if any(rb[3:]):
            return False
        if rb[0] != (d & 0xFF):
            return False
        if len(rb) > 1 and rb[1] != ((d >> 8) & 0xFF):
            return False
        if len(rb) > 2 and rb[2] != ((d >> 16) & 0xFF):
            return False
        return True


# ---- encoder (libmistral rbf_save) ---------------------------------------------------------------

def edcrc_rows(frames, geo):
    """EDCRC word of each frame row (uint8 (n, cfb))."""
    nb = 32 * geo.cram_frame_bits
    contrib, init = edcrc_contrib(nb)
    k = np.arange(nb)
    pos = 224 + (31 - k // geo.cram_frame_bits) + 32 * (k % geo.cram_frame_bits)
    bits = (frames[:, pos >> 3] >> (pos & 7).astype(np.uint8)) & 1
    calc = np.full(frames.shape[0], init, np.uint32)
    for j in range(nb):
        calc[bits[:, j] != 0] ^= contrib[j]
    return calc


# Postamble sizes of Quartus-compressed images (measured on e50f corpus builds; uncompressed use the die values).
COMPRESSED_POSTAMBLES = {"e50f": (28, 481)}


def encode_rbf(tables, bits, compress=None):
    """Planes -> .rbf bytes, same layout rules as libmistral rbf_save. compress=None: follow the COMPRESSION_DIS bit."""
    geo, g = bits.geo, tables["geom"]
    fs, mp, pb = geo.fs, geo.mpram, geo.pram_blocks
    data = bytearray(geo.oram_frame_bytes + geo.pram_frame_bytes * pb)
    data[0:0x80] = b"\xff" * 0x80
    data[0x80:0x84] = b"jjjj"
    for strip in range(32):
        for bit in range(40):
            if (bits.oram[strip] >> bit) & 1:
                data[0x84 + (strip >> 3) + (bit << 2)] |= 0x80 >> (strip & 7)
    data[0x124] = data[0x125] = 0
    ck = crc16(bytes(data[0x84:0x126]))
    data[0x126], data[0x127] = ck & 0xFF, ck >> 8
    data[0x128:0x128 + fs * 4 - 0xB8] = b"\xff" * (fs * 4 - 0xB8)
    for bit in range(31, -1, -1):
        cnt = geo.pram_sizes[bit]
        if not cnt:
            continue
        i = np.nonzero(bits.pram[bit])[0]
        base = mp - i - 1
        idx = geo.oram_frame_bytes + 4 + (bit >> 3) + base * 4 + (base // fs) * 8
        for ix in idx.tolist():
            data[ix] |= 1 << (bit & 7)
    coff = geo.oram_frame_bytes + (pb - 1) * geo.pram_frame_bytes
    data[coff:coff + 3] = b"\x2a\xc5\x01"
    coff = geo.oram_frame_bytes
    for _ in range(pb):
        c = crc16(bytes(data[coff:coff + geo.pram_frame_bytes - 2]))
        data[coff + geo.pram_frame_bytes - 2], data[coff + geo.pram_frame_bytes - 1] = c & 0xFF, c >> 8
        coff += geo.pram_frame_bytes
    comp_dis = options_compression_dis(tables, bits)
    do_compress = (not comp_dis) if compress is None else compress
    sx, cfb = geo.sx, geo.cfb
    fb = np.zeros((sx, cfb * 8), np.uint8)
    ys = np.arange(32, geo.sy)
    yy = ys + geo.offset
    pos = 224 + (31 ^ (yy // geo.cram_frame_bits)) + 32 * (yy % geo.cram_frame_bits)
    fb[:, pos] = bits.cram.reshape(geo.sy, sx)[32:, :].T
    frames = np.packbits(fb, axis=1, bitorder="little")
    frames[0, 0:3] = (0x84, 0x3E, 0x01)
    frames[sx - 1, 0:3] = (0x42, 0x9F, 0x00)
    ed = edcrc_rows(frames, geo)
    zones, idx = g["noedcrc_zones"], 0
    for x in range(sx):
        has = not (idx < len(zones) and x >= zones[idx])
        if idx < len(zones) and x == zones[idx] + 255:
            idx += 1
        frames[x, cfb - 8:cfb - 4] = np.frombuffer(int(ed[x] if has else 0).to_bytes(4, "little"), np.uint8)
    frames[:, cfb - 2:] = 0
    c = crc16_rows(frames[:, :cfb - 2])
    frames[:, cfb - 2] = c & 0xFF
    frames[:, cfb - 1] = c >> 8
    raw = frames.tobytes()
    data += nibble_compress(raw) if do_compress else raw
    p1, p2n = (COMPRESSED_POSTAMBLES.get(g["name"], (g["postamble_1"], g["postamble_2"])) if do_compress
               else (g["postamble_1"], g["postamble_2"]))
    post = bytearray(p1)
    post[0], post[1] = 0xEC, 0x64
    data += post
    c = crc16(bytes(post))
    data += bytes((c & 0xFF, c >> 8))
    p2 = bytearray(10)
    p2[0], p2[1] = 0xAE, 0xFB
    data += p2
    c = crc16(bytes(p2))
    data += bytes((c & 0xFF, c >> 8))
    data += b"\xff" * p2n
    return bytes(data)


# ---- API ---------------------------------------------------------------------------------------

def decode(data, device="5CEBA4U19C8", overrides=True, claims=False, compat=False, tables=None, strict=True):
    tb = tables or nt.load(device)
    ov = None
    if overrides:
        import cyclonev_native_overrides as ovm
        ov = ovm.Overrides()
    mdl = Model(tb, ov, claims=claims, compat=compat)
    mdl.bits = load_rbf(tb, data, mdl.geo, strict=strict)
    return mdl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rbf")
    ap.add_argument("bt")
    ap.add_argument("--device", default="5CEBA4U19C8")
    ap.add_argument("--no-overrides", action="store_true", help="bootstrap tables exactly (differential runs)")
    ap.add_argument("--mistral-compat", action="store_true", help="reproduce libmistral quirks (SCLK/DCMUX link skip)")
    ap.add_argument("--force", action="store_true", help="decode even if the container checks fail")
    ap.add_argument("--claims", help="write claimed/unclaimed accounting JSON")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_decode.log"))])
    t0 = time.time()
    data = open(a.rbf, "rb").read()
    m = decode(data, a.device, overrides=not a.no_overrides, claims=bool(a.claims), compat=a.mistral_compat, strict=not a.force)
    lines = m.bt_lines()
    os.makedirs(os.path.dirname(os.path.abspath(a.bt)), exist_ok=True)
    with open(a.bt, "w") as f:
        f.write("\n".join(lines) + "\n")
    log.info("%s -> %s: %d lines, %d unresolved route values (%.1fs)", a.rbf, a.bt, len(lines),
             len(m.route_unknown), time.time() - t0)
    if a.claims:
        import cyclonev_account as acc
        json.dump(acc.account(m, data), open(a.claims, "w"), indent=1)


if __name__ == "__main__":
    main()
