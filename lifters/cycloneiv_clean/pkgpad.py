"""Cyclone IV GX package pins (pkg ddb) and pads (pad ddb): DEV_PIN / DEV_PAD_BODY object streams.  Vendor-derived only (#165, #168).

Layouts (source: libddb_dev DEV_PIN::operator<< @ 0x15e930, DEV_PAD_BODY::operator<<, QTL_BOOL_VECTOR operator<< @ 0x1751a0,
static decompile; field order and counts in reference/ghidra/structs.tsv):
  - i32 deltas run against the previous object's same field (ints), a QTL_BOOL_VECTOR is `u32 nbits` + ceil(nbits/32) i32 deltas,
    strings are `u32 len` + bytes (no padding), vector<int> = `u32 count` + deltas, string hash = `u32 count` + (string, string) pairs.
  - DEV_PIN: m_id, bool vector, 25 ints, 13 strings, 7 vector<int>, 4 string hashes, 5 enum-valid bool vectors, m_pad_id_list.
  - DEV_PAD_BODY: m_id, ptr tag, bool vector, 55 ints, 26 strings, 10 vector<vector<int>>, 4 string hashes, 5 doubles, 6 enum-valid
    bool vectors, io-standard ptr vector, 125 default io-standard ptr tags.
  - The object run starts after the root's own fields; the start is found by the exact-consumption check (all N objects parse and the
    body ends at the last byte), not fitted.
"""
import os
import re
import struct

from . import cycloneiv_io as IO

SENTINEL = {"pin": 896, "pad": 520}      # object counts from the ddb type tables (DEV_PIN 896, DEV_PAD_BODY 520)


class _R:
    def __init__(self, b, pos):
        self.b, self.pos = b, pos

    def u32(self):
        self.pos += 4
        return struct.unpack_from("<I", self.b, self.pos - 4)[0]

    def i32(self):
        self.pos += 4
        return struct.unpack_from("<i", self.b, self.pos - 4)[0]

    def string(self):
        n = self.u32()
        if n > 200:
            raise ValueError("string length")
        s = self.b[self.pos:self.pos + n]
        self.pos += n
        return s.decode("latin1")

    def chain(self, n, ref):
        out, a = [], ref
        for _ in range(n):
            a = (a + self.i32()) & 0xFFFFFFFF
            out.append(a)
        return out

    def boolvec(self, ref):
        n = self.u32()
        if n > 100000:
            raise ValueError("bool vector")
        w = self.chain((n + 31) // 32, ref)
        return n, w

    def hashes(self, k):
        out = []
        for _ in range(k):
            n = self.u32()
            if n > 1000:
                raise ValueError("hash")
            out.append([(self.string(), self.string()) for _ in range(n)])
        return out


def _read_pin(r, st):
    o = {}
    st["id"] = (st["id"] + r.i32()) & 0xFFFFFFFF
    o["id"] = st["id"]
    n, w = r.boolvec(st["bool"])
    st["bool"] = w[0] if w else st["bool"]
    o["bool"] = (n, w)
    o["ints"] = []
    for i in range(25):
        st["ints"][i] = (st["ints"][i] + r.i32()) & 0xFFFFFFFF
        o["ints"].append(st["ints"][i])
    o["strs"] = [r.string() for _ in range(13)]
    o["vecs"] = []
    for v in range(7):
        x = r.chain(r.u32(), st["vec"][v])
        st["vec"][v] = x[0] if x else st["vec"][v]
        o["vecs"].append(x)
    o["hash"] = r.hashes(4)
    o["enum"] = []
    for e in range(5):
        n, w = r.boolvec(st["enum"][e])
        st["enum"][e] = w[0] if w else st["enum"][e]
        o["enum"].append((n, w))
    o["pad_raw"] = r.chain(r.u32(), 0)           # raw deltas: element k of the k-th pad-bearing pin = k (see pin_pad_rank)
    return o


def _read_pad(r, st):
    o = {}
    st["id"] = (st["id"] + r.i32()) & 0xFFFFFFFF
    o["id"] = st["id"]
    r.u32()                                      # ptr tag
    n, w = r.boolvec(st["bool"])
    st["bool"] = w[0] if w else st["bool"]
    o["bool"] = (n, w)
    o["ints"] = []
    for i in range(55):
        st["ints"][i] = (st["ints"][i] + r.i32()) & 0xFFFFFFFF
        o["ints"].append(st["ints"][i])
    o["strs"] = [r.string() for _ in range(26)]
    for _ in range(10):
        k = r.u32()
        if k > 1000:
            raise ValueError("2d")
        for _ in range(k):
            r.chain(r.u32(), 0)
    o["hash"] = r.hashes(4)
    r.pos += 40                                  # 5 doubles
    for e in range(6):
        n, w = r.boolvec(st["enum"][e])
        st["enum"][e] = w[0] if w else st["enum"][e]
    k = r.u32()
    o["iostd"] = [r.u32() for _ in range(k)]
    o["defstd"] = [r.u32() for _ in range(125)]
    return o


def _scan(b, reader, fresh, count, lo, hi):
    for start in range(lo, hi):
        r, st = _R(b, start), fresh()
        try:
            objs = [reader(r, st) for _ in range(count)]
        except (ValueError, struct.error):
            continue
        if r.pos == len(b):
            return objs
    raise ValueError("no start offset consumes the body exactly")


def _body(name):
    from . import sofio
    return IO.asmdb_body(os.path.normpath(os.path.join(sofio.quartus_bin(), "..", "common", "devinfo", "cycloneivgx", name)))


def _pkg_pin_count(name):
    """DEV_PIN object count of a pkg ddb: its type-table trailer (xz) lists `DEV_PIN` with the count."""
    import lzma
    import sys
    from . import sofio
    sys.path.insert(0, os.path.join(IO.P.REPO, "scripts"))
    import cyclonev_ddb_decode as dd
    path = os.path.normpath(os.path.join(sofio.quartus_bin(), "..", "common", "devinfo", "cycloneivgx", name))
    t = lzma.decompress(open(path, "rb").read()[dd.read_header(path).body_end:])
    o = 2
    for _ in range(struct.unpack_from("<H", t, 0)[0]):
        _i, _sz, _crc, cnt, _ver, nl = struct.unpack_from("<HIIIII", t, o)
        o += 22
        if t[o:o + nl - 1] == b"DEV_PIN":
            return cnt
        o += nl - 1
    raise ValueError("no DEV_PIN in " + name)


def package_pins(device):
    """Pin count of an Altera part name (EP4CGX150DF31C7 -> 896): `part.pin_count` of the Quartus device.db (names are base64)."""
    import base64
    import sqlite3
    from . import sofio
    path = os.path.normpath(os.path.join(sofio.quartus_bin(), "..", "common", "devinfo", "device.db"))
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    for n, k in c.execute("select name, pin_count from part"):
        if base64.b64decode(n).decode() == device:
            return k
    raise ValueError("part not in device.db: " + device)


_PINS = {}


def pins(count=896):
    """The DEV_PIN objects of one EP4CGX150 package (ddb_stingray4fbga<count>_pkg.ddb); default F896.  Start offset = exact-consumption scan."""
    if count not in _PINS:
        name = f"ddb_stingray4fbga{count}_pkg.ddb"
        assert _pkg_pin_count(name) == count, (name, count)
        fresh = lambda: {"id": 0, "bool": 0, "ints": [0] * 25, "vec": [0] * 7, "enum": [0] * 5}
        _PINS[count] = _scan(_body(name), _read_pin, fresh, count, 0 if count != 896 else 4396, 20000 if count != 896 else 14600)
    return _PINS[count]


def pin_pad(pin_list):
    """-> {pin index: pad index} for any package: a pad-bearing pin's single pad_raw element is the pad's 0-based index in the die pad table.
    (F896: element k of the k-th pad-bearing pin = k, so equal to pin_pad_rank.)"""
    return {i: p["pad_raw"][0] for i, p in enumerate(pin_list) if p["pad_raw"]}


def pads():
    """The 520 DEV_PAD_BODY objects (ddb_stingray4_pad.ddb); strs[1] = site X<x>Y<y>SUB_LOC<n>, strs[3] = pad class, strs[4] = function."""
    b = _body("ddb_stingray4_pad.ddb")
    fresh = lambda: {"id": 0, "bool": 0, "ints": [0] * 55, "enum": [0] * 6}
    i = b.find(b"SUB_LOC")
    return _scan(b, _read_pad, fresh, SENTINEL["pad"], i - 1500, i)


SITE = re.compile(r"X(\d+)Y(\d+)SUB_LOC(\d+)")


def pad_site(p):
    m = SITE.fullmatch(p["strs"][1])
    return tuple(map(int, m.groups()))


def pin_pad_rank(pin_list):
    """-> {pin index: pad index}.  A pin with a pad carries exactly one pad id; the k-th pad-bearing pin links pad k (0-based).

    Evidence: the raw m_pad_id_list deltas are 0, 1, 2, ... (not the ids); 400 / 400 oracle balls (build.pin x postfit.vo) land on
    the pad whose site string equals the placed IOBUF (tests/cycloneiv_clean/test_pkgpad.py).
    """
    out, k = {}, 0
    for i, p in enumerate(pin_list):
        if p["pad_raw"]:
            out[i] = k
            k += 1
    return out


def io_site_pads(pad_list):
    """-> {(block_type, site): pad index}: HIO sites (block type 5) = 'Row I/O' pads in pad order, VIO (6) = 'Column I/O' pads."""
    row = [j for j, p in enumerate(pad_list) if p["strs"][3] == "Row I/O"]
    col = [j for j, p in enumerate(pad_list) if p["strs"][3] == "Column I/O"]
    return {**{(5, s): j for s, j in enumerate(row)}, **{(6, s): j for s, j in enumerate(col)}}
