"""Full object walk of the Cyclone IV GX asmdb ddb body and the per-site IO CFF bits.  Vendor-derived only (#165, #168).

Pool format (source: libdb_pdb PDB_SEGMENT_READER::xfr_ptr / finish_reading_all, static decompile; docs/cycloneiv-clean-io.md):
  - pointer tag u32: 0 null; bit1 set = back-reference (id += tag >> 2); else new object of class tag >> 2, appended to the
    declared pointer type's list; the type is pushed on a stack on first use.
  - after the main stream: pop the top type, read all its objects in creation order (nested new types go on the stack).
  - vector<uint> = u32 count + i32 deltas, running sum inside the vector; the first element is a delta against the first
    element of the previous vector of the same field (0 for the first).  i32 deltas elsewhere: against the previous object's field.
  - xfr_stl_ptr = one presence byte, then the container inline.
Field order per class: ASMDB_*::operator<< serializers in libdb_asmdb (reference/ghidra/structs.tsv).
Check: the walk consumes the body exactly and every class count equals the ddb type table (see tests).
"""
import struct
from collections import Counter

from . import io as IO

M32 = 0xFFFFFFFF
# source: ASMDB_DIE::operator<< pointer-field order (queue order of the declared pointer types decides the pop order)
# static pointer types: BI = ASMDB_BLOCK_INFO*, AG = ASMDB_ARCH_GROUP_BASE*, DG = ASMDB_DEFAULT_GROUP*,
# LSM = ASMDB_LABELED_SIMPLE_MUX*, MUX = ASMDB_MUX*, IMW = ASMDB_INDEX_MAP_WRAPPER (inline map, no pointer)


class _Static:
    def __init__(self):
        self.objs = [None]       # id 0 unused: back-references need id > 0
        self.next = 1
        self.last = 0
        self.queued = False


class Walk:
    def __init__(self, body=None):
        self.b = IO.asmdb_body() if body is None else body
        self.pos = 0
        self.S = {}
        self.stack = []
        self.first = {}          # vector field -> first element of the previous vector
        self.prev = {}           # i32 delta field -> previous value
        self._main()
        self._pools()

    # --- primitives
    def u32(self):
        self.pos += 4
        return struct.unpack_from("<I", self.b, self.pos - 4)[0]

    def i32(self):
        self.pos += 4
        return struct.unpack_from("<i", self.b, self.pos - 4)[0]

    def byte(self):
        self.pos += 1
        return self.b[self.pos - 1]

    def string(self):
        n = self.u32()
        s = self.b[self.pos:self.pos + n]
        self.pos += n
        return s.decode("latin1")

    def idelta(self, key):
        self.prev[key] = self.prev.get(key, 0) + self.i32()
        return self.prev[key]

    def vec_uint(self, key):
        n = self.u32()
        out, a = [], self.first.get(key, 0)
        for i in range(n):
            a = (a + self.i32()) & M32
            out.append(a)
        if n:
            self.first[key] = out[0]
        return out

    def ptr(self, static):
        t = self.u32()
        if t == 0:
            return None
        s = self.S.setdefault(static, _Static())
        if t & 1:
            raise ValueError(f"adjusted pointer tag {t:#x} at {self.pos:#x}")
        if t & 2:
            s.last += t >> 2
            return (static, s.last)
        s.objs.append({"cls": t >> 2})
        if not s.queued:
            s.queued = True
            self.stack.append(s)
        return (static, len(s.objs) - 1)

    def ptr_vec(self, static):
        return [self.ptr(static) for _ in range(self.u32())]

    # --- main stream (ASMDB_DIE fields up to m_hc_wires)
    def _main(self):
        self.u32()
        self.pos += 17
        for _ in range(4):
            self.string()
        for _ in range(self.u32()):
            self.u32()
            self.ptr("BI")
        for st in ("AG", "DG"):
            self.ptr_vec(st)
        self.default_bits, self.forced_bits = [], []          # default / forced bit lists: i32 deltas, running sum (docs/cycloneiv-address-spaces.md 3.1)
        for lst in (self.default_bits, self.forced_bits):
            a = 0
            for _ in range(self.u32()):
                a = (a + self.i32()) & M32
                lst.append(a)
        for st in ("LSM", "DG", "AG"):                        # labeled muxes, local default, local arch groups
            self.ptr_vec(st)
        for _ in range(3):                                    # hc nodes / fringe / wires (empty on IV)
            n = self.u32()
            self.pos += 4 * n
        self.main_end = self.pos

    # --- object readers, by ddb type-table class id
    def _base(self, o):
        o["gi"] = self.idelta("ag.gi")
        o["type"] = self.i32()                                # ASMDB_ARCH_GROUP_TYPE enum
        o["btype"] = self.i32()                               # ASMDB_ARCH_GROUP_BLOCK_TYPE enum

    def _mux_data(self):
        return {"av": self.byte(), "aux": self.ptr("MUX"), "nxt": self.ptr("MUX")}

    def _ag_std(self, o):
        self._base(o)
        o["paths"] = [self.ptr_vec("MUX") for _ in range(self.u32())]
        o["data"] = [self._mux_data() for _ in range(self.u32())]

    def _ag_calc(self, o):
        self._ag_std(o)
        o["bi"] = self.ptr("BI")
        o["gim"] = self.ptr("LSM")
        o["oim"] = self.ptr("LSM")

    def _ag_dumb(self, o):
        self._base(o)
        o["arch"] = self.byte()
        o["bits"] = self.vec_uint("dumb.bits")

    def _ag_stl(self, o):
        self._base(o)
        o["paths"] = [self.ptr_vec("MUX") for _ in range(self.u32())]
        o["data"] = [{"av": self.byte(), "aux": self.ptr("IMW"), "nxt": self.ptr("IMW"), "mask": self.ptr("IMW")}
                     for _ in range(self.u32())]

    def _mux(self, o):
        o["bits"] = self.vec_uint("mux.bits")

    def _imw(self, o):
        o["map"] = {}
        if self.byte():
            k = v = 0
            for _ in range(self.u32()):
                k += self.i32()
                v += self.i32()
                o["map"][k] = v

    def _block_info(self, o):
        o["s"] = [self.string() for _ in range(3)]
        self.first.pop("bi.list", None)     # first element is a delta vs 0 per BLOCK_INFO (LAB cells = body.bin run, #169)
        o["lists"] = {}
        for _ in range(self.u32()):
            k = self.i32()
            o["lists"][k] = self.vec_uint("bi.list") if self.byte() else []
        o["btype"] = self.i32()
        o["ram_cols"] = self.idelta("bi.ram")
        o["simple"] = {}
        for _ in range(self.u32()):
            k = self.i32()
            o["simple"][k] = self.u32()
        o["export"] = {}
        if self.byte():
            a = 0
            for _ in range(self.u32()):
                nm = self.string()
                a += self.i32()
                o["export"][nm] = a
        o["avalon"] = {}
        if self.byte():
            k = 0
            for _ in range(self.u32()):
                k += self.i32()
                o["avalon"][k] = (self.string(), self.idelta("av.addr"))
        o["asize"] = {self.string(): self.i32() for _ in range(self.u32())}

    def _readers(self):
        def with_map(o):
            self._mux(o)
            o["map"] = self.ptr("MUX")

        def decision(o):
            self._mux(o)
            o["lo"], o["hi"] = self.byte(), self.byte()

        def hetero(o):
            self._mux(o)
            o["bits2"] = self.vec_uint("mux.bits")

        def bank(o):
            self._mux(o)
            o["size"], o["bank"] = self.idelta("bank.size"), self.idelta("bank.bank")

        def ram(o):
            self._mux(o)
            o["pol"] = self.ptr("MUX")

        def stl_mapped(o):
            self._mux(o)
            o["im"] = self.ptr("IMW")

        def labeled(o):
            self._mux(o)
            o["name"] = self.string()

        def dms(o):
            o["ag"] = self.ptr("AG")
            o["setting"] = self.idelta("dms.setting")

        def dbc(o):
            o["arch"] = self.byte()
            o["bit"] = self.idelta("dbc.bit")
            o["bi"] = self.ptr("BI")

        return {2: self._block_info, 5: self._ag_calc, 6: self._ag_std, 7: self._ag_dumb, 8: self._ag_stl,
                10: dms, 11: dbc, 12: self._mux, 13: labeled, 14: with_map, 15: self._mux, 17: self._mux, 18: with_map,
                19: decision, 20: hetero, 21: bank, 22: ram, 24: stl_mapped, 26: self._imw}

    def _pools(self):
        rd = self._readers()
        while self.stack:
            s = self.stack.pop()
            s.queued = False
            while s.next < len(s.objs):
                o = s.objs[s.next]
                rd[o["cls"]](o)
                s.next += 1
        self.end = self.pos

    # --- views
    def class_counts(self):
        c = Counter()
        for s in self.S.values():
            c.update(o["cls"] for o in s.objs[1:])
        return dict(c)

    def block_infos(self):
        return self.S["BI"].objs[1:]

    def groups(self):
        return self.S["AG"].objs[1:]

    def mux(self, ref):
        return self.S["MUX"].objs[ref[1]]


def _site_bits(w, o, site):
    if o["cls"] == 7:
        return [o["bits"][site]]
    out = []
    for r in o["paths"][site]:
        if r:
            out += w.mux(r).get("bits", [])
    return out


def io_cff_sites(w, names):
    """{(block_type, site): {group name: [CFF bit index, ...]}} for the IO blocks (5 HIO, 6 VIO).

    names = ASMDB_ARCH_GROUP_TYPE enum -> name (scripts/cycloneiv_clean_dirt.py enum_tables()["arch_group_type"]).
    CFF bit = address with tag 101 in the top bits (IO.ADDRESS_SPACES); index = address & 0x1fffffff.
    """
    tab = {}
    for o in w.groups():
        if o["btype"] not in (5, 6) or o["cls"] not in (5, 6, 7):
            continue
        nm = names.get(o["type"], str(o["type"]))
        n = len(o["bits"]) if o["cls"] == 7 else len(o["paths"])
        for s in range(n):
            cf = [x & 0x1FFFFFFF for x in _site_bits(w, o, s) if x >> 29 == 5]
            if cf:
                tab.setdefault((o["btype"], s), {}).setdefault(nm, []).extend(cf)
    return tab
