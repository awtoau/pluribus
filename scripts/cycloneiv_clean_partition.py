#!/usr/bin/env python3.15t
"""Partition a lifted Cyclone IV netlist into named KNOWN blocks and UNKNOWN components; annotate the RTL.

  python3.15t scripts/cycloneiv_clean_partition.py --nl NL.pkl --blocks boards/<b>/blocks.json [--build-seeds]
        [--rtl OUT.v] [--flat OUT_flat.v] [--lint] [--grow 2]

Seeds (instance names / LAB coords / hard-block coords / pads) live in the committed blocks.json; --build-seeds
regenerates it for the DJI m2001 image from this session's trace outputs (tmp/dji_spi/image_fork.json,
tmp/af3 cone, tmp/cycloneiv_clean/duml_entry_trace.json, boards/dji-m2001/pins.tsv). Growth is BOUNDED
(--grow rounds): a LUT joins a block only when every consumer is already in it, or when its LAB is mostly
that block and it touches it; FFs only when D-source and all consumers are inside. Two blocks claiming one
cell in a round = contested, left UNKNOWN and reported. Remainder: per-clock-domain connected components.

Outputs: tmp/cycloneiv_clean/partition.json, partition.md (coverage table), optional block-annotated RTL
(structured via rtl.lift homemap, flat via emit.verilog). Log tmp/logs/cycloneiv_clean_partition.log.
"""
import argparse
import collections
import json
import logging
import os
import pickle
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("partition")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean")
LINT_LIMIT_S = 900          # stall backstop: verilator lint of an 80 MB netlist (cycloneiv_clean_rtl.py uses 600; logged on expiry)

CONF_LABEL = {"V": "verified", "I": "inferred", "S": "structure known, function unknown", "U": "unknown"}


# ---------------------------------------------------------------------------------------------------------------- seeds
def _pins(path):
    from cycloneiv_clean_bus_trace import load_pins
    return load_pins(path)


def build_seeds(nl, D, board_dir):
    """DJI m2001 seed sets from this session's trace outputs -> list of block dicts (priority order)."""
    spi = json.load(open(os.path.join(REPO, "tmp", "dji_spi", "image_fork.json")))
    duml = json.load(open(os.path.join(OUT, "duml_entry_trace.json")))
    pins = _pins(os.path.join(board_dir, "pins.tsv"))
    import cycloneiv_clean_af3_engine as AF3
    from cycloneiv_clean_bus_trace import _capture_ff
    by_ref = collections.defaultdict(list)
    for r in pins:
        by_ref[r["chip_ref"].strip()].append(r)
    io_of = {io["ball"]: io for io in nl.ios}

    def drv_luts(balls):
        out = []
        for b in balls:
            io = io_of.get(b)
            for k in ("drv", "oe"):
                s = io.get(k) if io else None
                if s and s.startswith("lc_"):
                    out.append(s)
        return out

    blocks = []

    def add(name, conf, evidence, ffs=(), luts=(), labs=(), m9k=(), mac=(), pads=(), note=""):
        blocks.append(dict(name=name, confidence=conf, evidence=evidence, note=note,
                           seeds=dict(ffs=sorted(set(ffs)), luts=sorted(set(luts)), labs=sorted({tuple(l) for l in labs}),
                                      m9k=sorted({tuple(m) for m in m9k}), mac=sorted({tuple(m) for m in mac}), pads=sorted(set(pads)))))

    add("clock_infra", "V", "boards/dji-m2001/nets.tsv; docs/lightbridge-fpga.md s10", pads=["B14"],
        note="PLL_2/PLL_8 + 18 undecoded clock/source nets; counted separately (not LUT/FF cells)")
    # SPI slave register file (storage + decode); the radio-mode muxes in LAB (38,83) go to the engine block
    rf = list(spi["rf_ffs"].keys()) + spi["chain"]["ffs"] + spi["address_register"]["ffs"] + spi["readback_slices"]
    for g in spi.get("other_capture_groups", []):
        rf += g["ffs"]
    rf += spi["phase_node"]["leaves"]
    rl = [spi["command_match"]["node"], spi["phase_node"]["node"], spi["address_register"]["sload"], "lc_38_82_5"]
    for regs in spi["register_map"].values():
        rl += [g["enable"] for g in regs]
    add("spi_regfile", "V", "docs/lightbridge-fpga.md s6; tmp/dji_spi/image_fork.json (scripts/cycloneiv_clean_spi_trace.py)",
        ffs=rf, luts=rl, labs=[(37, 79), (37, 80), (37, 81), (37, 82), (37, 83), (38, 82)], pads=["AB11", "AA8", "AA9"])
    eng_ffs, eng_luts = [], []
    for o in spi["master"]["outputs"]:
        eng_luts.append(o["driver"])
        eng_ffs += [v for v in o["modes"].values() if v.startswith("ff_")]
    add("radio_spi_engine", "V", "docs/lightbridge-fpga.md s5; commit a2d81aa68; #177 comment 6543374632",
        ffs=eng_ffs, luts=eng_luts, labs=[(56, 85), (57, 87), (58, 87), (38, 83)], pads=["P19", "P20", "R19", "T19", "AA7"])
    eng, luts, _leaves, _ff, _lut = AF3.cone(nl)
    add("af3_engine", "V", "docs/lightbridge-fpga.md s8/s11a; scripts/cycloneiv_clean_af3_engine.py cone()",
        ffs=eng, luts=list(luts) + ["lc_12_87_3"], m9k=[(7, 85), (7, 86)], pads=["AF3"])
    fx3_pads = [r["ball"] for r in by_ref["FX3"]]
    fx3_cap = []
    for b in fx3_pads:
        f = _capture_ff(D, f"pad_{b}")
        if f:
            fx3_cap.append(f["name"])
    add("fx3_gpif", "V", "docs/lightbridge-fpga.md s9; boards/dji-m2001/pins.tsv FX3 rows; #177 comment 6543746246",
        ffs=fx3_cap, luts=drv_luts(fx3_pads) + ["lc_24_56_7"], labs=[(21, 53)], pads=fx3_pads)
    vt = [tuple(t) for t in duml["X"]["fx3_tiles"] if tuple(t) not in {(7, 32), (7, 33), (7, 46)}]
    we_luts = [t[4].strip("(!)") for t in duml["Y"]["staged_tiles"] if tuple(t[0]) in set(vt)]
    add("video_buffer", "V", "#177 comment 6543928814 (64 x 8192x1 tiles read by the FX3 DQ drivers)",
        m9k=vt, luts=we_luts, labs=[(19, 45)])
    sel = ["ff_11_45_3", "ff_11_45_6", "ff_12_47_4"]
    add("video_duml_demux", "V", "#177 comment 6543928814; docs/lightbridge-fpga.md s9",
        ffs=sel, labs=[(11, 45), (12, 47), (17, 45), (13, 25)])
    add("duml_uart_tx_ac11", "V", "#177 comment 6543928814 (2048-byte FIFO + 391 clk/bit UART TX); pins.tsv AC11",
        ffs=duml["W"]["ac11"]["counter"], m9k=[(7, 32), (7, 33)], labs=[(9, 33), (6, 32), (6, 33), (9, 34), (8, 34)], pads=["AC11"],
        note="structure V; stream identity (DUML) I")
    add("fx3_in_uart_tx_ac10", "V", "#177 comment 6543928814 (FX3 DQ input FIFO (7,46) + UART TX); pins.tsv AC10",
        m9k=[(7, 46)], labs=[(8, 46), (5, 46), (4, 46), (3, 45), (4, 45)], pads=["AC10"], note="structure V; stream identity I")
    cmp_luts = [k for k in duml["B_comparator"] if k.startswith("lc_")] + list(duml["C_combiner"].keys())
    cmp_ffs = list(duml["I_received_id_source"]["leaves"])
    for v in duml["B_comparator"].values():
        if isinstance(v, dict):
            cmp_ffs += v.get("other", [])
    add("rx_id_comparator", "V", "#177 comment 6543928814 (regs 3..5 vs received-ID register; deserialiser (31,65); frame timer)",
        ffs=cmp_ffs, luts=cmp_luts, labs=[(33, 89), (33, 90), (34, 90), (31, 65), (37, 88), (37, 89), (37, 90)], mac=[(43, 84)])
    add("frame_fsm", "V", "#177 comment 6543928814; pins.tsv AC8/AB12 (frame FSM over the 21-FF frame counter)",
        ffs=["ff_40_88_10", "ff_40_88_11"], labs=[(38, 86), (39, 86), (32, 89), (32, 90)], pads=["AC8", "AB12"],
        note="structure V; pad identity (P2.3 sync vs AD9363 ENABLE/TXNRX) I")
    tx_pads = [r["ball"] for r in by_ref["AD9363"] if r["label"].startswith("AD9363_TXD") or r["label"] == "TX_mux_select"]
    raddr = []
    for g in duml["L_data_only"]["tx_raddr"]:
        raddr += g["ffs"]
    add("tx_playback", "V", "#177 comment 6543928814 (16x24 playback RAM (23,62)/(23,63), 4-bit read counter, TX burst gate)",
        ffs=raddr, luts=drv_luts(tx_pads), m9k=[(23, 62), (23, 63)], labs=[(26, 63), (24, 63)], pads=tx_pads)
    add("uplink_record_readers", "I", "#177 comments 6543746246 (m1400 writes regs 0x44..0x7B) / 6543928814 (field readers)",
        labs=[(66, 78), (67, 83), (87, 75), (69, 80), (67, 81), (44, 79), (61, 78)],
        mac=[(74, 78), (74, 79), (74, 85), (43, 73)], m9k=[(81, 77), (65, 77), (94, 65), (94, 66), (94, 67), (94, 68), (94, 69), (94, 70)],
        note="structure V; role (uplink record -> baseband) I")
    rx_pads = [r["ball"] for r in by_ref["AD9363"] if r["dir"] == "in"]
    rx_cap, rx_m9k = [], []
    m9k_by_data = collections.defaultdict(set)
    for m in nl.m9k:
        for s in (m.get("data") or []):
            if s:
                m9k_by_data[s].add((m["x"], m["y"]))
    for b in rx_pads:
        f = _capture_ff(D, f"pad_{b}")
        if f:
            rx_cap.append(f["name"])
            rx_m9k += list(m9k_by_data.get(f["name"], ()))
    add("ad9363_rx_capture", "V", "boards/dji-m2001/pins.tsv AD9363 input rows; scripts/cycloneiv_clean_bus_trace.py",
        ffs=rx_cap, m9k=rx_m9k, pads=rx_pads, note="22 AD9363 input pads: 13-pad RX bus + M25 + N25 + 8 U-tagged no-sink pads; first capture stage only")
    add("reg3_tables", "S", "#177 comment 6543928814 (reg 3 indexes six 2048x4 tables)",
        m9k=[(36, 57), (36, 58), (36, 59), (36, 60), (36, 61), (36, 62), (36, 65)], labs=[(34, 61)])
    add("tx_source_bank", "S", "#177 comment 6543928814 (2048x4 bank feeding the ~9-stage TX pipeline)",
        m9k=[(23, 54), (23, 55), (23, 58), (23, 61), (36, 54), (36, 55)])
    misc = [r["ball"] for r in pins if r["chip_ref"].strip() in ("", "MCU", "MCU or board") or r["label"].startswith("bank")
            or r["label"] in ("status_passthru",)]
    misc = [b for b in misc if b not in {"AB11", "AA8", "AA9", "AA7", "AC10", "AC11", "B14"}]
    add("pads_misc", "U", "boards/dji-m2001/pins.tsv U/I rows without a block", luts=drv_luts(misc), pads=misc)
    return blocks


# ------------------------------------------------------------------------------------------------------------ partition
def cell_of(sig):
    """signal name -> cell id: LUT/FF name, ('m9k', x, y), ('mac', x, y), ('pad', ball) or None."""
    if not sig or sig in ("1'b0", "1'b1"):
        return None
    s = sig.strip()
    if s.startswith("(~") and s.endswith(")"):
        s = s[2:-1]
    if s.startswith("~"):
        s = s[1:]
    if s.startswith("lc_") or s.startswith("ff_"):
        return s
    if s.startswith("co_"):
        return "lc_" + s[3:]
    if s.startswith("pad_"):
        return ("pad", s[4:])
    if s.startswith("m9k_") or s.startswith("mac_"):
        p = s[4:].split("_")
        try:
            return (s[:3], int(p[0]), int(p[1]))
        except (ValueError, IndexError):
            return None
    return None


class Partition:
    def __init__(self, nl, blocks, grow=2, nets_tsv=None):
        self.nl, self.blocks, self.grow = nl, blocks, grow
        from lifters.cycloneiv_clean import functrace as FT
        self.fanout = FT._build_fanout(nl)
        self.lut = {L["name"]: L for L in nl.luts}
        self.ff = {F["name"]: F for F in nl.ffs}
        self.m9k = {(m["x"], m["y"]): m for m in nl.m9k}
        self.mac = {(m["x"], m["y"]): m for m in nl.mac}
        self.pad = {io["ball"]: io for io in nl.ios}
        self.lab = collections.defaultdict(list)
        for L in nl.luts:
            self.lab[(L["x"], L["y"])].append(L["name"])
        for F in nl.ffs:
            self.lab[(F["x"], F["y"])].append(F["name"])
        self.assign = {}
        self.conflicts, self.contested = [], []
        self.domain_name = {}
        if nets_tsv and os.path.exists(nets_tsv):
            for line in open(nets_tsv):
                if line.startswith("#") or not line.strip():
                    continue
                p = line.rstrip("\n").split("\t")
                if len(p) > 2 and p[2] == "clk":
                    self.domain_name[p[0]] = p[1]

    def cid(self, c):
        if isinstance(c, tuple):
            return c
        return c

    def consumers(self, cell):
        """cell ids consuming a LUT/FF/M9K/MAC output."""
        sigs = []
        if isinstance(cell, str):
            sigs.append(cell)
            if cell.startswith("lc_"):
                sigs.append("co_" + cell[3:])
        elif cell[0] == "m9k":
            m = self.m9k[(cell[1], cell[2])]
            sigs += [f"m9k_{cell[1]}_{cell[2]}_o[{i}]" for i in range(36)]
        elif cell[0] == "mac":
            sigs += [f"mac_{cell[1]}_{cell[2]}_r[{i}]" for i in range(72)]
        elif cell[0] == "pad":
            sigs.append(f"pad_{cell[1]}")
        out = set()
        for s in sigs:
            for kind, inst, pin, idx in self.fanout.get(s, ()):
                if kind in ("lc", "ff"):
                    out.add(inst)
                elif kind == "io":
                    out.add(("pad", inst))
                else:
                    out.add((kind, inst[0], inst[1]))
        return out

    def inputs(self, cell):
        """cell ids feeding a LUT/FF (data pins only; clock/aclr nets are global)."""
        out = set()
        if isinstance(cell, str) and cell.startswith("lc_"):
            for p in self.lut[cell]["pins"]:
                c = cell_of(p)
                if c:
                    out.add(c)
        elif isinstance(cell, str):
            F = self.ff[cell]
            for k in ("d", "ena", "sclr", "sload", "asdata"):
                c = cell_of(F.get(k))
                if c:
                    out.add(c)
        elif cell[0] == "m9k":
            m = self.m9k[(cell[1], cell[2])]
            for k in ("data", "addr", "raddr", "be", "data_b", "addr_b"):
                for p in (m.get(k) or []):
                    c = cell_of(p)
                    if c:
                        out.add(c)
            for k in ("we", "we_b", "ce", "ce_b"):
                c = cell_of(m.get(k))
                if c:
                    out.add(c)
        elif cell[0] == "mac":
            m = self.mac[(cell[1], cell[2])]
            for p in m["a"] + m["b"] + m.get("sign", []):
                c = cell_of(p)
                if c:
                    out.add(c)
            c = cell_of(m.get("ena"))
            if c:
                out.add(c)
        elif cell[0] == "pad":
            io = self.pad[cell[1]]
            for k in ("drv", "oe"):
                c = cell_of(io.get(k))
                if c:
                    out.add(c)
        return out

    def seed(self):
        for b in self.blocks:
            s = b["seeds"]
            cells = list(s.get("ffs", [])) + list(s.get("luts", []))
            for x, y in s.get("labs", []):
                cells += self.lab.get((x, y), [])
            cells += [("m9k", x, y) for x, y in s.get("m9k", []) if (x, y) in self.m9k]
            cells += [("mac", x, y) for x, y in s.get("mac", []) if (x, y) in self.mac]
            cells += [("pad", p) for p in s.get("pads", []) if p in self.pad]
            for c in cells:
                if isinstance(c, str) and c not in self.lut and c not in self.ff:
                    continue
                prev = self.assign.get(c)
                if prev is None:
                    self.assign[c] = b["name"]
                elif prev != b["name"]:
                    self.conflicts.append((str(c), prev, b["name"]))

    def grow_round(self, r):
        claims = collections.defaultdict(set)
        lab_share = {}
        for (x, y), cells in self.lab.items():
            cnt = collections.Counter(self.assign[c] for c in cells if c in self.assign)
            if cnt:
                blk, n = cnt.most_common(1)[0]
                if n * 2 >= len(cells):
                    lab_share[(x, y)] = blk
        for name, L in self.lut.items():
            if name in self.assign:
                continue
            cons = self.consumers(name)
            owners = {self.assign.get(c) for c in cons}
            if cons and None not in owners and len(owners) == 1:
                claims[name].add(next(iter(owners)))
                continue
            blk = lab_share.get((L["x"], L["y"]))
            if blk and (blk in owners or any(self.assign.get(c) == blk for c in self.inputs(name))):
                claims[name].add(blk)
        for name, F in self.ff.items():
            if name in self.assign:
                continue
            cons = self.consumers(name)
            owners = {self.assign.get(c) for c in cons}
            src = self.assign.get(cell_of(F.get("d")))
            if cons and None not in owners and len(owners) == 1 and src == next(iter(owners)):
                claims[name].add(src)
        n = 0
        for c, blks in claims.items():
            if len(blks) == 1:
                self.assign[c] = next(iter(blks))
                n += 1
            else:
                self.contested.append((c, sorted(blks)))
        log.info("grow round %d: +%d cells, %d contested", r, n, sum(1 for c, b in claims.items() if len(b) > 1))
        return n

    def domain(self, cell):
        if isinstance(cell, str) and cell.startswith("ff_"):
            return self.ff[cell].get("clk")
        if isinstance(cell, str):
            def clk_of(c):
                if isinstance(c, str):
                    return self.ff[c].get("clk") if c.startswith("ff_") else None
                if c[0] == "m9k":
                    return self.m9k[(c[1], c[2])].get("clk")
                if c[0] == "mac":
                    return self.mac[(c[1], c[2])].get("clk")
                return None
            cnt = collections.Counter(k for k in map(clk_of, self.consumers(cell)) if k)
            if cnt:
                return cnt.most_common(1)[0][0]
            cnt = collections.Counter(k for k in map(clk_of, self.inputs(cell)) if k)
            return cnt.most_common(1)[0][0] if cnt else None
        if cell[0] == "m9k":
            return self.m9k[(cell[1], cell[2])].get("clk")
        if cell[0] == "mac":
            return self.mac[(cell[1], cell[2])].get("clk")
        return None

    def unknown_components(self, small=32):
        rest = [c for c in list(self.lut) + list(self.ff) + [("m9k",) + k for k in self.m9k] + [("mac",) + k for k in self.mac]
                if c not in self.assign]
        dom = {c: self.domain(c) for c in rest}
        # deep comb networks (carry chains, XOR trees) have no clocked neighbour at 1 hop: propagate the
        # majority neighbour domain until stable (bounded: 20 sweeps, logged if still open)
        nb = {c: [n for n in (self.consumers(c) | self.inputs(c)) if n in dom] for c in rest if dom[c] is None}
        for sweep in range(20):
            changed = 0
            for c, ns in nb.items():
                if dom[c] is None:
                    cnt = collections.Counter(dom[n] for n in ns if dom[n])
                    if cnt:
                        dom[c] = cnt.most_common(1)[0][0]
                        changed += 1
            if not changed:
                break
        log.info("domain propagation: %d sweeps, %d cells still without a clock domain", sweep + 1, sum(1 for c in rest if dom[c] is None))
        parent = {c: c for c in rest}

        def find(c):
            while parent[c] != c:
                parent[c] = parent[parent[c]]
                c = parent[c]
            return c

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
        rs = set(rest)
        for c in rest:
            for i in self.inputs(c):
                if i in rs and dom[i] == dom[c]:
                    union(c, i)
        comps = collections.defaultdict(list)
        for c in rest:
            comps[find(c)].append(c)
        out = []
        smalls = collections.defaultdict(list)
        for root, cells in comps.items():
            d = dom[root]
            if len(cells) < small:
                smalls[d] += cells
                continue
            out.append((d, cells))
        for d, cells in smalls.items():
            out.append((d, cells))
        out.sort(key=lambda t: -len(t[1]))
        blocks = []
        k = collections.Counter()
        for d, cells in out:
            dn = self.domain_name.get(d, d or "noclk")
            k[dn] += 1
            name = f"unknown_{dn}_{k[dn]}" if len(cells) >= small else f"unknown_{dn}_small"
            xs = [self.lut[c]["x"] if c in self.lut else self.ff[c]["x"] for c in cells if isinstance(c, str)]
            ys = [self.lut[c]["y"] if c in self.lut else self.ff[c]["y"] for c in cells if isinstance(c, str)]
            bbox = [min(xs), min(ys), max(xs), max(ys)] if xs else None
            for c in cells:
                self.assign[c] = name
            blocks.append(dict(name=name, confidence="U", evidence="remainder: connected component within one clock domain",
                               note=f"clock {d} ({dn}); LAB bbox {bbox}", seeds={}, domain=d, bbox=bbox))
        self.blocks += blocks
        return blocks

    def run(self):
        self.seed()
        for r in range(1, self.grow + 1):
            if self.grow_round(r) == 0:
                break
        for ball in self.pad:
            self.assign.setdefault(("pad", ball), "pads_unassigned")
        unk = self.unknown_components()
        if any(v == "pads_unassigned" for v in self.assign.values()):
            self.blocks.append(dict(name="pads_unassigned", confidence="U", evidence="pads no block claimed", note="", seeds={}))
        return unk

    def table(self):
        tot = dict(luts=len(self.lut), ffs=len(self.ff), m9k=len(self.m9k), mac=len(self.mac), pads=len(self.pad))
        rows = []
        for b in self.blocks:
            cells = [c for c, n in self.assign.items() if n == b["name"]]
            cnt = dict(luts=sum(1 for c in cells if isinstance(c, str) and c.startswith("lc_")),
                       ffs=sum(1 for c in cells if isinstance(c, str) and c.startswith("ff_")),
                       m9k=sum(1 for c in cells if isinstance(c, tuple) and c[0] == "m9k"),
                       mac=sum(1 for c in cells if isinstance(c, tuple) and c[0] == "mac"),
                       pads=sum(1 for c in cells if isinstance(c, tuple) and c[0] == "pad"))
            used = cnt["luts"] + cnt["ffs"] + cnt["m9k"] + cnt["mac"]
            rows.append(dict(name=b["name"], confidence=b["confidence"], evidence=b["evidence"], note=b.get("note", ""),
                             counts=cnt, pct_cells=round(100.0 * used / (tot["luts"] + tot["ffs"] + tot["m9k"] + tot["mac"]), 2),
                             cells=dict(luts=sorted(c for c in cells if isinstance(c, str) and c.startswith("lc_")),
                                        ffs=sorted(c for c in cells if isinstance(c, str) and c.startswith("ff_")),
                                        m9k=sorted(list(c[1:]) for c in cells if isinstance(c, tuple) and c[0] == "m9k"),
                                        mac=sorted(list(c[1:]) for c in cells if isinstance(c, tuple) and c[0] == "mac"),
                                        pads=sorted(c[1] for c in cells if isinstance(c, tuple) and c[0] == "pad"))))
        return tot, rows


def markdown(tot, rows, conflicts, contested):
    def pct(n, t):
        return f"{100.0 * n / t:.1f}%" if t else "-"
    out = ["| block | conf | LUT | FF | M9K | MAC | pads | % cells | evidence |", "|---|---|---|---|---|---|---|---|---|"]
    agg = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        c = r["counts"]
        out.append(f"| {r['name']} | {r['confidence']} | {c['luts']} | {c['ffs']} | {c['m9k']} | {c['mac']} | {c['pads']} | {r['pct_cells']}% | {r['evidence']} |")
        agg[r["confidence"]].update(c)
    out.append("")
    out.append("| class | LUT | FF | M9K | MAC | pads |")
    out.append("|---|---|---|---|---|---|")
    for k in ("V", "I", "S", "U"):
        c = agg[k]
        out.append(f"| {k} {CONF_LABEL[k]} | {c['luts']} ({pct(c['luts'], tot['luts'])}) | {c['ffs']} ({pct(c['ffs'], tot['ffs'])}) | "
                   f"{c['m9k']} ({pct(c['m9k'], tot['m9k'])}) | {c['mac']} ({pct(c['mac'], tot['mac'])}) | {c['pads']} ({pct(c['pads'], tot['pads'])}) |")
    known = agg["V"] + agg["I"]
    out.append(f"| known (V+I) | {known['luts']} ({pct(known['luts'], tot['luts'])}) | {known['ffs']} ({pct(known['ffs'], tot['ffs'])}) | "
               f"{known['m9k']} ({pct(known['m9k'], tot['m9k'])}) | {known['mac']} ({pct(known['mac'], tot['mac'])}) | {known['pads']} ({pct(known['pads'], tot['pads'])}) |")
    out.append(f"| total | {tot['luts']} | {tot['ffs']} | {tot['m9k']} | {tot['mac']} | {tot['pads']} |")
    out.append("")
    out.append(f"seed conflicts (cell claimed by two seed sets, first wins): {len(conflicts)}; growth contested (left unknown): {len(contested)}")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------------- RTL annotation
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
KW = {"assign", "always", "begin", "end", "if", "else", "posedge", "negedge", "or", "case", "endcase", "default", "initial",
      "wire", "reg", "localparam", "input", "output", "inout", "module", "endmodule", "LUT_DELAY"}


def split_statements(lines):
    """[(lead comment lines, statement lines)] using begin/end depth (col-0 `end` lines exist in the structured RTL)."""
    out, cur, lead, depth = [], [], [], 0
    for l in lines:
        s = l.strip()
        if not cur and s.startswith("//"):
            lead.append(l)
            continue
        if not cur and not s:
            continue
        cur.append(l)
        toks = re.findall(r"\b(begin|end|case|endcase)\b", re.sub(r"//.*$", "", l))
        for t in toks:
            depth += 1 if t in ("begin", "case") else -1
        if depth <= 0:
            out.append((lead, cur))
            cur, lead, depth = [], [], 0
    if cur or lead:
        out.append((lead, cur))
    return out


def stmt_lhs(text):
    m = re.match(r"\s*assign\s+(?:`LUT_DELAY\s+)?([A-Za-z_]\w*)", text)
    if m:
        return m.group(1)
    m = re.match(r"\s*initial\s+begin\s+([A-Za-z_]\w*)", text)
    if m:
        return m.group(1)
    m = re.match(r"\s*localparam\s+(?:\[[^\]]*\]\s*)?([A-Za-z_]\w*)", text)
    if m:
        return m.group(1)
    if text.lstrip().startswith("always"):
        m = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*<=", text)
        if m:
            return m.group(1)
    m = re.match(r"\s*//\s*UNDECODED:\s*([A-Za-z_]\w*)", text)
    if m:
        return m.group(1)
    return None


class Annotator:
    def __init__(self, part, homemap, prefix="io_"):
        self.part, self.prefix = part, prefix
        self.rev = collections.defaultdict(collections.Counter)
        for flat, h in (homemap or {}).items():
            c = cell_of(flat)
            blk = part.assign.get(c) if c else None
            if blk:
                self.rev[h[0]][blk] += 1

    def name_block(self, n):
        if n is None:
            return None
        if n.startswith("I_"):
            n = n[2:]
        if n.startswith(self.prefix):
            return self.part.assign.get(("pad", n[len(self.prefix):]))
        if n.startswith("m9k_") or n.startswith("mac_"):
            p = n[4:].split("_")
            try:
                return self.part.assign.get((n[:3], int(p[0]), int(p[1])))
            except (ValueError, IndexError):
                return None
        c = cell_of(n)
        if c and c in self.part.assign:
            return self.part.assign[c]
        if n in self.rev:
            return self.rev[n].most_common(1)[0][0]
        return None

    def stmt_block(self, text):
        b = self.name_block(stmt_lhs(text))
        if b:
            return b, "lhs"
        cnt = collections.Counter()
        for n in IDENT.findall(re.sub(r"//.*$", "", text, flags=re.M)):
            if n in KW:
                continue
            bb = self.name_block(n)
            if bb:
                cnt[bb] += 1
        if cnt:
            return cnt.most_common(1)[0][0], "rhs"
        return "unmapped", "none"

    def annotate(self, text, table_md, order):
        lines = text.split("\n")
        i = next(k for k, l in enumerate(lines) if l.startswith("module "))
        j = next(k for k in range(i, len(lines)) if lines[k].startswith(");"))
        head, ports, body = lines[:i], lines[i:j + 1], lines[j + 1:]
        e = min(k for k, l in enumerate(body) if l.startswith("endmodule"))     # pattern sub-modules follow the top module
        tail = body[e:]
        body = body[:e]
        decls, groups, how = [], collections.defaultdict(list), collections.Counter()
        for lead, st in split_statements(body):
            first = st[0].lstrip() if st else ""
            if len(st) == 1 and re.match(r"(wire|reg)\b", first):      # declarations stay first (Verilog: declare before use)
                decls += lead + st
                continue
            blk, h = self.stmt_block("\n".join(st))
            how[h] += 1
            groups[blk] += lead + st
        out = head + ["// ==== PARTITION (scripts/cycloneiv_clean_partition.py): statements grouped by block; declarations kept first ===="]
        out += ["// " + l for l in table_md.split("\n")]
        out += ports + decls
        names = [b for b in order if b in groups] + sorted(b for b in groups if b not in order)
        for b in names:
            bl = next((x for x in self.part.blocks if x["name"] == b), None)
            conf = bl["confidence"] if bl else "U"
            ev = (bl["evidence"] if bl else "")
            out.append("")
            out.append(f"// ==== BLOCK: {b} ({conf}: {CONF_LABEL.get(conf, conf)}) {len(groups[b])} lines -- {ev} ====")
            out += groups[b]
        out += tail
        out = [l if len(l) < 30000 else l.replace("; ", ";\n  ") for l in out]      # verilator caps a line near 40 k tokens (same split as rtl.py)
        return "\n".join(out) + "\n", dict(how=dict(how), blocks={b: len(v) for b, v in groups.items()}, decl_lines=len(decls))


def lint(path):
    cmd = ["verilator", "--lint-only", "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-UNOPTFLAT", "-Wno-WIDTH", path, "--top-module", "cyc4_top"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=LINT_LIMIT_S)
    except subprocess.TimeoutExpired:
        log.error("lint %s exceeded %ds", path, LINT_LIMIT_S)
        return dict(status="timeout")
    errs = [l for l in r.stderr.splitlines() if l.startswith("%Error")]
    log.info("lint %s: rc=%d errors=%d %s", path, r.returncode, len(errs), errs[:3])
    return dict(status="clean" if r.returncode == 0 and not errs else "errors", rc=r.returncode, errors=len(errs), first=errs[:5])


# ------------------------------------------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", required=True)
    ap.add_argument("--blocks", required=True, help="boards/<board>/blocks.json (seeds; --build-seeds writes it)")
    ap.add_argument("--build-seeds", action="store_true")
    ap.add_argument("--grow", type=int, default=2)
    ap.add_argument("--rtl", help="write block-annotated structured RTL here (runs rtl.lift)")
    ap.add_argument("--flat", help="write block-annotated flat emit here")
    ap.add_argument("--lint", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_partition.log"))])
    from lifters.cycloneiv_clean import patterns as PT
    nl = pickle.load(open(a.nl, "rb"))
    D = PT.Design(nl)
    board_dir = os.path.dirname(os.path.abspath(a.blocks))
    if a.build_seeds:
        blocks = build_seeds(nl, D, board_dir)
        json.dump(dict(netlist=os.path.relpath(a.nl, REPO), blocks=blocks), open(a.blocks, "w"), indent=1)
        log.info("wrote %d seed blocks -> %s", len(blocks), a.blocks)
    blocks = json.load(open(a.blocks))["blocks"]
    for b in blocks:
        s = b["seeds"]
        for k in ("labs", "m9k", "mac"):
            s[k] = [tuple(t) for t in s.get(k, [])]
    P = Partition(nl, blocks, grow=a.grow, nets_tsv=os.path.join(board_dir, "nets.tsv"))
    unk = P.run()
    tot, rows = P.table()
    md = markdown(tot, rows, P.conflicts, P.contested)
    log.info("\n%s", md)
    log.info("unknown components: %d (largest %s)", len(unk), [(u["name"], len([c for c, n in P.assign.items() if n == u["name"]])) for u in unk[:6]])
    json.dump(dict(netlist=a.nl, totals=tot, blocks=rows, conflicts=P.conflicts[:500], n_conflicts=len(P.conflicts),
                   contested=[[str(c), b] for c, b in P.contested[:500]], n_contested=len(P.contested)),
              open(os.path.join(OUT, "partition.json"), "w"), indent=1)
    open(os.path.join(OUT, "partition.md"), "w").write(md + "\n")
    order = [b["name"] for b in P.blocks]
    rep = {}
    if a.rtl:
        from lifters.cycloneiv_clean import rtl
        hm = {}
        text, r = rtl.lift(nl, homemap=hm)
        log.info("rtl.lift: %d lines, %d homes", r.get("rtl_lines"), len(hm))
        ann, info = Annotator(P, hm).annotate(text, md, order)
        open(a.rtl, "w").write(ann)
        log.info("annotated RTL -> %s %s", a.rtl, json.dumps(info)[:600])
        rep["rtl"] = info
        if a.lint:
            rep["lint_rtl"] = lint(a.rtl)
    if a.flat:
        from lifters.cycloneiv_clean import emit
        text = emit.verilog(nl)
        ann, info = Annotator(P, {}).annotate(text, md, order)
        open(a.flat, "w").write(ann)
        log.info("annotated flat -> %s %s", a.flat, json.dumps(info)[:600])
        rep["flat"] = info
        if a.lint:
            rep["lint_flat"] = lint(a.flat)
    if rep:
        json.dump(rep, open(os.path.join(OUT, "partition_rtl.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
