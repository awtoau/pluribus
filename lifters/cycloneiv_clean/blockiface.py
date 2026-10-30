"""routing.ddb block interfaces: which BLOCK_INPUT_MUX (LEIM) index drives which pin of a block (#171).  Vendor-derived only.

Schema (source: DYGR_ROUTE_BLOCK_INTERFACE / _NODE / _CONNECTION ::operator<< libddb_dygr 0x2cfca0 / 0x2c7190 / 0x2c6fd0, scripts/cycloneiv_ddb_symdump.py):
  interface = (m_type i32, m_name string, map<element enum, vector<node*>>, map<alias, node*>, m_is_explicit bool).
  node      = (element enum, index, subloc, specialized index, tile x offset, timing id: i16/i32 deltas; alias string; connections).
  connection = (element enum i32, port type, driver idx, exact x, exact y, z, index, load pos, sram1, sram2: deltas; is_input bool).
Pool layout in the inflated body: 28 interface objects back to back, then 983 node objects in registration order (the NEW tags of the interface
vectors, in interface order).  Deltas run per class over the whole pool (docs/cycloneiv-ddb-format.md stream layer).
Type 1 interfaces (VIO_L, VIO_R, HIO, ...) hold BLOCK_INPUT_MUX nodes; a node's connection to element IO is (port type, z = SUB_LOC, index):
the pad pin the BIM drives.  Port type = DB_INPUT_PORT_TYPE (libdb_dbs.so DB_INPUT_PORT_TYPE_STRING), element enum = DEV_ELEMENT_ENUM
(reference/ghidra/enums.tsv).  Parsed once, cached as tmp/ddb/<die>_block_interfaces.json.
"""
import json
import os
import re
import struct
import subprocess
import sys

from . import ddb
from . import plane as P

# source: PDB stream layer (docs/cycloneiv-ddb-format.md): pointer tag low bits 00 = NEW object, 10 = reference (d << 2 | 2)
TAG_NEW, TAG_REF = 0, 2
# source: DYGR_ROUTE_BLOCK_INTERFACE_NODE / _CONNECTION operator<< field widths above: node header 5 x i16 + i32, connection 3 x i32 + 7 x i16 + bool
NODE_HEAD, CONN_SIZE = "<5hi", 27
LIB_DBS = "libdb_dbs.so"
SYMBOL_INPUT_PORT = "DB_INPUT_PORT_TYPE_STRING"
ENUMS_TSV = os.path.join(P.REPO, "reference", "ghidra", "enums.tsv")


def _lib(name):
    sys.path.insert(0, ddb.SCRIPTS)
    import cycloneiv_ddb_symdump as S
    return os.path.join(os.path.dirname(S.LIB), name)


def input_port_names():
    """DB_INPUT_PORT_TYPE value -> name (pointer table DB_INPUT_PORT_TYPE_STRING of libdb_dbs.so, R_X86_64_RELATIVE addends)."""
    lib = _lib(LIB_DBS)
    sym = subprocess.run(["nm", "-D", "-S", "--defined-only", lib], capture_output=True, text=True).stdout
    base, size = next((int(l.split()[0], 16), int(l.split()[1], 16)) for l in sym.splitlines() if l.endswith(" " + SYMBOL_INPUT_PORT))
    rel = {}
    for l in subprocess.run(["readelf", "-rW", lib], capture_output=True, text=True).stdout.splitlines():
        p = l.split()
        if len(p) >= 4 and p[2] == "R_X86_64_RELATIVE":
            rel[int(p[0], 16)] = int(p[3], 16)
    secs = [(int(m[3], 16), int(m[4], 16), int(m[5], 16)) for m in re.finditer(
        r"\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)", subprocess.run(["readelf", "-SW", lib], capture_output=True, text=True).stdout)
        if m[2] != "NOBITS"]
    data = open(lib, "rb").read()

    def string_at(va):
        for a, o, sz in secs:
            if a <= va < a + sz:
                return data[o + va - a:data.index(b"\0", o + va - a)].decode()
    out, i = {}, 0
    while 8 * i < size:
        out[i] = string_at(rel[base + 8 * i])
        i += 1
    return out


def dev_enums():
    """DEV_ELEMENT_ENUM name -> value (reference/ghidra/enums.tsv, generated from libddb_dstr)."""
    out = {}
    for l in open(ENUMS_TSV):
        p = l.rstrip("\n").split("\t")
        if len(p) >= 4 and p[1] == "DEV_ELEMENT_ENUM":
            out[p[3]] = int(p[2])
    return out


def die(msg):
    raise SystemExit("blockiface: " + msg)


def _u32(b, p):
    return struct.unpack_from("<I", b, p)[0]


def _str(b, p):
    n = _u32(b, p)
    return b[p + 4:p + 4 + n].decode("latin1"), p + 4 + n


def _tag(t):
    if t & 3 == TAG_NEW and t:
        return ("new", t >> 2)
    if t & 3 == TAG_REF:
        d = t >> 2
        return ("ref", d - (1 << 30) if d >= 1 << 29 else d)
    return ("null", 0)


def _interface(b, p):
    typ = _u32(b, p)
    name, p = _str(b, p + 4)
    n, p = _u32(b, p), p + 4
    vecs = []
    for _ in range(n):
        key, cnt = _u32(b, p), _u32(b, p + 4)
        vecs.append((key, [_tag(_u32(b, p + 8 + 4 * i)) for i in range(cnt)]))
        p += 8 + 4 * cnt
    n, p = _u32(b, p), p + 4
    alias = []
    for _ in range(n):
        s, p = _str(b, p)
        alias.append((s, _tag(_u32(b, p))))
        p += 4
    return dict(type=typ, name=name, vecs=vecs, alias=alias), p + 1


def _node(b, p, st):
    h = struct.unpack_from(NODE_HEAD, b, p)
    st["head"] = [a + d for a, d in zip(st["head"], h)]
    alias, p = _str(b, p + struct.calcsize(NODE_HEAD))
    n, p = _u32(b, p), p + 4
    conns = []
    for _ in range(n):
        c = struct.unpack_from("<iii7hB", b, p)
        p += CONN_SIZE
        st["conn"] = [0] + [st["conn"][k] + c[k] for k in range(1, 10)]
        conns.append(dict(enum=c[0], port=st["conn"][1], driver=st["conn"][2], x=st["conn"][3], y=st["conn"][4], z=st["conn"][5],
                          index=st["conn"][6], load=st["conn"][7], sram1=st["conn"][8], sram2=st["conn"][9]))
    hd = st["head"]
    return dict(enum=hd[0], index=hd[1], subloc=hd[2], alias=alias, conns=conns), p


def parse(body):
    """-> list of interfaces {type, name, nodes: [{enum, index, subloc, alias, conns}]} (checks: pool ends, counts, registration order)."""
    first = body.find(struct.pack("<I", 0) + struct.pack("<I", 4) + b"HIOL" + struct.pack("<I", 1))
    if first < 0:
        die("block interface pool (first interface HIOL) not found")
    p, ifs = first, []
    while True:
        try:
            d, q = _interface(body, p)
        except (struct.error, ValueError, UnicodeDecodeError, OverflowError, MemoryError):
            break
        if not (0 <= d["type"] <= 1) or not re.fullmatch(r"[A-Z0-9_]+", d["name"]):
            break
        ifs.append(d)
        p = q
    n_nodes = sum(len(v) for d in ifs for _, v in d["vecs"])
    if len(ifs) != 28 or n_nodes != 983:           # source: docs/cycloneiv-ddb-format.md type table (28 interfaces, 983 nodes)
        die(f"block interfaces: {len(ifs)} interfaces / {n_nodes} nodes (type table says 28 / 983)")
    st, nodes = dict(head=[0] * 6, conn=[0] * 10), []
    for _ in range(n_nodes):
        n, p = _node(body, p, st)
        nodes.append(n)
    k = 0
    for d in ifs:
        d["nodes"] = []
        for key, tags in d.pop("vecs"):
            for t in tags:
                if t[0] != "new" or nodes[k]["enum"] != key:
                    die(f"block interface {d['name']}: node {k} is not a NEW object of element {key}")
                d["nodes"].append(nodes[k])
                k += 1
        d.pop("alias")
    return ifs


def load(die=ddb.DIE):
    path = os.path.join(ddb.TMP, f"{die}_block_interfaces.json")
    if os.path.exists(path):
        return json.load(open(path))
    sys.path.insert(0, ddb.SCRIPTS)
    import cycloneiv_ddb_routing as R
    ifs = parse(R.body(die))
    json.dump(ifs, open(path, "w"))
    return ifs


class Pins:
    """(interface, DB_INPUT_PORT_TYPE name, z, index) -> BLOCK_INPUT_MUX index, from the type 1 interfaces' connections to element IO."""

    def __init__(self, die=ddb.DIE):
        self.die = die
        self.clkbuf_enum = dev_enums()["CLKBUFBLOCK"]
        ports = {v: k for k, v in input_port_names().items()}
        self.ports = ports
        io = dev_enums()["IO"]
        bim = dev_enums()["LEIM"]
        self.table = {}
        for d in load(die):
            if d["type"] != 1:
                continue
            for n in d["nodes"]:
                if n["enum"] != bim:
                    continue
                for c in n["conns"]:
                    if c["enum"] == io:
                        key = (d["name"], c["port"], c["z"], c["index"])
                        if key in self.table:
                            die(f"block interface {key}: two BLOCK_INPUT_MUX nodes drive one IO pin")
                        self.table[key] = n["index"]

    def bim(self, interface, port, z, index=0):
        """BLOCK_INPUT_MUX index driving pin `port` (DB_INPUT_PORT_TYPE name, e.g. "DATAIN") of IO sub location z, or -1."""
        return self.table.get((interface, self.ports[port], z, index), -1)

    def clkbuf(self, interface):
        """{BLOCK_INPUT_MUX index: [(z, index) of the CLKBUF_IN it feeds]}: connections of one type 1 interface to pin INCLK[index] of element
        CLKBUFBLOCK (z = clock buffer; the other pins, ENA and CLKSELECT, are control pins)."""
        out = {}
        for d in load(self.die):
            if d["type"] == 1 and d["name"] == interface:
                for n in d["nodes"]:
                    for c in n["conns"]:
                        if c["enum"] == self.clkbuf_enum and c["port"] == self.ports["INCLK"]:
                            out.setdefault(n["index"], []).append((c["z"], c["index"]))
        return out

    def li_count(self, interface):
        """Number of LOCAL_INTERCONNECT (LAB_LINE) nodes of a type 0 interface (HIOL, HIOR, LAB, MAC, MEAB, VIO)."""
        lab_line = dev_enums()["LAB_LINE"]
        return next(sum(1 for n in d["nodes"] if n["enum"] == lab_line) for d in load(self.die) if d["type"] == 0 and d["name"] == interface)
