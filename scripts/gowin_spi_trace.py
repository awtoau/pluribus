#!/usr/bin/env python3
"""Trace a GOWIN design's serial (SPI-style) command interface from the DB.

Runs under python3.15t against a loaded bitstream (PLURIBUS_SQLITE_PATH / the
usual backend selection).  Written for the FNIRSI/OpenScope 2C53T (GW1N-2)
SPI command-interface recovery (issue #70), but nothing here is board-specific:
give it a serial-input pad and it reports the same structure for any GOWIN
design.

    python3.15t scripts/gowin_spi_trace.py --bitstream LABEL --si-pad IOB18B

Sections
    1. Pad roles           — which pads reach modelled fabric at all, and how.
                             GOWIN routes SCLK/CS_N of a slave port into the
                             clock tree, where pluribus models no consumer, so
                             this section is mostly about proving what is NOT
                             traceable (and why) as much as what is.
    2. Input shift chain   — walk SI forward through gated LUT stages to recover
                             the deserialiser and hence the command WIDTH.
    3. Command register    — the flop bank that latches the chain (shared CE),
                             and which shift stages feed which register bit.
    4. Opcode decode       — every net that is a pure AND-minterm over the
                             command register, i.e. a decoded opcode enable,
                             plus the flops/ports each one gates.
    5. Readback path       — reconstructs the GW1N wide-mux (MUX2_LUT5/6/7/8)
                             chain, which pluribus does NOT model as cells, to
                             recover the output mux that drives the SO pad.
    6. Edge sensitivity    — negative-edge flop census, which is what decides
                             (or fails to decide) the SPI-mode question.

Section 5 is the reusable part worth knowing about: apicula's OF0..OF7 wires
are the wide-mux chain, and because pluribus lifts only LUT4/DFF/ALU/BSRAM,
any net driven by an OF wire has no modelled driver and a datapath through it
silently dead-ends.  This script rebuilds that chain from the arcs table.
"""

import argparse
import collections
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from sqlalchemy import text  # noqa: E402

from db import engine, die  # noqa: E402

# apicula wide-mux chain within one CFU tile (apycula/gowin_unpack.make_muxes).
# MUX2(I0, I1, S0) -> O, with O = S0 ? I1 : I0.
WIDE_MUX = [
    # (name,        I0,    I1,    O,     S0)
    ("MUX2_LUT50", "F0",  "F1",  "OF0", "SEL0"),
    ("MUX2_LUT51", "F2",  "F3",  "OF2", "SEL2"),
    ("MUX2_LUT52", "F4",  "F5",  "OF4", "SEL4"),
    ("MUX2_LUT53", "F6",  "F7",  "OF6", "SEL6"),
    ("MUX2_LUT60", "OF2", "OF0", "OF1", "SEL1"),
    ("MUX2_LUT61", "OF6", "OF4", "OF5", "SEL5"),
    ("MUX2_LUT70", "OF5", "OF1", "OF3", "SEL3"),
    ("MUX2_LUT80", "OF3", "OF3", "OF7", "SEL7"),
]
MUX_BY_OUT = {m[3]: m for m in WIDE_MUX}

CONST = lambda n: (not n) or str(n).startswith("1'b")  # noqa: E731


# ── LUT INIT decoding ────────────────────────────────────────────────────────

def lut_table(init16):
    """INIT is an MSB-first bit string; return f[p] for truth address
    p = A + 2B + 4C + 8D (see lifters/gowin_lift.py)."""
    v = int(init16, 2)
    return [(v >> p) & 1 for p in range(16)]


def care_inputs(init16):
    f = lut_table(init16)
    return [i for i in range(4) if any(f[p] != f[p ^ (1 << i)] for p in range(16))]


def lut_expr(init16, names="ABCD"):
    """Decode INIT to a readable expression, recognising BUF / 2:1 MUX / AND
    forms before falling back to sum-of-products over the care inputs."""
    f = lut_table(init16)
    care = care_inputs(init16)
    mt = [p for p in range(16) if f[p]]
    if not mt:
        return "0"
    if len(mt) == 16:
        return "1"
    if len(care) == 1:
        i = care[0]
        return names[i] if f[1 << i] else f"~{names[i]}"
    # 2:1 mux on one select input
    for s in care:
        others = [i for i in care if i != s]
        if len(others) == 2:
            for x in others:
                for y in others:
                    if all(f[p] == (((p >> x) & 1) if ((p >> s) & 1) else ((p >> y) & 1))
                           for p in range(16)):
                        return f"{names[s]} ? {names[x]} : {names[y]}"
    # pure AND (single minterm projected onto the care set)
    proj = sorted({tuple((p >> i) & 1 for i in care) for p in mt})
    terms = [" & ".join((names[i] if b else "~" + names[i])
                        for i, b in zip(care, combo)) for combo in proj]
    return " | ".join(terms)


# ── netlist model ────────────────────────────────────────────────────────────

class Net:
    """Driver/consumer maps over the lifted cells, plus the tile wide-mux chain."""

    def __init__(self, conn, bs_id):
        self.bs = bs_id
        self.ffs = {r[0]: r for r in conn.execute(text(
            "SELECT cell,clk,ce,d,q,lsr,dtype FROM ffs WHERE bitstream=:b"),
            {"b": bs_id})}
        self.luts = {r[0]: r for r in conn.execute(text(
            "SELECT cell,init,a,b,c,d,z,fn FROM luts WHERE bitstream=:b"),
            {"b": bs_id})}
        self.alus = list(conn.execute(text(
            "SELECT cell,sum_net,cout_net,cin,i0,i1,i3 FROM alu_cells WHERE bitstream=:b"),
            {"b": bs_id}))
        self.ebr = list(conn.execute(text(
            "SELECT block,port,role,net FROM ebr_ports WHERE bitstream=:b"),
            {"b": bs_id}))
        self.pads = {}
        for pin, lab, ni, no in conn.execute(text(
                "SELECT pin,label,net_in,net_out FROM pad_map WHERE bitstream=:b"),
                {"b": bs_id}):
            self.pads[lab] = {"pin": pin, "in": ni, "out": no}
        for net, name in conn.execute(text(
                "SELECT net,name FROM net_names WHERE bitstream=:b "
                "AND source='gowin_iob_unbonded'"), {"b": bs_id}):
            self.pads.setdefault(name, {"pin": None, "in": net, "out": None})

        self.drv = {}
        self.cons = collections.defaultdict(list)
        for cell, clk, ce, d, q, lsr, dt in self.ffs.values():
            if q:
                self.drv[q] = ("FF", cell, dt)
            for port, n in (("CLK", clk), ("CE", ce), ("D", d), ("LSR", lsr)):
                if not CONST(n):
                    self.cons[n].append((cell, port))
        for cell, init, a, b, c, d, z, fn in self.luts.values():
            if z:
                self.drv[z] = ("LUT", cell, init)
            for port, n in (("A", a), ("B", b), ("C", c), ("D", d)):
                if not CONST(n):
                    self.cons[n].append((cell, port))
        for cell, sn, cn, cin, i0, i1, i3 in self.alus:
            if sn:
                self.drv[sn] = ("ALU", cell, "SUM")
            if cn:
                self.drv[cn] = ("ALU", cell, "COUT")
            for port, n in (("CIN", cin), ("I0", i0), ("I1", i1), ("I3", i3)):
                if not CONST(n):
                    self.cons[n].append((cell, port))
        self.ebr_port = collections.defaultdict(list)
        for blk, port, role, net in self.ebr:
            if CONST(net):
                continue
            self.ebr_port[net].append((blk, port))
            if port.startswith("DO"):
                self.drv[net] = ("BSRAM", blk, port)
            else:
                self.cons[net].append((f"BSRAM[{blk}]", port))

        # tile wide-mux chain: which net each OF wire carries
        self.of_net = {}
        for tr, tc, sw, snet, srcw, srcnet in conn.execute(text(
                "SELECT tile_row,tile_col,sink_wire,sink_net,source_wire,source_net "
                "FROM arcs WHERE bitstream=:b"), {"b": bs_id}):
            for wire, net in ((sw, snet), (srcw, srcnet)):
                if wire and "_OF" in wire and net:
                    self.of_net[wire] = net
        self.sel_net = {}
        for sw, snet, srcnet in conn.execute(text(
                "SELECT sink_wire,sink_net,source_net FROM arcs WHERE bitstream=:b "
                "AND sink_wire LIKE '%SEL%'"), {"b": bs_id}):
            if sw:
                self.sel_net[sw] = srcnet or snet

    def dname(self, net):
        if CONST(net):
            return str(net)
        d = self.drv.get(net)
        if not d:
            return f"{net}(no modelled driver)"
        return f"{net}<-{d[1]}.{'Q' if d[0]=='FF' else d[2] if d[0] in ('ALU','BSRAM') else 'Z'}"

    def pad_of(self, net):
        for lab, p in self.pads.items():
            if p["in"] == net:
                return f"{lab}.in"
            if p["out"] == net:
                return f"{lab}.out"
        return None


# ── section 2: input shift chain ─────────────────────────────────────────────

def _capture_steps(nl, net, seen):
    """Candidate next stages: LUTs reading NET whose output is some flop's D.
    Yields (ff_cell, q_net, lut_cell, care_nets)."""
    for cell, _port in nl.cons.get(net, []):
        if not cell.startswith("lut_"):
            continue
        r = nl.luts[cell]
        z = r[6]
        if not z:
            continue
        care = {r[2:6][i] for i in care_inputs(r[1])}
        if net not in care:
            continue          # NET is a don't-care for this LUT
        for fcell, fport in nl.cons.get(z, []):
            if fport == "D" and fcell in nl.ffs and fcell not in seen:
                yield fcell, nl.ffs[fcell][4], cell, care


def walk_shift_chain(nl, si_net, maxlen=64):
    """Recover a *gated* serial shift chain.

    A GOWIN serial deserialiser stage is `D = prev_Q & shift_enable`, so every
    stage's D-LUT reads the previous stage's Q together with one common enable
    net.  Latching onto that shared enable is what distinguishes the real chain
    from the many other LUTs a serial bit fans out into (a naive "first LUT that
    feeds a flop" walk leaves the chain almost immediately).

    Returns [(stage, ff_cell, q_net, lut_cell)].
    """
    chain, seen = [], set()

    # Stage 1: the pad net's capture flop. Its LUT's other care inputs are the
    # candidate shift-enable nets.
    first = list(_capture_steps(nl, si_net, seen))
    if not first:
        return chain
    # Prefer a 2-input AND (data & enable) if one is present.
    first.sort(key=lambda t: len(t[3]))
    fcell, q, lut, care = first[0]
    gates = [n for n in care if n != si_net]
    seen.add(fcell)
    chain.append((1, fcell, q, lut))

    # Follow whichever gate net actually sustains the longest chain.
    best = chain
    for gate in gates:
        cur_chain, cur, cur_seen = list(chain), q, set(seen)
        while len(cur_chain) < maxlen and not CONST(cur):
            nxt = None
            for fcell, qq, lut, care in _capture_steps(nl, cur, cur_seen):
                if gate in care:
                    nxt = (fcell, qq, lut)
                    break
            if not nxt:
                break
            fcell, qq, lut = nxt
            cur_seen.add(fcell)
            cur_chain.append((len(cur_chain) + 1, fcell, qq, lut))
            cur = qq
        if len(cur_chain) > len(best):
            best = cur_chain
    return best


# ── section 4: opcode minterm decoding ───────────────────────────────────────

def decode_minterm(nl, net, cmd_q, maxd=6, depth=0, seen=None):
    """If NET is a pure AND of command-register bits (through any depth of
    single-minterm LUTs), return {cmd_net: 0|1}; else None."""
    if seen is None:
        seen = set()
    if CONST(net):
        return {} if str(net).endswith("1") else None
    if net in cmd_q:
        return {net: 1}
    d = nl.drv.get(net)
    if d is None or d[0] != "LUT" or depth >= maxd or net in seen:
        return None
    seen = seen | {net}
    init = d[2]
    f = lut_table(init)
    care = care_inputs(init)
    mt = [p for p in range(16) if f[p]]
    if not mt:
        return None
    proj = {tuple((p >> i) & 1 for i in care) for p in mt}
    if len(proj) != 1:
        return None
    combo = next(iter(proj))
    r = nl.luts[d[1]]
    out = {}
    for i, bit in zip(care, combo):
        sub = decode_minterm(nl, r[2:6][i], cmd_q, maxd, depth + 1, seen)
        if sub is None:
            return None
        for k, v in sub.items():
            val = v if bit else (1 - v)
            if k in out and out[k] != val:
                return None
            out[k] = val
    return out


# ── section 5: readback wide-mux ─────────────────────────────────────────────

def resolve_wide_mux(nl, out_wire):
    """Expand a tile OF wire through the MUX2_LUT chain into its leaf sources.
    Returns (tree_lines, leaf_nets)."""
    tile = out_wire.rsplit("_", 1)[0]
    lines, leaves = [], []

    def rec(wire, depth):
        short = wire.rsplit("_", 1)[1]
        pad = "  " * depth
        if short.startswith("F"):
            net = nl.of_net.get(wire)
            # tile F<i> wire == LUT<i> output; find it by position
            idx = short[1:]
            cell = f"lut_{tile_to_cell(tile)}_LUT{idx}"
            if cell in nl.luts:
                r = nl.luts[cell]
                lines.append(f"{pad}{short} = {cell} INIT={r[1]} => {lut_expr(r[1])}")
                for p, n in zip("ABCD", r[2:6]):
                    if p in [ "ABCD"[i] for i in care_inputs(r[1]) ]:
                        lines.append(f"{pad}    {p}={nl.dname(n)}")
                        leaves.append(n)
            else:
                lines.append(f"{pad}{short} = (no LUT)")
            return
        m = MUX_BY_OUT.get(short)
        if not m:
            lines.append(f"{pad}{short} = ?")
            return
        name, i0, i1, o, s0 = m
        selw = f"{tile}_{s0}"
        selnet = nl.sel_net.get(selw)
        lines.append(f"{pad}{short} = {name}(S0={s0}->{selnet}) ? {i1} : {i0}")
        rec(f"{tile}_{i1}", depth + 1)
        rec(f"{tile}_{i0}", depth + 1)

    rec(out_wire, 0)
    return lines, leaves


def tile_to_cell(tile):
    """R17C12 -> r16c11 (pluribus cells are 0-based)."""
    import re
    m = re.match(r"R(\d+)C(\d+)", tile)
    if not m:
        return tile
    return f"r{int(m.group(1))-1}c{int(m.group(2))-1}"


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bitstream", required=True, help="bitstream label")
    ap.add_argument("--si-pad", help="serial-input pad label (e.g. IOB18B)")
    ap.add_argument("--so-wire", help="tile OF wire driving the serial output "
                                      "(e.g. R17C12_OF5); auto-detected if omitted")
    ap.add_argument("--max-chain", type=int, default=64)
    args = ap.parse_args()

    eng = engine()
    with eng.connect() as conn:
        row = conn.execute(text("SELECT id FROM bitstreams WHERE label=:l"),
                           {"l": args.bitstream}).fetchone()
        if not row:
            die(f"no bitstream labelled {args.bitstream!r}")
        nl = Net(conn, row[0])

    print(f"=== gowin_spi_trace: {args.bitstream} ===")
    print(f"  {len(nl.ffs)} FFs, {len(nl.luts)} LUTs, {len(nl.alus)} ALU, "
          f"{len(nl.pads)} pads")

    # 1. pad roles
    print("\n--- 1. pad fabric roles ---")
    for lab in sorted(nl.pads):
        p = nl.pads[lab]
        for side in ("in", "out"):
            net = p[side]
            if not net:
                continue
            c = nl.cons.get(net, [])
            d = nl.drv.get(net)
            if not c and not d:
                continue
            print(f"  {lab:8s} {side:3s} {net:8s} consumers={len(c)} "
                  f"driver={d[1] if d else '-'}")
    dead = [l for l in sorted(nl.pads)
            if not any(nl.cons.get(n) or nl.drv.get(n)
                       for n in (nl.pads[l]["in"], nl.pads[l]["out"]) if n)]
    print(f"  pads with NO modelled fabric touch ({len(dead)}): {dead}")

    # 2. shift chain
    chain = []
    if args.si_pad:
        p = nl.pads.get(args.si_pad)
        if not p:
            die(f"pad {args.si_pad} not in pad_map/net_names")
        si = p["in"]
        print(f"\n--- 2. input shift chain from {args.si_pad} ({si}) ---")
        chain = walk_shift_chain(nl, si, args.max_chain)
        for st, cell, q, lut in chain:
            r = nl.ffs[cell]
            print(f"  stage{st:<2d} {cell:18s} q={q:8s} clk={r[1]:8s} "
                  f"ce={str(r[2]):8s} {r[6]:5s} via {lut} "
                  f"INIT={nl.luts[lut][1]} => {lut_expr(nl.luts[lut][1])}")
        print(f"  => recovered command width: {len(chain)} bits")

    # 3. command register: flop bank whose D comes from chain stages
    print("\n--- 3. command register ---")
    stage_q = {q: st for st, _, q, _ in chain}
    cmdbits = {}
    for cell, r in nl.ffs.items():
        d = r[3]
        src = nl.drv.get(d)
        if src and src[0] == "LUT":
            lr = nl.luts[src[1]]
            for n in lr[2:6]:
                if n in stage_q:
                    cmdbits[cell] = (stage_q[n], r[4], r[2])
    # Every bank of chain-fed flops sharing one real (non-constant) clock-enable
    # is a parallel latch of the shift chain.  A design may have several: one
    # holding the opcode field and others holding whole received data bytes, so
    # report them all rather than guessing which is "the" command register.
    byce = collections.defaultdict(dict)
    for cell, v in cmdbits.items():
        if not CONST(v[2]):
            byce[v[2]][cell] = v
    banks = sorted(byce.items(), key=lambda kv: -len(kv[1]))
    if not banks:
        print("  none found (no bank of chain-fed flops shares a real CE)")
    for load_ce, bank in banks:
        stages = sorted(v[0] for v in bank.values())
        print(f"  bank: load CE={load_ce}  {len(bank)} bits  stages={stages}")
        for cell, (st, q, ce) in sorted(bank.items(), key=lambda kv: kv[1][0]):
            print(f"      stage{st} -> {cell:18s} q={q}")

    # 4. opcode decode — try each bank; the opcode register is whichever one
    # actually has minterm decodes hanging off it.
    print("\n--- 4. opcode decodes (pure minterms over a chain-fed bank) ---")
    allnets = set(nl.cons) | set(nl.drv)
    any_hits = False
    for load_ce, bank in banks:
        cmd_q = {v[1]: c for c, v in bank.items()}
        stage_of = {v[1]: v[0] for v in bank.values()}
        hits = {}
        for n in allnets:
            dec = decode_minterm(nl, n, cmd_q)
            if dec and len(dec) >= 3:
                hits[n] = dec
        if not hits:
            continue
        any_hits = True
        print(f"  bank CE={load_ce}: {len(hits)} decoded enable nets")
        for n, dec in sorted(hits.items()):
            # stage k holds bit (k-1): stage 1 is the LAST bit clocked in and so
            # the LSB under MSB-first framing (see the ALU bit-order evidence).
            val = mask = 0
            for net, bit in dec.items():
                b = stage_of.get(net)
                if b is None:
                    continue
                mask |= 1 << (b - 1)
                val |= bit << (b - 1)
            gated = nl.cons.get(n, [])
            ce_t = sorted({c for c, p in gated if p == "CE"})
            print(f"    {n:8s} opcode=0x{val:02x} mask=0x{mask:02x} "
                  f"({len(dec)} bits) gates {len(ce_t)} CE")
            if ce_t:
                print(f"             targets: {ce_t}")
    if not any_hits:
        print("  none")

    # 5. readback wide-mux
    print("\n--- 5. readback path (GW1N wide-mux chain, not modelled as cells) ---")
    ofw = args.so_wire
    if not ofw:
        cands = [w for w in nl.of_net if w.rsplit("_", 1)[1] in MUX_BY_OUT]
        if len(cands) == 1:
            ofw = cands[0]
        elif cands:
            print(f"  candidates: {cands} (pick one with --so-wire)")
    if ofw:
        net = nl.of_net.get(ofw)
        print(f"  {ofw} carries {net}  (pad: {nl.pad_of(net)})")
        lines, leaves = resolve_wide_mux(nl, ofw)
        for l in lines:
            print("    " + l)
        print(f"  => {len(leaves)} mux leaf sources")
    else:
        print("  no wide-mux output wire in use")

    # 6. edge sensitivity
    print("\n--- 6. edge sensitivity (SPI mode evidence) ---")
    dt = collections.Counter(r[6] for r in nl.ffs.values())
    neg = {k: v for k, v in dt.items() if k.startswith(("DFFN", "DLN"))}
    print(f"  flop dtypes: {dict(dt)}")
    print(f"  negative-edge flops: {neg if neg else 'NONE'}")
    print("  => all sequential elements are positive-edge; the fabric samples on"
          " the RISING clock edge.")
    print("  NOTE: SPI mode 0 and mode 3 BOTH sample on the rising edge; they")
    print("        differ only in CPOL (idle level), which is a master-side")
    print("        property with no representation in a slave netlist.")


if __name__ == "__main__":
    main()
