#!/usr/bin/env python3.15t
"""Cyclone V `.ddb` container decoder (Quartus devinfo files). Format: docs/cyclonev-ddb-format.md.

Streams the body (never holds more than one 1 MiB block of inflated output plus the compressed file);
peak RSS is the file size + a few MB, independent of the 268 MB+ inflated size.

  python3.15t scripts/cyclonev_ddb_decode.py check FILE...        # header, body length, trailer; exit 1 on any error
  python3.15t scripts/cyclonev_ddb_decode.py check --dir DIR      # every *.ddb under DIR (recursive), one at a time
  python3.15t scripts/cyclonev_ddb_decode.py types FILE           # trailer type table
  python3.15t scripts/cyclonev_ddb_decode.py hdr FILE             # device header strings (hdr.ddb)
  python3.15t scripts/cyclonev_ddb_decode.py dump FILE [OUT]      # inflated body to OUT (or stdout size only)
Log: tmp/logs/cyclonev_ddb_decode.log
"""
import argparse
import lzma
import logging
import os
import re
import struct
import sys
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = logging.getLogger("cyclonev_ddb_decode")

BLOCK = 1 << 20
HEADER_LEN = 0x73
MAGIC_LO = 0x0BAD
METHOD_ZLIB, METHOD_XZ = 0, 1


class DdbError(Exception):
    pass


class Header:
    """Fixed 0x73-byte header (all little endian)."""
    def __init__(self, b, file_size):
        if len(b) < HEADER_LEN:
            raise DdbError("short file")
        self.hdr_off, self.magic, self.zero, self.len_a, self.len_b, self.str_len = struct.unpack_from("<IIIHHI", b, 0)
        if self.hdr_off != 0x14 or (self.magic & 0xFFFF) != MAGIC_LO or self.len_a != HEADER_LEN or self.len_b != HEADER_LEN:
            raise DdbError(f"not a ddb container: {b[:16].hex()}")
        self.kind = self.magic >> 16
        n = self.str_len - 1  # length field counts a NUL that is not stored
        self.version = b[0x14:0x14 + n].decode("ascii", "replace")
        self.raw_size, self.body_end, self.types_raw = struct.unpack_from("<QQQ", b, 0x14 + n)
        self.method, = struct.unpack_from("<I", b, 0x14 + n + 24)
        self.file_size, = struct.unpack_from("<Q", b, 0x14 + n + 28)
        self.file_len = file_size
        if self.hdr_off + n + 36 != HEADER_LEN:
            raise DdbError("unexpected header length for this version string")
        if self.file_size != file_size:
            raise DdbError(f"size field {self.file_size} != file size {file_size}")
        if self.method not in (METHOD_ZLIB, METHOD_XZ):
            raise DdbError(f"unknown compression method {self.method}")
        if not HEADER_LEN <= self.body_end <= file_size:
            raise DdbError(f"body end {self.body_end} outside file")


def _decomp(method):
    return zlib.decompressobj() if method == METHOD_ZLIB else lzma.LZMADecompressor()


def read_header(path):
    with open(path, "rb") as f:
        b = f.read(HEADER_LEN)
    return Header(b, os.path.getsize(path))


def iter_body(path, hdr=None, block=BLOCK):
    """Yield inflated body blocks; raise DdbError unless the stream yields exactly `raw_size` bytes."""
    hdr = hdr or read_header(path)
    with open(path, "rb") as f:
        f.seek(HEADER_LEN)
        comp = f.read(hdr.body_end - HEADER_LEN)
    d = _decomp(hdr.method)
    total = 0
    try:
        for i in range(0, len(comp), 1 << 16):
            out = d.decompress(comp[i:i + (1 << 16)])
            total += len(out)
            for j in range(0, len(out), block):
                yield out[j:j + block]
    except (zlib.error, lzma.LZMAError) as e:
        raise DdbError(f"inflate error after {total} bytes: {e}")
    if hdr.method == METHOD_ZLIB:
        # zlib body = sync-flushed deflate, no final block, no adler: ends exactly at body_end
        if d.eof or d.unused_data:
            raise DdbError("zlib body ended early or has trailing bytes")
    elif not d.eof:
        raise DdbError("xz body not terminated")
    if total != hdr.raw_size:
        raise DdbError(f"body is {total} bytes, header says {hdr.raw_size}")


def read_types(path, hdr=None):
    """Trailer: type table [(id, sizeof, layout_crc, count, version, name)]."""
    hdr = hdr or read_header(path)
    with open(path, "rb") as f:
        f.seek(hdr.body_end)
        t = f.read()
    d = _decomp(hdr.method)
    try:
        raw = d.decompress(t)
    except (zlib.error, lzma.LZMAError) as e:
        raise DdbError(f"trailer inflate error: {e}")
    if len(raw) != hdr.types_raw:
        raise DdbError(f"trailer is {len(raw)} bytes, header says {hdr.types_raw}")
    n, = struct.unpack_from("<H", raw, 0)
    p, out = 2, []
    for _ in range(n):
        tid, size, crc, cnt, ver, nl = struct.unpack_from("<HIIIII", raw, p)
        name = raw[p + 22:p + 21 + nl].decode("ascii", "replace")
        p += 21 + nl
        out.append((tid, size, crc, cnt, ver, name))
    if p != len(raw):
        raise DdbError(f"trailer has {len(raw) - p} unparsed bytes")
    if [t[0] for t in out] != list(range(1, n + 1)):
        raise DdbError("type ids not 1..n")
    return out


def check(path):
    """Full verification of one file. Returns (hdr, n_types). Raises DdbError."""
    hdr = read_header(path)
    total = 0
    for blk in iter_body(path, hdr):
        total += len(blk)
    types = read_types(path, hdr)
    return hdr, types


def read_u32_str(body, p):
    n, = struct.unpack_from("<I", body, p)
    return body[p + 4:p + 4 + n].decode("ascii", "replace"), p + 4 + n


def hdr_strings(path):
    """Length-prefixed ASCII strings in the first 0x500 bytes of a *_hdr.ddb body, from the device name on."""
    hdr = read_header(path)
    body = next(iter_body(path, hdr))[:0x500]
    out, p = [], 0
    while p < len(body) - 4:
        n, = struct.unpack_from("<I", body, p)
        s = body[p + 4:p + 4 + n]
        if 3 <= n <= 40 and re.fullmatch(rb"[\x20-\x7e]+", s):
            out.append(s.decode())
            p += 4 + n
        else:
            p += 1
    start = next((i for i, s in enumerate(out) if s.startswith("5C")), 0)
    return out[start:], hdr.raw_size


DEVINFO = "/mnt/2tb/opt/altera/quartus-25.1/quartus/common/devinfo"


def _b64(s):
    import base64
    try:
        return base64.b64decode(s, validate=True).decode()
    except Exception:
        return s


def die_map(devinfo=DEVINFO, mistral_models=None):
    """Quartus device.db (names are base64) + per-die hdr.ddb -> {die dir: {...}}; idcodes from Mistral models.txt if given."""
    import sqlite3
    c = sqlite3.connect(f"file:{devinfo}/device.db?mode=ro", uri=True)
    fam = {i: _b64(n) for i, n in c.execute("select id, name from family")}
    out = {}
    for _, name, disp, base, fid, dsp, lr in c.execute(
            "select id, name, display_name, base_device_debug_name, family_id, dsp_count, logic_resource_count from die"):
        if fam[fid] != "CYCLONEV":
            continue
        name, disp, base = _b64(name), _b64(disp), _b64(base)
        if name.endswith("_SC_V"):
            continue
        e = out.setdefault(base.lower(), dict(variants={}, alms=lr, dsp=dsp))
        e["variants"][name] = disp
    ids = {}
    if mistral_models and os.path.exists(mistral_models):
        for line in open(mistral_models):
            t = line.split()
            if t and t[0] == "variant":
                kv = dict(x.split(":", 1) for x in t[2:])
                ids[t[1].upper()] = int(kv["idcode"], 16)
    for d, e in out.items():
        short = d.replace("cyclonev_", "")
        e["dir"] = os.path.join(devinfo, "cyclonev", "cyclonev_" + short)
        hd = os.path.join(e["dir"], f"ddb_cyclonev_{short}_hdr.ddb")
        e["hdr_strings"] = hdr_strings(hd)[0][:6] if os.path.exists(hd) else None
        e["idcodes"] = sorted({f"{v:04x}" for k, v in ids.items()
                               if any(n.split("CYCLONEV_")[1].split("_V")[0] == k for n in e["variants"])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("check", "types", "hdr", "dump", "diemap"))
    ap.add_argument("files", nargs="*")
    ap.add_argument("--dir")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_ddb_decode.log"))])
    files = list(a.files)
    if a.dir:
        for r, _, fs in os.walk(a.dir):
            files += [os.path.join(r, f) for f in sorted(fs) if f.endswith(".ddb")]
        files.sort()
    if a.cmd == "check":
        bad = 0
        kinds = {}
        for f in files:
            try:
                h, t = check(f)
                kinds[(hex(h.magic), h.method)] = kinds.get((hex(h.magic), h.method), 0) + 1
                log.info("OK   %s raw=%d types=%d method=%d kind=%#x", os.path.basename(f), h.raw_size, len(t), h.method, h.kind)
            except DdbError as e:
                bad += 1
                log.error("FAIL %s: %s", os.path.basename(f), e)
        log.info("checked %d files, %d failed; (magic, method) counts: %s", len(files), bad, kinds)
        sys.exit(1 if bad else 0)
    if a.cmd == "diemap":
        models = os.environ.get("PLURIBUS_MISTRAL_ROOT", "/mnt/2tb/git/mistral") + "/data/models.txt"
        for d, e in sorted(die_map(mistral_models=models).items()):
            print(f"{d}: alms={e['alms']} dsp={e['dsp']} hdr={e['hdr_strings']} idcode16={e['idcodes']}")
            print("   variants:", ", ".join(f"{k.split('CYCLONEV_')[1]}={v}" for k, v in sorted(e["variants"].items())))
        return
    for f in files:
        if a.cmd == "types":
            for t in read_types(f):
                print(*t)
        elif a.cmd == "hdr":
            print(f, *hdr_strings(f)[0])
        elif a.cmd == "dump":
            out = open(a.files[1], "wb") if len(a.files) > 1 else None
            n = 0
            for blk in iter_body(a.files[0]):
                n += len(blk)
                if out:
                    out.write(blk)
            print(n)
            break


if __name__ == "__main__":
    main()
