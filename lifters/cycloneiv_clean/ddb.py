"""Raw loaders for the accepted vendor device files (A1, A2).  No coordinate conversion anywhere.

Parsers reused by import (checked clean of retired identifiers): scripts/cycloneiv_ddb_routing.py (fanout),
scripts/cycloneiv_ddb_asm.py (parse, group_sizes).  Loaders read their cached arrays under tmp/ddb/;
`build()` regenerates them (Quartus install required, minutes).
"""
import os
import sys

import numpy as np

from . import plane as P

# source: Quartus device directory name of EP4CGX150 (db/stingray4*.ddb)
DIE = "stingray4"
TMP = os.path.join(P.REPO, "tmp", "ddb")
SCRIPTS = os.path.join(P.REPO, "scripts")
# source: A2 asm.ddb entry = 31-bit absolute address + flag byte (docs/cycloneiv-ddb-format.md)
ADDR_MASK = 0x7FFFFFFF


class DdbMissing(FileNotFoundError):
    pass


def _need(path):
    if not os.path.exists(path):
        raise DdbMissing(f"{path} missing; run lifters.cycloneiv_clean.ddb.build()")
    return path


def build(die=DIE):
    sys.path.insert(0, SCRIPTS)
    import cycloneiv_ddb_asm as A
    import cycloneiv_ddb_routing as R
    R.fanout(die)
    A.parse(die)


class Routing:
    """routing.ddb: one row per record (element).  x, y are the raw vendor tile coordinates."""

    def __init__(self, die=DIE):
        z = np.load(_need(os.path.join(TMP, f"{die}_rt_fanout.npz")))
        self.x, self.y = z["x"], z["y"]                   # per record
        self.first_dest = z["V"]                          # per record, 0 = none
        self.tpl = z["tpl"]                               # per record -> template
        self.enum, self.z, self.index = z["enum"], z["z"], z["index"]      # per template
        self.cnt, self.eoff, self.offs = z["cnt"], z["eoff"], z["offs"]   # per template / edge offsets
        self.n = len(self.x)

    def fanout(self, rec):
        """Destination record ids of `rec`, in group order (edge k = asm group k)."""
        t = self.tpl[rec]
        if t < 0 or self.first_dest[rec] == 0:
            return np.zeros(0, np.int64)
        e = int(self.eoff[t])
        return self.first_dest[rec].astype(np.int64) + self.offs[e:e + int(self.cnt[t])]

    def element(self, rec):
        """(enum, x, y, z, index) straight from the file."""
        t = self.tpl[rec]
        return int(self.enum[t]), int(self.x[rec]), int(self.y[rec]), int(self.z[t]), int(self.index[t])

    def element_keys(self):
        """int64 key per record over (enum, x, y, z, index); records without a template get -1."""
        t = np.maximum(self.tpl, 0).astype(np.int64)
        k = (((self.enum[t].astype(np.int64) * 256 + self.x) * 256 + self.y) * 256 + self.z[t]) * 4096 + self.index[t]
        return np.where(self.tpl >= 0, k, -1)


def element_key(enum, x, y, z, index):
    return (((enum * 256 + x) * 256 + y) * 256 + z) * 4096 + index


class Asm:
    """asm.ddb: records in order, bits grouped per record.  addr = stored 31-bit value, flag bytes split out."""

    def __init__(self, die=DIE):
        g = lambda k: np.load(_need(os.path.join(TMP, f"{die}_asm_{k}.npy")), mmap_mode="r")
        self.pos = g("pos")                               # running sum of the stored deltas, per bit
        self.flag = g("flag")
        self.rec = g("rec")
        self.n, self.nb, self.voff, self.vals = g("n"), g("nb"), g("voff"), g("vals")
        self.bit0 = np.concatenate([[0], np.cumsum(np.asarray(self.nb), dtype=np.int64)])

    def addr(self, sl):
        return np.asarray(self.pos[sl], np.int64) & ADDR_MASK

    def flags(self, sl):
        """(b0, b1) signed bytes of the flag word."""
        f = np.asarray(self.flag[sl], np.int64)
        return ((f & 0xFF) ^ 0x80) - 0x80, (((f >> 8) & 0xFF) ^ 0x80) - 0x80

    def group_sizes(self, rec):
        """Fan-out group sizes of one record: vals[1:] plus the implicit last (nb - sum)."""
        n, nb, o = int(self.n[rec]), int(self.nb[rec]), int(self.voff[rec])
        if n == 0:
            return np.zeros(1, np.int64)
        explicit = np.asarray(self.vals[o + 1:o + n], np.int64)
        return np.concatenate([explicit, [nb - explicit.sum()]])

    def group_slice(self, rec, k):
        """Bit index range of group k of `rec`."""
        s = self.group_sizes(rec)
        a = int(self.bit0[rec]) + int(s[:k].sum())
        return slice(a, a + int(s[k]))
