"""Chip geometry: tile-name -> (row, col), max_row/col, get_tiles_by_position.

Ported from prjtrellis:
  - Database.cpp  get_chip_info / get_device_tilegrid
  - Tile.cpp      get_row_col_pair_from_chipsize (+ regexes, center_map, clk_col)
  - Chip.cpp      Chip() ctor loop + get_tiles_by_position / get_max_row/col
"""
import json
import os
import re

# --- tile-name regexes (Tile.cpp:9-25) -- regex_search semantics (may match
#     anywhere in the name), evaluated in the exact precedence order below. -----
_RXCX = re.compile(r"R(\d+)C(\d+)")
_CENTER = re.compile(r"CENTER(\d+)")
_CENTERB = re.compile(r"CENTER_B")
_CENTERT = re.compile(r"CENTER_T")
_CENTEREBR = re.compile(r"CENTER_EBR(\d+)")
_T = re.compile(r"[A-Za-z0-9_]*T(\d+)")
_B = re.compile(r"[A-Za-z0-9_]*B(\d+)")
_L = re.compile(r"[A-Za-z0-9_]*L(\d+)")
_R = re.compile(r"[A-Za-z0-9_]*R(\d+)")
_CLK_DUMMY = re.compile(r"CLK_DUMMY(\d+)")
_CLK_DUMMY_B = re.compile(r"CLK_DUMMY_PICB")
_CLK_DUMMY_T = re.compile(r"CLK_DUMMY_PICT")

# center_map (Tile.cpp:32-47): zero-indexed max chip_size -> zero-indexed center
CENTER_MAP = {
    (7, 9): (6, 4),      # LCMXO2-256
    (8, 17): (7, 7),     # LCMXO2-640
    (12, 21): (6, 12),   # LCMXO2-1200, LCMXO3-1300
    (15, 25): (8, 13),   # LCMXO2-2000, LCMXO3-2100
    (22, 31): (11, 15),  # LCMXO2-4000, LCMXO3-4300
    (27, 40): (17, 18),  # LCMXO2-7000, LCMXO3-6900
    (31, 48): (15, 24),  # LCMXO3-9400
}

# clk_col (Tile.cpp:49-58): keyed by (rows, cols) as used for MachXO-family
# CLK_DUMMY tiles.  MachXO2 devices generally lack CLK_DUMMY tiles, but keep the
# table faithful for completeness.
CLK_COL = {
    (9, 5): 2,     # LCMXO256
    (11, 9): 4,    # LCMXO640
    (16, 11): 5,   # LCMXO1200
    (20, 16): 8,   # LCMXO2280
}


def get_row_col(name, chip_size, row_bias, col_bias):
    """Port of get_row_col_pair_from_chipsize (Tile.cpp:61).

    `chip_size` is (max_row, max_col).  Returns zero-indexed (row, col).
    """
    cs = tuple(chip_size)

    # Special CENTERnn cases (Tile.cpp:64-71)
    if "CENTER30" in name and cs == (27, 40):
        return (20, CENTER_MAP[cs][1])
    if "CENTER33" in name:
        return (8, CENTER_MAP[cs][1])
    if "CENTER35" in name:
        return (22, CENTER_MAP[cs][1])

    # CLK_DUMMY family (Tile.cpp:72-81)
    if _CLK_DUMMY_T.search(name):
        return (0, CLK_COL[cs])
    if _CLK_DUMMY_B.search(name):
        return (cs[0], CLK_COL[cs])
    m = _CLK_DUMMY.search(name)
    if m:
        return (int(m.group(1)) - row_bias, CLK_COL[cs])
    if name.startswith("CLK") and "_2K" in name:
        return (int(name[7:]) - row_bias, CLK_COL[cs])
    if name.startswith("CLK"):
        return (int(name[4:]) - row_bias, CLK_COL[cs])

    # EBR RxxC0 (MachXO only, row_bias==1) -- Tile.cpp:82-84
    m = _RXCX.search(name)
    if "EBR" in name and m and row_bias == 1:
        return (int(m.group(1)) - row_bias, int(m.group(2)) - col_bias + 1)

    # General RxCx (Tile.cpp:85-90)
    if m:
        if cs == (22, 31):
            if (int(m.group(2)) - col_bias) > 31:  # LCMXO3D-4300 fix
                return (int(m.group(1)), int(m.group(2)) - col_bias - 1)
        return (int(m.group(1)) - row_bias, int(m.group(2)) - col_bias)

    # CENTER_T / CENTER_B / CENTER_EBR / CENTER (Tile.cpp:91-98)
    if _CENTERT.search(name):
        return (0, CENTER_MAP[cs][1])
    if _CENTERB.search(name):
        return (cs[0], CENTER_MAP[cs][1])
    if _CENTEREBR.search(name):
        return (CENTER_MAP[cs][0], CENTER_MAP[cs][1])
    m = _CENTER.search(name)
    if m:
        return (int(m.group(1)) - row_bias, CENTER_MAP[cs][1])

    # Edge tiles T/B/L/R (Tile.cpp:99-106)
    m = _T.search(name)
    if m:
        return (0, int(m.group(1)) - col_bias)
    m = _B.search(name)
    if m:
        return (cs[0], int(m.group(1)) - col_bias)
    m = _L.search(name)
    if m:
        return (int(m.group(1)) - row_bias, 0)
    m = _R.search(name)
    if m:
        return (int(m.group(1)) - row_bias, cs[1])

    raise RuntimeError(f"Could not extract position from {name}")


def load_device_info(device, db_root, family="MachXO2"):
    """Port of get_chip_info (Database.cpp): read devices.json for the part."""
    dj = json.load(open(os.path.join(db_root, "devices.json")))
    dev = dj["families"][family]["devices"][device]
    return {
        "family": family,
        "max_row": int(dev["max_row"]),
        "max_col": int(dev["max_col"]),
        "row_bias": int(dev["row_bias"]),
        "col_bias": int(dev["col_bias"]),
        "num_frames": int(dev["frames"]),
        "bits_per_frame": int(dev["bits_per_frame"]),
    }


class ChipGeometry:
    """Mirror of the Chip ctor's tile-position bookkeeping (Chip.cpp:23-39)."""

    def __init__(self, device, db_root, family="MachXO2"):
        self.device = device
        self.db_root = db_root
        info = load_device_info(device, db_root, family)
        self.info = info
        self.max_row = info["max_row"]
        self.max_col = info["max_col"]
        self.row_bias = info["row_bias"]
        self.col_bias = info["col_bias"]
        self.family = info["family"]
        chip_size = (self.max_row, self.max_col)

        tg_path = os.path.join(db_root, family, device, "tilegrid.json")
        tg = json.load(open(tg_path))

        # tile full-name -> (row, col) and (row, col) -> [(name, type), ...]
        self.tile_rc = {}
        self.tile_type = {}
        self.at_location = {}
        for name, tinfo in tg.items():
            row, col = get_row_col(name, chip_size, self.row_bias, self.col_bias)
            self.tile_rc[name] = (row, col)
            self.tile_type[name] = tinfo["type"]
            self.at_location.setdefault((row, col), []).append(
                (name, tinfo["type"]))

    def get_tiles_by_position(self, row, col):
        return self.at_location.get((row, col), [])

    def get_max_row(self):
        return self.max_row

    def get_max_col(self):
        return self.max_col
