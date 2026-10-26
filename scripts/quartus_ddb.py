#!/usr/bin/env python3.15t
"""Quartus .ddb container reader (Cyclone IV E / IV GX / V devinfo).

Layout (measured on cycloneivgx 2026-10-26):
- header of 0x73 bytes: u32 0x14, u32 total-ish, ..., version string ("Version 25.1std.0 ...").
- payload: a chain of zlib members, each starting 78 01 and ending at its own sync/final marker;
  after one member's end the next begins at once (the "invalid stored block lengths" of a single
  inflate is the next member's start).
- inflate(): returns (header_bytes, [member payloads]); members are concatenated by payload().

  python3.15t scripts/quartus_ddb.py FILE.ddb [--out OUT.bin]      # sizes + member map
"""
import argparse
import sys
import zlib
from pathlib import Path

HDR = 0x73


SYNC = b"\x00\x00\xff\xff\x78\x01"


def members(raw, start=HDR):
    """[(offset, compressed_len, data)] per zlib stream.  Streams are not terminated: each ends
    with a sync-flush marker (00 00 ff ff) and the next one starts with 78 01 right after it."""
    if raw[start] == 0xFD:      # xz payload (hdr, part_info, ...), one stream
        import lzma
        d = lzma.LZMADecompressor()
        data = d.decompress(raw[start:])
        return [(start, len(raw) - start - len(d.unused_data), data)]
    cuts, pos = [start], start
    while True:
        i = raw.find(SYNC, pos)
        if i < 0:
            break
        cuts.append(i + 4)
        pos = i + 4
    cuts.append(len(raw))
    out = []
    for a, b in zip(cuts, cuts[1:]):
        d = zlib.decompressobj()
        data = d.decompress(raw[a:b])
        data += d.flush()
        out.append((a, b - a, data))
    return out


def read(path, start=HDR):
    raw = Path(path).read_bytes()
    return raw[:start], members(raw, start), raw


def payload(path, start=HDR):
    return b"".join(m[2] for m in read(path, start)[1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ddb")
    ap.add_argument("--out")
    a = ap.parse_args()
    hdr, ms, raw = read(a.ddb)
    print(f"{a.ddb}: {len(raw)} bytes, header {hdr[:0x20].hex()}, {len(ms)} members, "
          f"payload {sum(len(m[2]) for m in ms)} bytes, compressed covered {sum(m[1] for m in ms) + HDR}")
    for off, n, data in ms[:8]:
        print(f"  member at {off:#x}: {n} -> {len(data)}")
    if a.out:
        Path(a.out).write_bytes(b"".join(m[2] for m in ms))
    return 0


if __name__ == "__main__":
    sys.exit(main())
