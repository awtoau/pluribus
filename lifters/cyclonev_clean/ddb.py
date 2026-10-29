"""Quartus .ddb container reader (body only).

source: file header of every devinfo .ddb, layout read from the files (docs/cyclonev-ddb-format.md).
"""
import lzma
import struct
import zlib

# source: ddb header, fixed 0x73-byte prefix; offsets inside it follow the version string.
HEADER_LEN = 0x73


def body(path):
    """Inflated body bytes of a .ddb file (trailer type table not returned)."""
    with open(path, "rb") as f:
        data = f.read()
    hdr_off, magic = struct.unpack_from("<II", data, 0)
    if hdr_off != 0x14 or (magic & 0xFFFF) != 0x0BAD:
        raise ValueError(f"not a ddb container: {path}")
    (str_len,) = struct.unpack_from("<I", data, 0x10)
    p = 0x14 + str_len - 1
    raw_size, body_end, _types_raw = struct.unpack_from("<QQQ", data, p)
    (codec,) = struct.unpack_from("<I", data, p + 24)
    comp = data[HEADER_LEN:body_end]
    if codec == 1:
        out = lzma.decompress(comp)
    elif codec == 0:
        out = zlib.decompressobj().decompress(comp)
    else:
        raise ValueError(f"unknown codec {codec}")
    if len(out) != raw_size:
        raise ValueError(f"{path}: inflated {len(out)} != header {raw_size}")
    return out
