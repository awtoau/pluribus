"""Cyclone V asmdb.ddb reader: die header and per-block CFF (PRAM) placement.

Record layouts are the field order of the PDB serializers in libdb_asmdb.so
(ASMDB_DIE / ASMDB_BLOCK_INFO `operator<<`, static decompile), then read from the body.
Placement rule (offset_cache.cpp, `calculate_bits_traditional`): list type 3.. = CFF offsets.
"""
import re
import struct

from .ddb import body

# source: ASMDB_DIE::operator<< field order: arch byte, num_bits, num_cff_bits, num_unvm_bits,
#         num_option_reg_bits (u32 each), then 4 length-prefixed strings.
# source: ASMDB_BLOCK_INFO::operator<< + ASMDB_BLOCK_INFO::get_block_data: block_lists keys 3..7 = CFF offset vectors.
CFF_KEY0 = 3
_SPACE = re.compile(rb"\d+ : \d+ : \d+(?: : \d+)*")


def die_header(buf):
    arch = buf[4]
    num_bits, num_cff, num_unvm, num_opt = struct.unpack_from("<IIII", buf, 5)
    return dict(arch=arch, num_bits=num_bits, num_cff_bits=num_cff, num_unvm_bits=num_unvm,
                num_option_reg_bits=num_opt)


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def block_infos(buf):
    """-> list of dict(name, space, nseg, sizes, lists{key:[int32]}); one per BLOCK_INFO with a CFF space."""
    out = []
    for m in _SPACE.finditer(buf):
        o = m.start() - 4
        if o < 0 or _u32(buf, o) != len(m.group(0)):
            continue
        fields = [int(x) for x in m.group(0).split(b" : ")]
        nseg = fields[2]
        sizes = fields[3:]
        if nseg == 0 or len(sizes) != nseg:
            continue
        p = m.end()
        n = _u32(buf, p)
        p += 4 + n
        n = _u32(buf, p)
        name = buf[p + 4:p + 4 + n].decode("latin1")
        p += 4 + n
        cnt = _u32(buf, p)
        p += 4
        lists = {}
        for _ in range(cnt):
            key = _u32(buf, p)
            p += 5  # key + non-null flag byte
            ln = _u32(buf, p)
            p += 4
            lists[key] = list(struct.unpack_from(f"<{ln}i", buf, p))
            p += 4 * ln
        out.append(dict(name=name, space=m.group(0).decode(), nseg=nseg, sizes=sizes, lists=lists, off=o))
    return out


def extents(blocks, ncff):
    """CFF address extents, all mod num_cff_bits.

    List j (key 3+j) is delta-coded across instances. Its first value is absolute for j = 0 and
    relative to segment j-1 of instance 0 for j > 0 (no-overlap check over the whole die selects this).
    A = highest address of the extent; bit b of the segment sits at A - b.
    -> list of (name, instance, segment, A_high, size)
    """
    rows = []
    for b in blocks:
        prev0 = 0
        for j, size in enumerate(b["sizes"]):
            vec = b["lists"].get(CFF_KEY0 + j)
            if not vec:
                continue
            a = (prev0 + vec[0]) % ncff
            prev0 = a
            for k, d in enumerate(vec):
                if k:
                    a = (a + d) % ncff
                rows.append((b["name"], k, j, a, size))
    return rows


def load(ddb_path):
    buf = body(ddb_path)
    hdr = die_header(buf)
    blocks = block_infos(buf)
    return hdr, blocks, extents(blocks, hdr["num_cff_bits"])


def claims(rows, ncff):
    """CFF address -> (block, instance, segment, bit). Raises on a double claim (vendor tables tile the space)."""
    own = {}
    for name, k, j, a, size in rows:
        for b in range(size):
            x = (a - b) % ncff
            if x in own:
                raise ValueError(f"CFF address {x} claimed twice: {own[x][:3]} and {(name, k, j)}")
            own[x] = (name, k, j, b)
    return own
