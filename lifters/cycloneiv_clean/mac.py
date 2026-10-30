"""Cyclone IV GX (EP4CGX150) embedded multiplier (MAC / MUL block) instances and control bits (#169).  Vendor groups + specimen-confirmed.

- Instance: MAC index = column rank * 90 + (Y - 1); column rank = ascending X among the MUL columns of the fitter geometry file.
- Control bits observed by pair builds (gxhb_macp{a,b}_*, one feature per pair, two MAC columns): see docs/cycloneiv-clean-hardblocks.md.
"""
import json

from . import fields as F
from .m9k import GEOM

MAC = 41                         # source: ASMDB_ARCH_GROUP_BLOCK_TYPE MAC (fields.PLACED)


def columns():
    kind = json.load(open(GEOM))["col_kind"]
    return sorted(int(x) for x, k in kind.items() if k == "MUL")


def instance(x, y):
    return columns().index(x) * F.ROWS_PER_COLUMN + (y - 1)
