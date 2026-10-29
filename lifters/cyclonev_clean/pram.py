"""Cyclone V PRAM claim map from vendor tables.

CFF address space A = 0 .. num_cff_bits-1 (asmdb DIE header). Extent bit b sits at A_high - b.
A -> (strip, position) needs the per-strip sizes: NOT derived from vendor files yet (docs/cyclonev-clean-pram.md).
With strip sizes given, serial position L = N-1-A, strips concatenated in order.
"""
import os

from . import asmdb

# source: Quartus install, quartus/common/devinfo/cyclonev/cyclonev_<die>/ddb_cyclonev_<die>_asmdb.ddb
def asmdb_path(die):
    root = os.environ.get("PLURIBUS_QUARTUS_DEVINFO")  # .../quartus/common/devinfo/cyclonev
    if not root:
        raise SystemExit("set PLURIBUS_QUARTUS_DEVINFO to quartus/common/devinfo/cyclonev")
    return os.path.join(root, f"cyclonev_{die}", f"ddb_cyclonev_{die}_asmdb.ddb")


def vendor_tables(die):
    """-> (header dict, extents rows, claim map)."""
    hdr, _blocks, rows = asmdb.load(asmdb_path(die))
    return hdr, rows, asmdb.claims(rows, hdr["num_cff_bits"])


def to_strip_pos(addr, ncff, strip_sizes):
    """A -> (strip, position within strip); strip_sizes must sum to ncff."""
    if sum(strip_sizes) != ncff:
        raise ValueError("strip sizes do not sum to num_cff_bits")
    pos = ncff - 1 - addr
    for s, n in enumerate(strip_sizes):
        if pos < n:
            return s, pos
        pos -= n
    raise ValueError("address out of range")
