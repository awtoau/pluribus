"""globalise_net: canonicalize a tile-local wire db-name to its owning tile.

Ported faithfully from prjtrellis RoutingGraph.cpp:
  - globalise_net_machxo2            (lines 171-296)
  - find_machxo2_global_position     (lines 349-512)
  - get_global_type_from_name        (lines 514-611)
  - chip_prefix selection            (lines 23-69)
and Chip.cpp:
  - generate_global_info_machxo2     (lines 638-686)
  - start_stride / spine_map         (lines 601-636)

A wire name is either:
  * a local net with optional N/S/E/W relative-position prefixes, or
  * a global (G_/L_/R_/U_/D_/BRANCH_) whose nominal position is computed from
    the chip's spine/stride layout.

`globalise_net(row, col, name)` returns a `RId(x, y, name)` or None (the C++
returns a default RoutingId(), which callers treat as "drop this net").
"""
import re
from collections import namedtuple

from .geometry import CENTER_MAP

RId = namedtuple("RId", ["x", "y", "name"])

# --- name -> chip_prefix (RoutingGraph.cpp:23-69). Order matters: check the
#     more specific MachXO3D "...D-..." names implicitly via substring tests. ---
_PREFIX_RULES = [
    ("25F", "25K_"), ("12F", "25K_"), ("45F", "45K_"), ("85F", "85K_"),
    ("LCMXO256", "256X_"), ("LCMXO640", "640X_"),
    ("LCMXO1200", "1200X_"), ("LCMXO2280", "2280X_"),
    ("LCMXO2-256", "256_"), ("LCMXO2-640", "640_"),
    ("LCMXO2-1200", "1200_"), ("LCMXO2-2000", "2000_"),
    ("LCMXO2-4000", "4000_"), ("LCMXO2-7000", "7000_"),
    ("LCMXO3-1300", "1300_"), ("LCMXO3-2100", "2100_"),
    ("LCMXO3-4300", "4300_"), ("LCMXO3-6900", "6900_"),
    ("LCMXO3-9400", "9400_"),
    ("LCMXO3D-4300", "4300D_"), ("LCMXO3D-9400", "9400D_"),
]


def chip_prefix(chip_name):
    for needle, pref in _PREFIX_RULES:
        if needle in chip_name:
            return pref
    raise AssertionError(f"no chip_prefix for {chip_name}")


# start_stride (Chip.cpp:601-616), keyed by (max_row, max_col)
START_STRIDE = {
    (7, 9): 0, (8, 17): 1, (12, 21): 0, (15, 25): 3,
    (22, 31): 1, (27, 40): 2, (31, 48): 0,
}
# spine_map (Chip.cpp:621-636): list of (row, down); -1 == don't care
SPINE_MAP = {
    (7, 9): [(6, -1)], (8, 17): [(7, -1)], (12, 21): [(6, -1)],
    (15, 25): [(8, -1)], (22, 31): [(11, -1)],
    (27, 40): [(13, 0), (20, -1)], (31, 48): [(8, 7), (22, -1)],
}


def generate_global_info(max_row, max_col):
    """Port of Chip::generate_global_info_machxo2 (Chip.cpp:638-686).

    Returns dict with 'spines' (list of (row, down)) and 'ud_conns'
    (list indexed by column of the global numbers routed in that column).
    """
    stride = START_STRIDE[(max_row, max_col)]
    ud_conns = []

    # Column 0: six globals (all i in 0..3 except `stride`, plus i+4).
    items_col_0 = []
    for i in range(4):
        if i != stride:
            items_col_0.append(i)
            items_col_0.append(i + 4)
    ud_conns.append(items_col_0)

    # Columns 1 .. max_col-1
    for _i in range(1, max_col):
        items = [stride, stride + 4]
        stride = (stride + 1) & 3
        ud_conns.append(items)

    # Final column: expected two + next two in the stride (edge effect).
    items_col_last = [stride, stride + 4]
    stride = (stride + 1) & 3
    items_col_last += [stride, stride + 4]
    ud_conns.append(items_col_last)

    return {"spines": SPINE_MAP[(max_row, max_col)], "ud_conns": ud_conns}


# --- get_global_type_from_name regexes (RoutingGraph.cpp:525-588) -------------
_G_ENTRY = re.compile(r"G_VPRX(\d){2}00")
_G_LR = re.compile(r"[LR]_HPSX(\d){2}00")
_G_LR_G = re.compile(r"G_HPSX(\d){2}00")
_G_UD = re.compile(r"[UD]_VPTX(\d){2}00")
_G_UD_G = re.compile(r"G_VPTX(\d){2}00")
_G_BRANCH = re.compile(r"BRANCH_HPBX(\d){2}00")
_CM_GLB_OUT = re.compile(r"G_VPRXCLKI\d+")
_CIB_OUT_TO_GLB = re.compile(r"G_J?PCLKCIB(L[TBRL]Q|MID|VIQ[TBRL])(\d){1}")
_DCC_SIG = re.compile(r"G_J?(CLK[IO]|CE)(\d){1}[TB]?_DCC")
_DCM_SIG = re.compile(r"G_J?(CLK(\d){1}_|SEL|DCMOUT)(\d){1}_DCM")
_OSC_CLK = re.compile(r"G_J?OSC_.*")

# GlobalType
CENTER, SPINE_LEFT_RIGHT, LEFT_RIGHT, UP_DOWN, BRANCH, OTHER, NONE = range(7)


def get_global_type_from_name(db_name):
    """Return (GlobalType, match) mirroring RoutingGraph.cpp:514-611.

    `regex_match` is full-string anchored -> use re.fullmatch.
    """
    def fm(rx):
        return rx.fullmatch(db_name)

    m = fm(_G_ENTRY) or fm(_CM_GLB_OUT) or fm(_CIB_OUT_TO_GLB) or fm(_DCM_SIG)
    if m:
        return CENTER, m
    m = fm(_G_LR)
    if m:
        return SPINE_LEFT_RIGHT, m
    m = fm(_G_LR_G)
    if m:
        return LEFT_RIGHT, m
    m = fm(_G_UD) or fm(_G_UD_G)
    if m:
        return UP_DOWN, m
    m = fm(_G_BRANCH)
    if m:
        return BRANCH, m
    m = fm(_DCC_SIG) or fm(_OSC_CLK)
    if m:
        return OTHER, m
    return NONE, None


class Globaliser:
    """Holds per-chip state for globalise_net (mirrors RoutingGraph members)."""

    _LOCAL_RE = re.compile(r"^([NS]\d+)?([EW]\d+)?_(.*)")
    # PIO-wire substrings that trigger the left/right edge special-cases
    # (RoutingGraph.cpp:230-247 / 257-274).
    _PIO_SUBSTR = ("DI", "JDI", "PADD", "INDD", "IOLDO", "IOLTO", "JCE",
                   "JCLK", "JLSR", "JONEG", "JOPOS", "JTS", "JIN", "JIP",
                   "JINCK")

    def __init__(self, chip_name, max_row, max_col):
        self.chip_name = chip_name
        self.max_row = max_row
        self.max_col = max_col
        self.prefix = chip_prefix(chip_name)
        self.center = CENTER_MAP[(max_row, max_col)]  # (row, col)
        self.gi = generate_global_info(max_row, max_col)

    # --- global position (RoutingGraph.cpp:349-512) -------------------------
    def _find_global_position(self, row, col, db_name):
        center = self.center  # (center_row, center_col)
        spines = self.gi["spines"]
        spine_1 = spines[0]
        spine_2 = spines[1] if len(spines) > 1 else (-1, -1)
        strategy, m = get_global_type_from_name(db_name)

        if strategy == CENTER:
            return RId(center[1], center[0], db_name)

        if strategy == SPINE_LEFT_RIGHT:
            assert row == spine_1[0] or row == spine_2[0]
            return RId(center[1], row, db_name)

        if strategy == LEFT_RIGHT:
            assert row == spine_1[0] or row == spine_2[0]
            assert db_name[0] == "G"
            db_copy = ("L" if col <= center[1] else "R") + db_name[1:]
            return RId(center[1], row, db_copy)

        if strategy == UP_DOWN:
            ud_col = self.gi["ud_conns"][col]
            conn_no = int(m.group(1))
            if conn_no not in ud_col:
                return None
            if row == spine_1[0] or row == spine_2[0]:
                assert db_name[0] in ("U", "D")
                return RId(col, row, db_name)
            assert db_name[0] == "G"
            spine_row = spine_1[0]
            if row <= spine_1[0]:
                c0 = "U"
            else:
                if spine_2[0] == -1 or row <= (spine_1[0] + spine_1[1]):
                    c0 = "D"
                else:
                    c0 = "U" if row <= spine_2[0] else "D"
                    spine_row = spine_2[0]
            return RId(col, spine_row, c0 + db_name[1:])

        if strategy == BRANCH:
            candidate_cols = []
            if col > 1:
                candidate_cols.append(col - 2)
            if col > 0:
                candidate_cols.append(col - 1)
            candidate_cols.append(col)
            if col < self.max_col:
                candidate_cols.append(col + 1)
            conn_no = int(m.group(1))
            for curr_col in candidate_cols:
                if conn_no in self.gi["ud_conns"][curr_col]:
                    return RId(curr_col, row, db_name)
            # C++ asserts a column was found.
            raise AssertionError(f"BRANCH {db_name} @({row},{col}) unmatched")

        if strategy == OTHER:
            return RId(col, row, db_name)

        return None  # NONE

    # --- globalise_net (RoutingGraph.cpp:171-296) ---------------------------
    def globalise_net(self, row, col, db_name):
        stripped = db_name

        # Chip-prefix stripping (256_/640_ =4, 1200_.. =5, 4300D_/9400D_ =6).
        if db_name.startswith(("256_", "640_")):
            if db_name[:4] == self.prefix:
                stripped = db_name[4:]
            else:
                return None
        if db_name.startswith(("1200_", "1300_", "2000_", "2100_", "4000_",
                               "4300_", "6900_", "7000_", "9400_")):
            if db_name[:5] == self.prefix:
                stripped = db_name[5:]
            else:
                return None
        if db_name.startswith(("4300D_", "9400D_")):
            if db_name[:6] == self.prefix:
                stripped = db_name[6:]
            else:
                return None

        # Global prefixes -> nominal position via spine/stride layout.
        if stripped.startswith(("G_", "L_", "R_", "U_", "D_", "BRANCH_")):
            return self._find_global_position(row, col, stripped)

        # Local net: apply N/S/E/W relative offsets.
        x, y = col, row
        m = self._LOCAL_RE.match(stripped)
        if m:
            for i in (1, 2):  # groups before the final (.*)
                g = m.group(i)
                if not g:
                    continue
                d = int(g[1:])
                if g[0] == "N":
                    y -= d
                elif g[0] == "S":
                    y += d
                elif g[0] == "W":
                    x -= d
                    if x < 0 and self._is_pio_wire(db_name) and x == -1:
                        x = 0
                elif g[0] == "E":
                    x += d
                    if (x > self.max_col and self._is_pio_wire(db_name)
                            and x == self.max_col + 1):
                        x = self.max_col
                else:
                    raise AssertionError(g)
            name = m.group(m.lastindex) if m.lastindex else stripped
            # m.group(3) is the final (.*) capture
            name = m.group(3)
        else:
            name = stripped

        if x < 0 or x > self.max_col or y < 0 or y > self.max_row:
            return None
        return RId(x, y, name)

    def _is_pio_wire(self, db_name):
        return any(s in db_name for s in self._PIO_SUBSTR)
