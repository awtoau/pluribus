#!/usr/bin/env python3
"""GOWIN family lifter — pure-Python, reads a `.gwconfig` text config.

The heavy GOWIN decode (Project Apicula / apycula) runs as a SEPARATE
subprocess under the oss-cad-suite interpreter — see scripts/gowin_unpack.py —
which emits a normalized `.gwconfig`.  THIS module imports nothing heavy
(collections + re only) so it loads cleanly in the free-threaded python3.15t
pluribus interpreter alongside the rest of the stack.

It exposes the same surface as lifters/machxo2_lift.MachXO2Lift so load.py's
family-agnostic core (nets / FFs / LUTs / net_fanout / arcs) runs unchanged:
    parse_config(path)      -> GowinParsedConfig
    recover_netlist(pc)     -> Design   (all_nets, ffs, luts, dsu, net_name)
    arc_endpoint_sets(pc)   -> (sources, sinks)
    gkey(row, col, wire)    -> canonical node name (identity: names are already
                               global + node-stitched by scripts/gowin_unpack.py)
The pad / EFB / EBR hooks return empty for now — GW1N-1 pad recovery, the clock
spine, and BSRAM/PLL are not modelled yet (load.py gates those MachXO2-only
blocks by family).

LUT INIT CONVENTION (verified — do not "fix" without re-checking):
  gowin_unpack.py emits init16 as f"{val:016b}" where
  val = 0xFFFF - sum(1<<f for the SET fuse positions), pins I0=A I1=B I2=C I3=D,
  truth-table address = A + 2B + 4C + 8D, INIT[address] = f.  That is EXACTLY
  the pluribus MSB-first convention consumed by load.classify_lut /
  machxo2_lift.lut_dependence (v = int(init16, 2); bit p = f(p)).  No reversal,
  no pin permutation.  Verified against apycula's golden blinky-ref.v
  (R10C4 0x5555 = INV(a); R10C8 0xEEEE = OR(a,b)) and against a synthesised
  known function (tests/test_gowin_lift.py).
"""

import re
from collections import defaultdict


class DSU:
    """Union-find over node-name strings (same shape as machxo2_lift.DSU)."""

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
    """Recovered structural netlist (nets + LUT4s + flip-flops)."""

    def __init__(self):
        self.luts = []
        self.ffs = []
        self.net_name = {}       # dsu-root -> "n<k>"
        self.all_nets = []
        self.dsu = None
        self.used_roots = set()
        self.n_arcs = 0
        self.skipped_arcs = 0
        # gowin diagnostics (surfaced in the load summary / report)
        self.n_alu = 0
        self.n_alu_ff = 0        # DFFs whose D comes from an (unmodelled) ALU
        self.hardip_counts = {}


class GowinParsedConfig:
    """Parsed `.gwconfig`.  The machxo2-compat empty dicts exist only so a
    stray reach into load.py's family-gated blocks never AttributeErrors."""

    def __init__(self):
        self.device = None
        self.arcs = []                       # (row, col, sink, source)
        self.tile_type = {}                  # (row,col) -> ttyp string
        self.luts = []                       # dicts
        self.dffs = []                       # dicts
        self.iobs = []                       # dicts
        self.hardips = []                    # dicts (ALU / MUX / BSRAM / PLL / ...)
        # machxo2-compat empties (never populated for gowin)
        self.enums = defaultdict(dict)
        self.words = defaultdict(dict)
        self.slice_enum = defaultdict(dict)
        self.lut_init = {}
        self.bram_init = {}
        self.efb_blocks = {}


def _kv(tokens):
    """['A=node', 'B=-'] -> {'A': 'node', 'B': None}  ('-' means absent)."""
    out = {}
    for tok in tokens:
        if "=" not in tok:
            continue
        k, _, v = tok.partition("=")
        out[k] = None if v == "-" else v
    return out


# VCC/VSS constant nodes -> Verilog literals (mirrors machxo2 const handling).
_CONST_NODE = {"VCC": "1'b1", "VSS": "1'b0"}


class GowinLift:
    """Text-config-backed lifter for one GOWIN device (e.g. GW1N-1)."""

    # capability flags (informational; load.py gates by the `lifter` string)
    has_efb = False
    has_ebr = False
    has_iologic = False

    class _IdRG:
        """Minimal routing-graph shim: node names ARE their own ids."""
        @staticmethod
        def to_str(x):
            return str(x)

    def __init__(self, device, **_kwargs):
        self.device = device
        self.family = "gowin"
        self.rg = self._IdRG()

    # ---- parsing -----------------------------------------------------------
    def parse_config(self, path):
        pc = GowinParsedConfig()
        with open(path) as fh:
            for raw in fh:
                s = raw.strip()
                if not s or s.startswith("#"):
                    continue
                p = s.split()
                tag = p[0]
                if tag == ".device":
                    pc.device = p[1]
                elif tag == ".tile":
                    pc.tile_type[(int(p[1]), int(p[2]))] = p[3]
                elif tag == "arc":
                    dst = None if p[3] == "-" else p[3]
                    src = None if p[4] == "-" else p[4]
                    pc.arcs.append((int(p[1]), int(p[2]), dst, src))
                elif tag == "lut":
                    kv = _kv(p[5:])
                    pc.luts.append({
                        "row": int(p[1]), "col": int(p[2]), "bel": p[3],
                        "init": p[4],
                        "a": kv.get("A"), "b": kv.get("B"),
                        "c": kv.get("C"), "d": kv.get("D"), "f": kv.get("F"),
                    })
                elif tag == "dff":
                    kv = _kv(p[5:])
                    pc.dffs.append({
                        "row": int(p[1]), "col": int(p[2]), "bel": p[3],
                        "dtype": p[4],
                        "q": kv.get("Q"), "d": kv.get("D"), "clk": kv.get("CLK"),
                        "ce": kv.get("CE"), "sr": kv.get("SR"),
                    })
                elif tag == "iob":
                    kv = _kv(p[5:])
                    pc.iobs.append({
                        "row": int(p[1]), "col": int(p[2]), "bel": p[3],
                        "mode": p[4],
                        "i": kv.get("I"), "o": kv.get("O"), "oe": kv.get("OE"),
                        "pin": kv.get("pin"),
                    })
                elif tag == "hardip":
                    kv = _kv(p[4:])
                    rec = {"row": int(p[1]), "col": int(p[2]), "type": p[3]}
                    rec.update(kv)
                    pc.hardips.append(rec)
        return pc

    # ---- node-key helper ---------------------------------------------------
    def gkey(self, row, col, name):
        """Canonical node key.  gowin node names are already global and
        node-stitched by scripts/gowin_unpack.py, so this is identity."""
        if name is None or name == "-":
            return None
        return name

    def arc_endpoint_sets(self, pc):
        """Nodes appearing as a config-arc source / sink."""
        sinks, sources = set(), set()
        for (_r, _c, sink, source) in pc.arcs:
            if sink is not None:
                sinks.add(sink)
            if source is not None:
                sources.add(source)
        return sources, sinks

    # ---- recovery ----------------------------------------------------------
    def recover_netlist(self, pc):
        d = Design()
        dsu = d.dsu = DSU()
        src_keys = set()

        # 1) union every routing arc (nodes are pre-stitched globals)
        for (_r, _c, sink, source) in pc.arcs:
            if sink is None and source is None:
                continue
            if sink is None:
                dsu.union(source, source)
                continue
            if source is None:
                dsu.union(sink, sink)
                continue
            dsu.union(sink, source)
            src_keys.add(source)
        d.n_arcs = len(pc.arcs)
        d.used_roots = {dsu.find(k) for k in src_keys}

        net_name = d.net_name
        counter = [0]

        def net_of(key):
            root = dsu.find(key)
            if root not in net_name:
                counter[0] += 1
                net_name[root] = f"n{counter[0]}"
            return net_name[root]

        def connected(key):
            return key in dsu.p

        # 2) constant roots (VCC/VSS) -> literals, resolved before any naming
        const_by_root = {}
        for node, lit in _CONST_NODE.items():
            if node in dsu.p:
                const_by_root[dsu.find(node)] = lit

        # 2b) degenerate (all-0 / all-1) LUTs: map their F node to the literal
        for lt in pc.luts:
            if set(lt["init"]) not in ({"0"}, {"1"}):
                continue
            f = lt["f"]
            if not f:
                continue
            dsu.union(f, f)
            const_by_root[dsu.find(f)] = "1'b1" if set(lt["init"]) == {"1"} else "1'b0"

        def resolve(key, default):
            if key is None or not connected(key):
                return default
            root = dsu.find(key)
            if root in const_by_root:
                return const_by_root[root]
            return net_of(key)

        # 3) ALU outputs: force-name the F node so a paired DFF's D resolves to
        #    the ALU-result net.  The ALU's own logic (carry chain) is NOT
        #    modelled yet — these nets are correct endpoints but currently
        #    have no fanin.  Counted and reported, excluded from LUT parity.
        n_alu = 0
        alu_out_nodes = set()
        hardip_counts = defaultdict(int)
        for hp in pc.hardips:
            hardip_counts[hp["type"]] += 1
            if hp["type"] == "ALU":
                n_alu += 1
                f = hp.get("F")
                if f:
                    alu_out_nodes.add(f)
                    net_of(f)
        d.n_alu = n_alu
        d.hardip_counts = dict(hardip_counts)

        # 4) LUT4s (skip constants — handled above)
        for lt in pc.luts:
            if set(lt["init"]) in ({"0"}, {"1"}):
                continue
            f = lt["f"]
            z = net_of(f) if f else None
            z_used = bool(f and connected(f) and dsu.find(f) in d.used_roots)
            d.luts.append({
                "name": f"lut_r{lt['row']}c{lt['col']}_{lt['bel']}",
                "init": lt["init"],
                "a": resolve(lt["a"], None), "b": resolve(lt["b"], None),
                "c": resolve(lt["c"], None), "d": resolve(lt["d"], None),
                "z": z,
                "z_used": z_used,
            })

        # 5) flip-flops
        n_alu_ff = 0
        for df in pc.dffs:
            q = df["q"]
            if not q:
                continue  # every FF must have a Q net (load.py asserts this)
            # a DFF fed directly by an ALU result: D is the ALU's F output node.
            # Its net is real (force-named above) but has no fanin until the ALU
            # is modelled — track how many so the parity claim stays honest.
            if df["d"] in alu_out_nodes:
                n_alu_ff += 1
            d.ffs.append({
                "name": f"ff_r{df['row']}c{df['col']}_{df['bel']}",
                "q": net_of(q),
                "d": resolve(df["d"], "1'b0"),
                "clk": resolve(df["clk"], "1'b0"),
                "ce": resolve(df["ce"], "1'b1"),
                "lsr": resolve(df["sr"], "1'b0"),
                "dtype": df["dtype"],
            })
        d.n_alu_ff = n_alu_ff

        # 6) force a net name for every routed node (except constant roots), so
        #    the arcs table and api queries see fully-resolved nets — mirrors
        #    machxo2_lift.recover_netlist's final naming pass.
        for (_r, _c, sink, source) in pc.arcs:
            for node in (sink, source):
                if node is None or node not in dsu.p:
                    continue
                if dsu.find(node) in const_by_root:
                    continue
                net_of(node)

        d.all_nets = sorted(set(net_name.values()), key=lambda s: int(s[1:]))
        return d

    # ---- pad / EFB / EBR hooks (empty for gowin, load.py gates these) ------
    def pad_fabric_node(self, row, col, pio, direction):
        return None

    def bels_of(self, row, col):
        return {}

    def load_efb_fixed_conns(self, dbroot=None):
        return []

    def apply_efb_fixed_conns(self, dsu, efb_conns, cfg_row=1, cfg_col=4):
        return set()
