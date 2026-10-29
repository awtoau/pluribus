"""Cyclone IV GX (EP4CGX150) IO configuration: address spaces and the CFF region.  Vendor-derived only (#165).

Finding: IO pin configuration is NOT in the CRAM address space of asm.ddb.  The assembler addresses five spaces
(CRAM, CFF, UNVM, option register, DPRIO) by tag bits; asm.ddb holds CRAM only; the 31,060 CFF bits land in the 36
periphery frames of the rbf.  Evidence and counts: docs/cycloneiv-clean-io.md.  Decoded here: the address tags, the
die head counts, the CFF bit -> rbf cell table.  NOT decoded: asmdb groups -> IO fields (direction, standard, drive, slew,
pull), pad -> pin.  No constant below is fitted to a single cell.
"""
import os

import numpy as np

from . import plane as P

# a >= 0 -> CRAM bit a; (a & mask) == mask picks the space, index = a & keep; 0xfffffffa..e = DB_ILLEGAL_* markers.
# source: libcomp_asmcc ASM_BITFIELD::silent_set_bits @ 0x117e50 (static decompile), tag tests in this order
ADDRESS_SPACES = (
    # name, mask (all bits must be set), keep (index bits)
    ("LITERAL", 0xC0000000, 0x3FFFFFFF),
    ("CFF", 0xA0000000, 0x5FFFFFFF),
    ("UNVM", 0x90000000, 0x6FFFFFFF),
    ("OPTION", 0x88000000, 0x77FFFFFF),
    ("DPRIO", 0x84000000, 0x7BFFFFFF),
)
# source: ASMDB_DIE::operator<< field order in libdb_asmdb (bool8 m_arch_value, then i32_delta m_num_bits, m_num_cff_bits,
#   m_num_unvm_bits, m_num_option_reg_bits), read at asmdb body offsets 5, 9, 13, 17
DIE_HEAD_OFFSETS = (("num_bits", 5), ("num_cff_bits", 9), ("num_unvm_bits", 13), ("num_option_reg_bits", 17))
# source: ddb_stingray4_asmdb.ddb in the Quartus devinfo directory (EP4CGX150 die)
ASMDB_NAME = "ddb_stingray4_asmdb.ddb"
# source: sof section tags of sfl_ep4cgx150.sof: 17 = CRAM, 21 = CFF, 18 = option; each 17 / 21 section = 12-byte header + packed bits
SOF_TAG_CRAM, SOF_TAG_CFF, SOF_TAG_OPTION = 17, 21, 18
SOF_SECTION_HEADER = 12
CFF_TABLE_PATH = os.path.join(P.REPO, "databases", "cycloneiv", "cff2rbf.npz")
# source: scripts/cycloneiv_clean_cff_tables.py (quartus_cpf bit-planes): each CFF bit sits in 4 consecutive bytes of one lane
CFF_REPLICAS = 4


class CffMissing(FileNotFoundError):
    pass


def classify(addr):
    """DB_BIT_SETTING address(es) (uint32 values, as stored) -> (space names, index) arrays.  Space 'CRAM' for a < 2^31."""
    a = np.asarray(addr, np.int64) & 0xFFFFFFFF
    space = np.full(a.shape, "ILLEGAL", dtype="U7")
    index = np.full(a.shape, -1, np.int64)
    done = np.zeros(a.shape, bool)
    cram = a < 0x80000000
    space[cram], index[cram], done[cram] = "CRAM", a[cram], True
    for name, mask, keep in ADDRESS_SPACES:
        m = ~done & ((a & mask) == mask)
        space[m], index[m], done[m] = name, a[m] & keep, True
    return space, index


def die_head(path=None):
    """{num_bits, num_cff_bits, num_unvm_bits, num_option_reg_bits} read from the vendor asmdb body."""
    import sys
    sys.path.insert(0, os.path.join(P.REPO, "scripts"))
    import cyclonev_ddb_decode as dd
    from . import sofio
    if path is None:
        path = os.path.normpath(os.path.join(sofio.quartus_bin(), "..", "common", "devinfo", "cycloneivgx", ASMDB_NAME))
    if not os.path.exists(path):
        raise sofio.VendorMissing(path)
    body = b""
    for chunk in dd.iter_body(path):
        body += chunk
        if len(body) >= 32:
            break
    return {k: int.from_bytes(body[o:o + 4], "little") for k, o in DIE_HEAD_OFFSETS}


def sof_section_sizes(path):
    """{tag: payload length} of a sof."""
    import gzip
    import struct
    d = gzip.decompress(open(path, "rb").read())
    p, out = 12, {}
    while p < len(d):
        tag, ln = struct.unpack_from("<HI", d, p)
        out[tag] = ln
        p += 6 + ln
    return out


def packed_len(nbits):
    return SOF_SECTION_HEADER + (nbits + 7) // 8


def asm_census(asm):
    """Space census of every asm.ddb entry: {space: count} plus min / max raw address (ddb.Asm in, nothing else read)."""
    pos = np.asarray(asm.pos, np.int64)
    space, _ = classify(pos)
    names, counts = np.unique(space, return_counts=True)
    return dict(zip(names.tolist(), counts.tolist())), int(pos.min()), int(pos.max())


class Cff:
    """CFF bit -> rbf periphery cells.  cells[i] = (frame, byte, bit) rows; frame 0 = header, 1..36 periphery;
    byte is the raw frame byte (0..795), not the plane's j.  `primary` = the first CFF_REPLICAS cells of each bit."""

    def __init__(self, path=CFF_TABLE_PATH):
        if not os.path.exists(path):
            raise CffMissing(f"{path} missing; run scripts/cycloneiv_clean_cff_tables.py")
        z = np.load(path)
        self.source = str(z["source"])
        t = z["cff"]
        self.n_bits = int(t.max()) + 1
        cells = np.argwhere(t >= 0)
        idx = t[t >= 0].astype(np.int64)
        order = np.argsort(idx, kind="stable")
        self.cells, self.idx = cells[order], idx[order]
        self.first = np.searchsorted(self.idx, np.arange(self.n_bits))
        self.count = np.bincount(self.idx, minlength=self.n_bits)
        pr = self.cells[self.first][:, None, :] + np.array([0, 1, 2, 3])[None, :, None] * np.array([0, 1, 0])[None, None, :]
        self.primary = pr                                  # [n_bits, 4, 3] (frame, byte, bit)

    def read(self, rbf):
        """(values uint8 [n_bits], disagreeing primary-replica cells) from rbf bytes or a path."""
        b = np.fromfile(rbf, np.uint8) if isinstance(rbf, str) else np.frombuffer(rbf, np.uint8)
        fr = b[P.RBF_HEADER:P.RBF_HEADER + P.RBF_PRE_FRAMES * P.RBF_FRAME_BYTES].reshape(P.RBF_PRE_FRAMES, P.RBF_FRAME_BYTES)
        rep = (fr[self.primary[..., 0], self.primary[..., 1]] >> self.primary[..., 2]) & 1
        val = rep[:, 0]
        return val.astype(np.uint8), int((rep != val[:, None]).sum())


# source: libcomp_asm ASM_IO_PIN_MODE::process_atom @ 0x29101c (static decompile): mux_select(group, value) per pin state
PIN_MODE_MUX = {
    "input": 0,
    "output_oe_const": 1,
    "output_oe_wired": 2,
    "open_drain_oe_const": 3,
    "open_drain_oe_wired": 4,
    "output_oe_registered": 5,
    "open_drain_oe_registered": 6,
}


# source: libdb_asmdb ASMDB_DIE::operator<< @ 0x19d8f0 (static decompile): field order after the 4 counts
DIE_STREAM_FIELDS = (
    "m_summary_block_rba_version_string", "m_mcf_sch_version_string", "m_rba_version_string", "m_bvp_version_string",
    "m_block_info_map", "m_arch_group_list", "m_default_group_list", "m_default_bit_list", "m_forced_bit_list",
    "m_labeled_simple_mux_list", "m_local_default_group_list", "m_local_arch_group_list", "m_hc_base_nodes",
    "m_hc_fringe_nodes", "m_hc_wires",
)


def asmdb_body(path=None):
    """Inflated asmdb body bytes (IV die)."""
    import sys
    sys.path.insert(0, os.path.join(P.REPO, "scripts"))
    import cyclonev_ddb_decode as dd
    from . import sofio
    if path is None:
        path = os.path.normpath(os.path.join(sofio.quartus_bin(), "..", "common", "devinfo", "cycloneivgx", ASMDB_NAME))
    if not os.path.exists(path):
        raise sofio.VendorMissing(path)
    return b"".join(dd.iter_body(path))


def asmdb_main_stream(b):
    """Walk the non-deferred part of the ASMDB_DIE record (PDB layer: docs/cycloneiv-ddb-format.md).

    Containers are `u32 count` + count elements; pointer elements are one u32 tag each (class id = tag >> 2,
    object content is deferred to per-class pools after the main stream); default / forced bit lists are
    delta-coded u32 (running sum mod 2^32).  -> dict with block-type keys, tag histograms, bit lists, end offset.
    """
    import struct
    u = lambda o: struct.unpack_from("<I", b, o)[0]
    o = 4 + 17                                      # root tag, arch byte + 4 counts (die_head), then 4 strings
    for _ in range(4):
        o += 4 + u(o)
    out = {}
    n = u(o)
    out["block_types"] = [u(o + 4 + 8 * i) for i in range(n)]
    out["block_tags"] = [u(o + 8 + 8 * i) for i in range(n)]
    o += 4 + 8 * n
    for name in ("m_arch_group_list", "m_default_group_list"):
        n = u(o)
        tags = struct.unpack_from(f"<{n}I", b, o + 4)
        out[name] = {t >> 2: tags.count(t) for t in sorted(set(tags))}
        o += 4 + 4 * n
    for name in ("m_default_bit_list", "m_forced_bit_list"):
        n = u(o)
        acc, vals = 0, []
        for d in struct.unpack_from(f"<{n}I", b, o + 4):
            acc = (acc + d) & 0xFFFFFFFF
            vals.append(acc)
        out[name] = vals
        o += 4 + 4 * n
    for name in DIE_STREAM_FIELDS[9:]:
        n = u(o)
        out[name] = n
        o += 4 + 4 * n
    out["end"] = o
    return out


def ddb_types(path):
    """Type table of a devinfo .ddb (trailer after the body): [(class_id, sizeof, count, name)].

    Layout from docs/cyclonev-ddb-format.md: u16 n, per type u16 id, u32 sizeof, u32 crc, u32 count, u32 version,
    u32 namelen (incl. NUL), name.  A pointer tag's class id (tag >> 2) indexes this table.
    """
    import struct
    import sys
    import zlib
    sys.path.insert(0, os.path.join(P.REPO, "scripts"))
    import cyclonev_ddb_decode as dd
    hdr = dd.read_header(path)
    raw = open(path, "rb").read()[hdr.body_end:]
    t = zlib.decompressobj().decompress(raw)
    n = struct.unpack_from("<H", t, 0)[0]
    o, out = 2, []
    for _ in range(n):
        i, sz, _crc, cnt, _ver, nl = struct.unpack_from("<HIIIII", t, o)
        o += 22
        out.append((i, sz, cnt, t[o:o + nl - 1].decode("latin1")))
        o += nl - 1
    return out


# source: scripts/cycloneiv_clean_io_pairs.py analyse (pair ids = `base` / `spec` build ids per row); one assignment differs per pair
PAIRS_PATH = os.path.join(P.REPO, "databases", "cycloneiv", "io_pairs.json")


class PairsMissing(FileNotFoundError):
    pass


def io_pairs(path=PAIRS_PATH):
    """Pair-diff table: {sample, rows[setting, value, pin, base, spec, cff, opt, cram, ...], location, location_vs_corpus}.
    Each row's `cff` = CFF bit indices that differ between the base and spec build of that site (exact labels, pair diff only)."""
    import json
    if not os.path.exists(path):
        raise PairsMissing(f"{path} missing; run scripts/cycloneiv_clean_io_pairs.py build + analyse")
    return json.load(open(path))
