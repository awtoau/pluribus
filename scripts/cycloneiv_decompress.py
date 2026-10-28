#!/usr/bin/env python3
"""Cyclone III / IV (E, GX, LS) compressed .rbf -> uncompressed .rbf, byte-identical to quartus_cpf.

Format (docs/cycloneiv-bitstream.md), offsets relative to the 0x6a sync byte S (S = 32 in Quartus files):
- 0xFF preamble.  Frame 0 = header frame, F bytes: 0x6a, 40 option bytes (8 bit-lanes of 40 bits,
  byte i = bit i of every lane), CRC-16/MODBUS of the 40 bytes (LE), 0xFF fill to S+F.
- Frames 1..r-1: periphery, raw, no per-frame CRC.  r = 13..49 by die.
- Frames r..: CRAM, F bytes each, last 2 = CRC-16 (poly 0xA001 reflected, init 0xFE54) of the rest.
- Postamble: 59 x 0xFF.
- Compressed: everything from frame r to EOF is nibble-coded (same scheme as Cyclone V,
  scripts/cyclonev_decompress.py): key nibble k, then the nibbles k marks; unmarked = 0.
- Option bits that differ: lane 1 bit 35 (1 = uncompressed); length field = lane 2 bits 16..39
  (low) : lane 3 bits 0..6 (high), = 4*(file length - 1) uncompressed.  Header CRC recomputed.
Die-independent: F from the header frame's 0xFF fill, r and the frame count from the CRC chain.

Usage: python3.15t scripts/cycloneiv_decompress.py in.rbf [-o out.rbf] [--info]
"""
import argparse
import collections
import math
import os
import sys

import numpy as np

SYNC = 0x6A
PREAMBLE = 32          # 0xFF bytes before S in every quartus_cpf file
POSTAMBLE = 59         # 0xFF bytes after the last CRAM frame in every quartus_cpf file
HDR = 40
CRAM_INIT = 0xFE54
MAX_PERIPHERY = 96     # periphery frames seen: 13..49
NV = [bin(k).count("1") for k in range(16)]
ENCRYPTED_ENTROPY = 7.9
ENTROPY_PROBE = 1 << 16


class FormatError(ValueError):
    pass


def _table():
    t = []
    for i in range(256):
        a = i
        for _ in range(8):
            a = (a >> 1) ^ (0xA001 if a & 1 else 0)
        t.append(a)
    return t


CRC_T = _table()


def crc16(b, a=0xFFFF):
    for x in b:
        a = (a >> 8) ^ CRC_T[(a ^ x) & 0xFF]
    return a


def frame_ok(d, s, f):
    return s + f <= len(d) and crc16(d[s:s + f - 2], CRAM_INIT) == d[s + f - 2] | d[s + f - 1] << 8


def lane(d, s, n):
    return sum(((d[s + 1 + i] >> n) & 1) << i for i in range(HDR))


def set_lane(d, s, n, v):
    for i in range(HDR):
        o = s + 1 + i
        d[o] = (d[o] | 1 << n) if (v >> i) & 1 else (d[o] & ~(1 << n))


def length_field(d, s):
    return (lane(d, s, 2) >> 16) | (lane(d, s, 3) & 0x7F) << 24


def set_length_field(d, s, v):
    set_lane(d, s, 2, lane(d, s, 2) & 0xFFFF | (v & 0xFFFFFF) << 16)
    set_lane(d, s, 3, lane(d, s, 3) & ~0x7F | (v >> 24) & 0x7F)


def hdr_crc_ok(d, s):
    return crc16(d[s + 1:s + 1 + HDR]) == d[s + 1 + HDR] | d[s + 2 + HDR] << 8


def fix_header(d, s, length):
    set_lane(d, s, 1, lane(d, s, 1) | 1 << 35)
    set_length_field(d, s, 4 * (length - 1))
    c = crc16(d[s + 1:s + 1 + HDR])
    d[s + 1 + HDR], d[s + 2 + HDR] = c & 0xFF, c >> 8


def find_sync(d):
    n = 0
    while n < len(d) and d[n] == 0xFF:
        n += 1
    if n >= len(d) or d[n] != SYNC:
        raise FormatError(f"no 0x6a sync after {n} bytes of 0xFF preamble: not a Cyclone III/IV .rbf")
    return n


def frame_size(d, s):
    """F = header frame length: 0x6a + 40 + CRC, then 0xFF fill up to frame 1."""
    q = s + 3 + HDR
    while q < len(d) and d[q] == 0xFF:
        q += 1
    return q - s


def _nibbles(src):
    nib = bytearray(2 * len(src))
    nib[0::2] = bytes(b & 15 for b in src)
    nib[1::2] = bytes(b >> 4 for b in src)
    return nib


def _scalar_loop(nib, i, n, limit, out):
    """The reference record loop: decode from nibble i; appends to `out`; returns the stop position."""
    while i < n and (limit is None or len(out) < limit):
        k = nib[i]
        if k == 0:
            j = i
            stop = n if limit is None else min(n, i + (limit - len(out) + 1) // 2)
            while j < stop and nib[j] == 0:
                j += 1
            out += bytes(2 * (j - i))
            i = j
            continue
        if i + 1 + NV[k] > n:
            if i + 1 + NV[k & 3] <= n:
                v0 = 0
                p = i + 1
                if k & 1:
                    v0 = nib[p]; p += 1
                if k & 2:
                    v0 |= nib[p] << 4; p += 1
                out.append(v0)
                i = n
            break
        i += 1
        v0 = v1 = 0
        if k & 1:
            v0 = nib[i]; i += 1
        if k & 2:
            v0 |= nib[i] << 4; i += 1
        if k & 4:
            v1 = nib[i]; i += 1
        if k & 8:
            v1 |= nib[i] << 4; i += 1
        out.append(v0)
        out.append(v1)
    return i


def nibble_decode_scalar(src, limit=None):
    """Key/nibble stream -> bytes, record by record (reference loop).  Stops at EOF or `limit` output bytes.
    A key at EOF whose byte-1 nibbles are missing yields byte 0 only (odd-length Quartus tail).
    Returns (bytes, left)."""
    nib = _nibbles(src)
    out = bytearray()
    n = len(nib)
    i = _scalar_loop(nib, 0, n, limit, out)
    return bytes(out), n - i


FAST_MIN_NIBBLES = 1 << 14
_NV = np.array(NV, np.int64)


def nibble_decode_fast(src):
    """== nibble_decode_scalar(src) (limit=None), numpy.  The stream is sequential (a record's length
    comes from its key, no resync marks), so it is decoded as pointer chasing on the nonzero nibbles
    only: next(key) = first nonzero nibble at/after key + 1 + NV[key] (zero nibbles are 1-nibble
    keys, i.e. 2 zero bytes each).  The chain from the first nonzero is listed by pointer doubling
    (log2 m gathers); payload nibbles are then gathered and scattered by key index."""
    a = np.frombuffer(src, np.uint8)
    n = 2 * len(a)
    nib = np.zeros(n + 8, np.uint8)
    nib[0:n:2] = a & 15
    nib[1:n:2] = a >> 4
    nz = np.flatnonzero(nib[:n])
    m = len(nz)
    if m == 0:
        return bytes(2 * n), 0
    k = nib[nz].astype(np.int64)
    nvk = _NV[k]
    q = nz + 1 + nvk
    trunc = q > n
    nxt = np.empty(m + 1, np.int64)
    nxt[:m] = np.searchsorted(nz, q)
    nxt[:m][trunc] = m
    nxt[m] = m
    levels = [nxt]
    while (1 << len(levels)) <= m + 1:
        last = levels[-1]
        levels.append(last[last])
    path = np.zeros(1, np.int64)
    for jump in reversed(levels):
        nxt_pts = jump[path]
        path = np.stack((path, nxt_pts), axis=1).reshape(-1)
    cut = int(np.argmax(path == m)) if (path == m).any() else len(path)
    path = path[:cut]
    tail_pos = None
    if len(path) and trunc[path[-1]]:
        tail_pos = int(nz[path[-1]])
        path = path[:-1]
    p, kk, nvv = nz[path], k[path], nvk[path]
    end = n if tail_pos is None else tail_pos
    kidx = p - (np.cumsum(nvv) - nvv)
    total_keys = end - int(nvv.sum())
    out = np.zeros(2 * total_keys, np.uint8)
    c = p + 1
    b0 = kk & 1
    nv0 = b0 + ((kk >> 1) & 1)
    lo0 = np.where(b0 == 1, nib[c], 0)
    hi0 = np.where((kk & 2) != 0, nib[c + b0], 0)
    c1 = c + nv0
    lo1 = np.where((kk & 4) != 0, nib[c1], 0)
    hi1 = np.where((kk & 8) != 0, nib[c1 + ((kk >> 2) & 1)], 0)
    out[2 * kidx] = lo0 | (hi0 << 4)
    out[2 * kidx + 1] = lo1 | (hi1 << 4)
    if tail_pos is None:
        return out.tobytes(), 0
    tail = bytearray(out.tobytes())
    i = _scalar_loop(bytearray(nib[:n].tobytes()), tail_pos, n, None, tail)
    return bytes(tail), n - i


def nibble_decode(src, limit=None):
    """Key/nibble stream -> bytes (see nibble_decode_scalar).  Large unlimited streams take the
    numpy path (identical output, tests/test_cycloneiv_decompress.py)."""
    if limit is None and 2 * len(src) >= FAST_MIN_NIBBLES and os.environ.get("PLURIBUS_DECODE") != "scalar":
        return nibble_decode_fast(src)
    return nibble_decode_scalar(src, limit)


def entropy(b):
    n = len(b)
    return -sum(c / n * math.log2(c / n) for c in collections.Counter(b).values() if c)


_CRC_NP = np.array(CRC_T, np.uint32)


def frames_ok_np(d, start, f):
    """bool per whole frame at start + i*f: CRC-16 (init CRAM_INIT) of its first f-2 bytes == last 2
    bytes (LE).  All frames at once: one table step per byte column."""
    nfull = max(0, (len(d) - start) // f)
    if nfull == 0:
        return np.zeros(0, bool)
    arr = np.frombuffer(d, np.uint8, count=nfull * f, offset=start).reshape(nfull, f)
    cols = np.ascontiguousarray(arr[:, :f - 2].T)
    a = np.full(nfull, CRAM_INIT, np.uint32)
    for col in cols:
        a = (a >> 8) ^ _CRC_NP[(a ^ col) & 0xFF]
    return a == (arr[:, f - 2].astype(np.uint32) | arr[:, f - 1].astype(np.uint32) << 8)


def cram_walk_scalar(u, start, f):
    n = 0
    while frame_ok(u, start + n * f, f):
        n += 1
    return n


def cram_walk(u, start, f):
    """Count of consecutive CRC-valid frames from start (== cram_walk_scalar)."""
    if os.environ.get("PLURIBUS_DECODE") == "scalar":
        return cram_walk_scalar(u, start, f)
    ok = frames_ok_np(u, start, f)
    return int(np.argmin(ok)) if len(ok) and not ok.all() else len(ok)


def parse(d):
    s = find_sync(d)
    if not hdr_crc_ok(d, s):
        raise FormatError(f"header CRC-16/MODBUS mismatch at {s + 1 + HDR:#x}")
    f = frame_size(d, s)
    if f < 3 + HDR + 8:
        raise FormatError(f"header frame size {f} too small (periphery frame 1 starts with 0xFF?)")
    return {"sync": s, "frame": f, "compressed": not (lane(d, s, 1) >> 35) & 1,
            "length_field": length_field(d, s),
            "lanes": [f"{lane(d, s, n):010x}" for n in range(8)]}


def find_cram_raw(d, s, f):
    for r in range(2, MAX_PERIPHERY):
        p = s + r * f
        if frame_ok(d, p, f) and frame_ok(d, p + f, f):
            return r
    raise FormatError(f"no CRAM frame (CRC init {CRAM_INIT:#x}, F={f}) within {MAX_PERIPHERY} frames")


def find_cram_coded(d, s, f):
    for r in range(2, MAX_PERIPHERY):
        p = s + r * f
        if p >= len(d):
            break
        u, _ = nibble_decode(d[p:p + 4 * f], 2 * f)
        if len(u) >= 2 * f and frame_ok(u, 0, f) and frame_ok(u, f, f):
            return r
    probe = d[s + 4 * f:s + 4 * f + ENTROPY_PROBE]
    e = entropy(probe) if probe else 0
    msg = f"no coded CRAM frame (F={f}) within {MAX_PERIPHERY} frames; byte entropy after the header {e:.3f}"
    if e > ENCRYPTED_ENTROPY:
        msg += " (looks encrypted)"
    raise FormatError(msg)


def finish(out, s, h, info):
    """Trim the 0xFF tail to the Quartus postamble, check frames, fix header.  Returns bytes."""
    f, r = h["frame"], h["periphery_frames"]
    start = s + r * f
    n = cram_walk(out, start, f)
    end = start + n * f
    tail = out[end:]
    if tail.strip(b"\xff"):
        raise FormatError(f"CRAM CRC chain stops after {n} frames at {end:#x}; "
                          f"{len(tail.rstrip(b'\xff'))} non-0xFF bytes follow")
    if len(tail) < POSTAMBLE:
        raise FormatError(f"postamble {len(tail)} x 0xFF < {POSTAMBLE}")
    if len(tail) != POSTAMBLE:
        info["trimmed_ff_tail"] = len(tail) - POSTAMBLE
    out = bytearray(b"\xff" * PREAMBLE) + out[s:end] + b"\xff" * POSTAMBLE
    if s != PREAMBLE:
        info["preamble_in"] = s
    fix_header(out, PREAMBLE, len(out))
    info.update(cram_frames=n, cram_start=PREAMBLE + r * f, length=len(out),
                bits_per_frame=8 * (f - 2), cram_bits=8 * (f - 2) * n)
    return bytes(out)


def decompress(data, info=None):
    """Compressed (or uncompressed) Cyclone III/IV .rbf -> uncompressed .rbf as quartus_cpf writes it."""
    info = {} if info is None else info
    h = parse(data)
    info.update(h)
    s, f = h["sync"], h["frame"]
    if not h["compressed"]:
        h["periphery_frames"] = find_cram_raw(data, s, f)
        info["periphery_frames"] = h["periphery_frames"]
        return finish(bytearray(data), s, h, info)
    r = find_cram_coded(data, s, f)
    h["periphery_frames"] = info["periphery_frames"] = r
    body, left = nibble_decode(data[s + r * f:])
    info["leftover_nibbles"] = left
    out = bytearray(data[:s + r * f]) + body
    return finish(out, s, h, info)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rbf")
    ap.add_argument("-o", "--out")
    ap.add_argument("--info", action="store_true")
    a = ap.parse_args()
    data = open(a.rbf, "rb").read()
    info = {}
    try:
        out = decompress(data, info)
    except FormatError as e:
        for k, v in info.items():
            print(f"{k}: {v}")
        print(f"{a.rbf}: {e}", file=sys.stderr)
        return 2
    if a.info or not a.out:
        for k, v in info.items():
            print(f"{k}: {v}")
    if a.out:
        open(a.out, "wb").write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
