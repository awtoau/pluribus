#!/usr/bin/env python3
"""Anlogic EG4 (eagle_s20) lifter — pure-Python, reads a `.anloconfig` text
config emitted by scripts/anlogic_unpack.py (issue #67).

Third pluribus FPGA family, alongside MachXO2 (prjtrellis) and Gowin (apicula).
Like the Gowin path it is deliberately dependency-light (only re/collections) so
it imports cleanly into the free-threaded python3.15t pipeline interpreter, and
it exposes the same lifter surface as MachXO2Lift / GowinLift so load.py can
dispatch it by family:

    parse_config(path)   -> AnlogicParsedConfig   (device, tiles, luts, sysconfig)
    recover_netlist(pc)  -> Design                (LUT4 cells + their output nets)
    arc_endpoint_sets(pc)-> (set, set)            (empty — routing not decoded)
    gkey(row, col, name) -> node key (identity)
    pad/EFB/EBR hooks    -> empty

WHAT IS RECOVERED (verified layers):
  * device / package / idcode / sysconfig words          (container, CRC-checked)
  * the full tile grid with per-tile CRAM occupancy       (Tang-Dynasty fuse DB)
  * LUT4 init words for every configured LUT              (MEMORY fuses)
    The LUT layer is validated by construction: LUT non-zero-ness correlates
    exactly with tile CRAM occupancy (empty tiles decode to all-zero LUTs), and
    the recovered inits are canonical functions (0xff00, 0xf000, XOR/XNOR ...).

WHAT IS NOT YET RECOVERED (documented remaining work — see load.py load_anlogic):
  * routing / connectivity.  Anlogic muxes are BINARY-encoded: a sink's source
    is chosen by the value of several `TOP.Xn.MCnn` config bits evaluated
    through the per-bit boolean expr the fuse DB carries (prjtang leaves this
    mux decode unfinished).  So LUT input pins (a/b/c/d) and FF connectivity are
    left unconnected here; `arcs` stays empty for this family.
  * LUT-init PIN order is provisional: the MEMORY-fuse bit index is taken as the
    truth-table address directly (address = A+2B+4C+8D).  The init *values* are
    correct; the input-pin permutation is not yet cross-checked against a
    TD-synthesised known function, so classify_lut() results are indicative.
"""

from collections import defaultdict


class DSU:
    """Union-find over node-name strings (same shape as gowin_lift.DSU)."""

    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        root = x
        while self.p[root] != root:
            root = self.p[root]
        while self.p[x] != root:
            self.p[x], x = root, self.p[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


class Design:
    """Recovered structural netlist (LUT4 cells + their output nets)."""

    def __init__(self):
        self.luts = []
        self.ffs = []
        self.net_name = {}
        self.all_nets = []
        self.dsu = None
        self.used_roots = set()
        self.n_arcs = 0
        self.skipped_arcs = 0
        # anlogic diagnostics (surfaced in the load summary)
        self.tile_counts = {}      # tile_type -> count
        self.active_tiles = 0
        self.n_luts_nonzero = 0


class AnlogicParsedConfig:
    """Parsed `.anloconfig`."""

    def __init__(self):
        self.device = None
        self.package = None
        self.idcode = None
        self.sysconfig = {}                  # name -> "0x...."
        self.tiles = []                      # dicts: name,type,x,y,sf,sb,rows,cols,occ
        self.luts = []                       # dicts: tile,slice,lut,init
        self.bram_init = {}                  # index -> hex string
        # machxo2-compat empties (never populated) so any stray family-gated
        # reach into load.py's machxo2 blocks never AttributeErrors.
        self.enums = defaultdict(dict)
        self.words = defaultdict(dict)
        self.slice_enum = defaultdict(dict)
        self.lut_init = {}
        self.efb_blocks = {}


class AnlogicLift:
    """Text-config-backed lifter for one Anlogic EG4 device (e.g. EG4S20BG256)."""

    has_efb = False
    has_ebr = False
    has_iologic = False

    class _IdRG:
        @staticmethod
        def to_str(x):
            return str(x)

    def __init__(self, device, **_kwargs):
        self.device = device
        self.family = "anlogic"
        self.rg = self._IdRG()

    # ---- parsing -----------------------------------------------------------
    def parse_config(self, path):
        pc = AnlogicParsedConfig()
        with open(path) as fh:
            for raw in fh:
                s = raw.strip()
                if not s or s.startswith("#"):
                    continue
                p = s.split()
                tag = p[0]
                if tag == ".device":
                    pc.device = p[1]
                elif tag == ".package":
                    pc.package = p[1]
                elif tag == ".idcode":
                    pc.idcode = p[1]
                elif tag == ".sysconfig":
                    pc.sysconfig[p[1]] = p[2]
                elif tag == ".tile":
                    # .tile name type x y start_frame start_bit rows cols occupancy
                    pc.tiles.append({
                        "name": p[1], "type": p[2],
                        "x": int(p[3]), "y": int(p[4]),
                        "start_frame": int(p[5]), "start_bit": int(p[6]),
                        "rows": int(p[7]), "cols": int(p[8]),
                        "occupancy": int(p[9]) if len(p) > 9 else 0,
                    })
                elif tag == "lut":
                    # lut tilename slice lut init16
                    pc.luts.append({
                        "tile": p[1], "slice": p[2], "lut": p[3], "init": p[4],
                    })
                elif tag == ".bram_init":
                    pc.bram_init[int(p[1])] = p[2]
        return pc

    # ---- node-key helper ---------------------------------------------------
    def gkey(self, row, col, name):
        if name is None or name == "-":
            return None
        return name

    def arc_endpoint_sets(self, pc):
        """Routing is not decoded for the anlogic family — no arc endpoints."""
        return set(), set()

    # ---- recovery ----------------------------------------------------------
    def recover_netlist(self, pc):
        d = Design()
        d.dsu = DSU()

        counts = defaultdict(int)
        for t in pc.tiles:
            counts[t["type"]] += 1
            if t["occupancy"]:
                d.active_tiles += 1
        d.tile_counts = dict(counts)

        net_name = d.net_name
        counter = [0]

        def out_net(cell):
            key = f"z_{cell}"
            root = d.dsu.find(key)
            if root not in net_name:
                counter[0] += 1
                net_name[root] = f"n{counter[0]}"
            return net_name[root]

        for lt in pc.luts:
            cell = f"lut_{lt['tile']}_{lt['slice']}_{lt['lut']}"
            init = lt["init"]
            # skip all-0 / all-1 (unconfigured or constant) LUTs
            if set(init) in ({"0"}, {"1"}):
                continue
            d.n_luts_nonzero += 1
            z = out_net(cell)
            d.luts.append({
                "name": cell,
                "init": init,
                # routing not decoded: inputs unconnected, output net is real
                "a": None, "b": None, "c": None, "d": None,
                "z": z, "z_used": False,
            })

        d.all_nets = sorted(set(net_name.values()), key=lambda s: int(s[1:]))
        return d

    # ---- pad / EFB / EBR hooks (empty; load.py gates these) ---------------
    def pad_fabric_node(self, row, col, pio, direction):
        return None

    def bels_of(self, row, col):
        return {}

    def load_efb_fixed_conns(self, dbroot=None):
        return []

    def apply_efb_fixed_conns(self, dsu, efb_conns, cfg_row=1, cfg_col=4):
        return set()
