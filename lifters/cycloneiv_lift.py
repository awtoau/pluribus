#!/usr/bin/env python3
"""Cyclone III / IV E / IV GX lifter: bitstream (.rbf, compressed or not) -> structural netlist.

Sibling of cyclonev_lift / ecp5_lift (no shared flags).  Everything comes from the bitstream and
device tables; the Quartus post-fit netlist is only an oracle in the gate, never an input.

Device-driven: `lifters/data/cycloneiv_<die>_geom.json` (tile anchors, lane sizes) and the routing
mux tables learnt by scripts/cycloneiv_route_learn.py (or the vendor tables, same Decoder API).

Cells (per used LE, bit (3,-2) of the LE window):
  LUT   init (16-bit truth table, index = a + 2 b + 4 c + 8 d), inputs a..d, cin mode (DATAC mux
        reads the carry code), cout = init[{0, cin, b, a}]
  FF    exists when an LE_BUFFER of the LE selects the register output; pins D / ASDATA / CLK /
        CLRN / ENA / SCLR / SLOAD traced through the routing tables; clock inversion = LAB bit
Nets: a driver cell's output; terminals are named, never guessed:
  ('PAD', x, y, s, i)    IO_DATAIN element (an input pad; identity learnt from the corpus)
  ('CLKW', type, ...)    LAB_CLK / global clock element (clock tree not decoded)
  ('UNRESOLVED', why)    no unique driver; the cell input is listed in Design.unresolved
NOT LIFTED, reported not hidden: M9K, multipliers, PLL, transceivers, IO routing, clock tree, a
carry chain entering a LAB at LE 0, ENA/SCLR/SLOAD semantics beyond the traced pins.
"""
import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_route_decode as rd  # noqa: E402
import cycloneiv_route_learn as rl  # noqa: E402

LE_USED = (-8, -1)         # LE window bit: set for 95.8% of LUT cells and absent from empty LEs
CLK_POL = (-6, -30)        # LAB-relative bit (frame, v offset from the tile anchor): clock inverted
D_DIRECT = (4, -1)         # LE window bit (even LEs): FF D not from the LUT (sload / direct)
PORTS = ("DATAA", "DATAB", "DATAC", "DATAD")
TERMINAL_WIRES = {"IO_DATAIN", "BLK_CLK_BUF", "LAB_CLK", "GLOBAL_CLK_H", "GLOBAL_CLK_V", "SCLK_TO_ROWCLK_BUF",
                  "CLK_BUFFER", "CLKBUF_IN", "GEN_CORE_BUF", "CLKBUF_OUT"}


class Design:
    def __init__(self):
        self.luts = []          # {name, x, y, le, init, mode, a, b, c, d, cin, z, cout}
        self.ffs = []           # {name, x, y, le, d, asdata, clk, clk_inv, ena, clrn, sclr, sload, q}
        self.terminals = {}     # net -> descriptor tuple (boundary inputs)
        self.unresolved = []    # (cell, pin, reason)
        self.not_lifted = collections.Counter()
        self.used_les = 0


def comb(x, y, le):
    return f"c_{x}_{y}_{le}"


def cout(x, y, le):
    return f"co_{x}_{y}_{le}"


def qnet(x, y, le):
    return f"q_{x}_{y}_{le}"


def support_deps(m):
    dep = []
    for i in range(4):
        d = False
        for j in range(16):
            if not j >> i & 1 and ((m >> j) & 1) != ((m >> (j | (1 << i))) & 1):
                d = True
                break
        dep.append(d)
    return dep


class CycloneIVLift:
    def __init__(self, die, tables):
        self.geom = cg.load(die)
        self.dec = rd.Decoder(tables)

    # -- per-tile primitives ------------------------------------------------------------
    def le_bit(self, plane, x, y, le, df, dv):
        return rl.le_bit(plane, self.geom, x, y, le, df, dv)

    def mask(self, plane, x, y, le):
        from cycloneiv_le_locate import DK
        m = 0
        for k, (df, dv) in enumerate(DK):
            if self.le_bit(plane, x, y, le, df, dv):
                m |= 1 << k
        return m

    def scan(self, plane, tiles):
        """(used bool [tile, le], masks uint16 [tile, le]): an LE is used when its LE-used bit is set
        or its mask is nonzero (vectorised over all LEs)."""
        import numpy as np
        from cycloneiv_le_locate import DK
        geom = self.geom
        base_f, base_v, sign = [], [], []
        for (x, y) in tiles:
            f0, v0 = geom.anchor(x, y)
            for le in range(16):
                base_f.append(f0)
                base_v.append(v0 + geom.DN[le])
                sign.append(-1 if le % 2 else 1)
        bf, bv, sg = np.array(base_f), np.array(base_v), np.array(sign)
        masks = np.zeros(len(bf), dtype=np.uint32)
        for k, (df, dv) in enumerate(DK):
            masks |= plane.has(bf + df, bv + sg * dv).astype(np.uint32) << k
        bit = plane.has(bf + LE_USED[0], bv + sg * LE_USED[1])
        used = bit | (masks != 0)
        n = len(tiles)
        return used.reshape(n, 16), masks.reshape(n, 16).astype(np.uint16)

    def lab_bit(self, plane, x, y, df, dv):
        f0, v0 = self.geom.anchor(x, y)
        return plane[f0 + df, v0 + dv]

    # -- netlist ------------------------------------------------------------------------
    def net_of(self, d, des, cell, pin, owner):
        """Driver tuple from Tracer -> net name (terminals recorded in des.terminals)."""
        if d is None:
            return None
        kind = d[0]
        if kind == "DRV":
            _k, cellkind, n, x, y = d
            le = n // 2
            if cellkind == "LCCOMB":
                return comb(x, y, le)
            if cellkind == "FF":
                return qnet(x, y, le)
            name = f"p_{cellkind}_{x}_{y}_{n}"
            des.terminals[name] = ("DRV", cellkind, x, y, n)
            return name
        if kind == "CONST":
            return "1'b1" if d[1] else "1'b0"
        if kind == "CIN":
            return owner["cin"]
        if kind == "WIRE":
            _k, typ, s, i, x, y = d
            name = f"w_{typ}_{x}_{y}_{s}_{i}"
            des.terminals[name] = ("WIRE", typ, x, y, s, i)
            return name
        return None

    def lift(self, plane, tiles=None):
        geom = self.geom
        des = Design()
        tr = rd.Tracer(self.dec, plane, geom, terminals=TERMINAL_WIRES)
        tiles = tiles if tiles is not None else [(x, y) for x in sorted(geom.kind) if geom.kind[x] == "LAB"
                                                  for y in range(1, geom.ymax)]
        used, masks = self.scan(plane, tiles)
        for ti, (x, y) in enumerate(tiles):
            if not used[ti].any():
                continue
            prev_used = False
            for le in range(16):
                if not used[ti][le]:
                    prev_used = False
                    continue
                des.used_les += 1
                m = int(masks[ti][le])
                name = f"lut_{x}_{y}_{le}"
                owner = {"cin": "1'b0"}
                lut = {"name": name, "x": x, "y": y, "le": le, "init": m, "mode": "datac",
                       "z": comb(x, y, le), "cout": cout(x, y, le), "cin": "1'b0"}
                deps = support_deps(m)
                for p, dep in zip(PORTS, deps):
                    pin = p[-1].lower()
                    lut[pin] = "1'b0"
                    if not dep and p != "DATAC":
                        continue
                    got, why = tr.trace(("LCCOMB", 2 * le, p), x, y)
                    if got is None:
                        if dep:
                            des.unresolved.append((name, p, why))
                            lut[pin] = f"u_{x}_{y}_{le}_{pin}"
                            des.terminals[lut[pin]] = ("UNRESOLVED", why)
                        continue
                    if got[0] == "CIN":
                        lut["mode"] = "cin"
                        lut["cin"] = cout(x, y, le - 1) if le > 0 and prev_used else "1'b0"
                        if le == 0 or not prev_used:
                            des.not_lifted["carry chain entering at LE 0 / after an unused LE"] += 1
                        owner["cin"] = lut["cin"]
                        lut["c"] = lut["cin"]
                        continue
                    net = self.net_of(got, des, name, p, owner)
                    lut[pin] = net if net else "1'b0"
                des.luts.append(lut)
                prev_used = True
                # FF: exists when an LE_BUFFER of this LE selects the register output
                if self.ff_exists(tr, plane, x, y, le):
                    des.ffs.append(self.lift_ff(tr, plane, des, x, y, le))
        self.close_references(tr, plane, des)
        self.break_loops(des)
        return des

    def close_references(self, tr, plane, des):
        """Every c_/co_/q_ net a pin reads must have a cell: lift the FF a trace reached even when
        no LE_BUFFER of its LE selected it; a reference to an LE with no lifted LUT becomes an
        unresolved terminal (decode inconsistency, counted, never silently tied)."""
        import re
        pat = re.compile(r"^(c|co|q)_(\d+)_(\d+)_(\d+)$")
        defined = {l["z"] for l in des.luts} | {l["cout"] for l in des.luts} | {f["q"] for f in des.ffs}
        pins = [("lut", l, p) for l in des.luts for p in ("a", "b", "c", "d", "cin")]
        pins += [("ff", f, p) for f in des.ffs for p in ("d", "asdata", "clk", "clrn", "ena", "sclr", "sload")]
        todo = list(pins)
        while todo:
            kind, cell, pin = todo.pop()
            m = pat.match(cell[pin])
            if not m or cell[pin] in defined:
                continue
            what, x, y, le = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
            if what == "q":
                ff = self.lift_ff(tr, plane, des, x, y, le)
                des.ffs.append(ff)
                defined.add(ff["q"])
                des.not_lifted["FF reached by a trace without an LE_BUFFER selecting it"] += 1
                todo += [("ff", ff, p) for p in ("d", "asdata", "clk", "clrn", "ena", "sclr", "sload")]
            else:
                net = f"u_ref_{cell[pin]}"
                des.terminals[net] = ("UNRESOLVED", "reference to an LE with no lifted LUT")
                des.unresolved.append((cell.get("name"), pin, "reference to an unused LE"))
                cell[pin] = net

    def break_loops(self, des):
        """A zero-delay loop in the lifted netlist is a decode error (built designs have none) and
        hangs the simulator: cut every LUT-to-LUT edge inside a strongly connected component and
        list it as unresolved ('comb loop')."""
        by_net = {}
        for l in des.luts:
            by_net[l["z"]] = l["name"]
            by_net[l["cout"]] = l["name"]
        idx = {l["name"]: i for i, l in enumerate(des.luts)}
        succ = [[] for _ in des.luts]
        for l in des.luts:
            for pin in ("a", "b", "c", "d", "cin"):
                src = by_net.get(l[pin])
                if src is not None:
                    succ[idx[src]].append(idx[l["name"]])
        # iterative Tarjan
        index, low, on, stack, comp = {}, {}, set(), [], {}
        counter = [0]
        for root in range(len(des.luts)):
            if root in index:
                continue
            work = [(root, 0)]
            while work:
                v, i = work.pop()
                if i == 0:
                    index[v] = low[v] = counter[0]
                    counter[0] += 1
                    stack.append(v)
                    on.add(v)
                if i < len(succ[v]):
                    work.append((v, i + 1))
                    w = succ[v][i]
                    if w not in index:
                        work.append((w, 0))
                    elif w in on:
                        low[v] = min(low[v], index[w])
                else:
                    if work:
                        low[work[-1][0]] = min(low[work[-1][0]], low[v])
                    if low[v] == index[v]:
                        members = []
                        while True:
                            w = stack.pop()
                            on.discard(w)
                            members.append(w)
                            if w == v:
                                break
                        for w in members:
                            comp[w] = (v, len(members))
        cut = 0
        for l in des.luts:
            me = idx[l["name"]]
            cid, size = comp[me]
            for pin in ("a", "b", "c", "d", "cin"):
                src = by_net.get(l[pin])
                if src is None:
                    continue
                s = idx[src]
                if comp[s][0] == cid and (size > 1 or s == me):
                    net = f"u_loop_{l['x']}_{l['y']}_{l['le']}_{pin}"
                    des.terminals[net] = ("UNRESOLVED", "comb loop")
                    des.unresolved.append((l["name"], pin, "comb loop"))
                    l[pin] = net
                    cut += 1
        des.not_lifted["comb loop edges cut (decode error)"] += cut

    def ff_exists(self, tr, plane, x, y, le):
        for i in (2 * le, 2 * le + 1):
            cands, _why = self.dec.sources(plane, self.geom, ("LE_BUFFER", 0, i), x, y)
            if any(c.startswith("DRV|FF|") for c in cands):
                return True
        return False

    def lift_ff(self, tr, plane, des, x, y, le):
        n = 2 * le + 1
        name = f"ff_{x}_{y}_{le}"
        ff = {"name": name, "x": x, "y": y, "le": le, "q": qnet(x, y, le)}
        owner = {"cin": "1'b0"}
        for port in ("CLK", "CLRN", "ENA", "SCLR", "SLOAD", "ASDATA", "DATAD"):
            got, why = tr.trace(("FF", n, port), x, y)
            if got is not None and got[0] == "LUTOUT":
                net = comb(x, y, le)
            else:
                net = self.net_of(got, des, name, port, owner) if got else None
            if net is None:
                des.unresolved.append((name, port, why))
                net = f"u_{x}_{y}_{le}_{port.lower()}"
                des.terminals[net] = ("UNRESOLVED", why)
            ff["d" if port == "DATAD" else port.lower()] = net
        ff["clk_inv"] = self.lab_bit(plane, x, y, *CLK_POL)
        return ff
