"""Lattice ECP5 lifter — stub (issue #9 / #15).

The public interface matches MachXO2Lift so load.py can call it without
caring which family it has.  Only __init__ is functional; all recovery
methods raise NotImplementedError until ECP5 tile/bel conventions are
mapped.

Key differences from MachXO2 that need to be handled before recovery works:
  - Slice naming: TRELLIS_SLICE (SLICEL/SLICEM) vs MachXO2 SLICE[A-D]
  - LUT init format: K=0 only (LUT4 within 8-input LUT8), different SENUM keys
  - No EFB fixed_conns: ECP5 has SERIO hard blocks, not the WISHBONE/I2C EFB
  - Pad joint node names differ: PIOA_IO → different naming convention
  - IO cells: TRELLIS_IO, not PIO, for I/O primitives
  - Routing graph globalise_net() edge cases may differ

See docs/unknown-bits-analysis.md (Lattice ECP5 section, TBD) and issue #9.
"""

import re
import sys
from collections import defaultdict


DEF_BUILD_DIR = __import__('os').environ.get("TRELLIS_BUILD",
                            "tmp/prjtrellis/libtrellis/build")
DEF_DBROOT    = __import__('os').environ.get("TRELLIS_DBROOT",
                            "tmp/prjtrellis/database")

# .config tile/arc regexes — identical format to MachXO2.
TILE_RE = re.compile(r"^\.tile\s+(\S+):(\S+)")
ARC_RE  = re.compile(r"^arc:\s+(\S+)\s+(\S+)")
ENUM_RE = re.compile(r"^enum:\s+(\S+)\s+(\S+)")
WORD_RE = re.compile(r"^word:\s+(\S+)\s+(\S+)")


class ECP5Lift:
    """Routing-graph-backed lifter for one ECP5 device.

    Currently only __init__ is operational (chip/routing-graph construction
    so the device string can be validated early).  All recovery methods
    raise NotImplementedError until ECP5 slice/bel naming is mapped.
    """

    def __init__(self, device, build_dir=DEF_BUILD_DIR, dbroot=DEF_DBROOT):
        if build_dir not in sys.path:
            sys.path.insert(0, build_dir)
        import pytrellis
        self._pt = pytrellis
        pytrellis.load_database(dbroot)
        self.device = device
        self.chip = pytrellis.Chip(device)
        self.rg = self.chip.get_routing_graph(True, True)

        self.tile_rc = {}
        for r in range(self.chip.get_max_row() + 1):
            for c in range(self.chip.get_max_col() + 1):
                try:
                    for t in self.chip.get_tiles_by_position(r, c):
                        self.tile_rc[t.info.name] = (r, c)
                except Exception:
                    pass

    def parse_config(self, path):
        """Parse a Trellis .config into a raw tile-resolved form.

        The .config line format is the same across all Trellis families, but
        ECP5 tile/slice names differ from MachXO2.  This method reads arcs and
        enums; LUT INIT extraction needs a separate ECP5-specific regex pass
        once slice naming is confirmed (TRELLIS_SLICE vs SLICE[A-D]).
        """
        from lifters.machxo2_lift import ParsedConfig
        pc = ParsedConfig()
        cur_rc = None
        with open(path) as fh:
            for line in fh:
                s = line.strip()
                m = TILE_RE.match(s)
                if m:
                    cur_rc = self.tile_rc.get(f"{m.group(1)}:{m.group(2)}")
                    if cur_rc:
                        pc.tile_type[cur_rc] = m.group(2)
                    continue
                if cur_rc is None:
                    continue
                r, c = cur_rc
                me = ENUM_RE.match(s)
                if me:
                    pc.enums[(r, c)][me.group(1)] = me.group(2)
                else:
                    mw = WORD_RE.match(s)
                    if mw:
                        pc.words[(r, c)][mw.group(1)] = mw.group(2)
                m = ARC_RE.match(s)
                if m:
                    pc.arcs.append((r, c, m.group(1), m.group(2)))
        return pc

    def recover_netlist(self, pc):
        raise NotImplementedError(
            "ECP5 recover_netlist not implemented (issue #9). "
            "Map TRELLIS_SLICE bel names and LUT INIT key format first."
        )

    def arc_endpoint_sets(self, pc):
        raise NotImplementedError(
            "ECP5 arc_endpoint_sets not implemented (issue #9)."
        )

    def load_efb_fixed_conns(self, dbroot=None):
        raise NotImplementedError(
            "ECP5 has no EFB (issue #9). "
            "ECP5 uses SERIO/USRMCLK hard blocks instead; map those separately."
        )

    def apply_efb_fixed_conns(self, dsu, efb_conns, cfg_row=None, cfg_col=None):
        raise NotImplementedError(
            "ECP5 apply_efb_fixed_conns not applicable (issue #9)."
        )

    def pad_fabric_node(self, row, col, pio, direction):
        raise NotImplementedError(
            "ECP5 pad_fabric_node not implemented (issue #9). "
            "ECP5 IO joint node naming differs from MachXO2 JQ/JA convention."
        )

    def bels_of(self, row, col):
        raise NotImplementedError(
            "ECP5 bels_of not implemented (issue #9)."
        )
