#!/usr/bin/env python3.15t
"""High-level Cyclone IV GX (EP4CGX150) corpus: parametrised Verilog designs with a ground-truth construct manifest (#165).

Each design = parts from a PART LIBRARY (counters, adders, comparators, LFSRs, CRC, FSMs, registers, muxes, M9K RAM/ROM/FIFO, MACs,
pipelines, composites, large resource fillers).  Seeded, deterministic.  Written to <root>/hl_<kind>_<seed>/:
  src/top.v, src/hl_truth.json (constructs + parameters + expected recovered counts), src/*.mif, design.toml.
IO style (--style): min = one clock pad + one output pad (stimulus from on-chip LFSR banks, output = registered XOR-reduction of all
state); virt = every port a VIRTUAL_PIN (feasibility only; see docs/altera/cycloneIV/cycloneiv-clean-hl-corpus.md).

  python3.15t scripts/cycloneiv_hl_corpus.py --feasibility            # 3 designs x 2 styles -> tmp/hlcorpus/
  python3.15t scripts/cycloneiv_hl_corpus.py --generate [--root DIR]  # the corpus (default corpus/cycloneiv)
  python3.15t scripts/cycloneiv_hl_corpus.py --build [--root DIR] [--match 'hl_fsm_*'] [--jobs 4] [--force]
Log: tmp/logs/cycloneiv_hl_corpus.log
"""
import argparse
import fnmatch
import json
import logging
import math
import os
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
log = logging.getLogger("cycloneiv_hl_corpus")
DEVICE = "EP4CGX150DF31C7"
# source: Xilinx XAPP052 maximal-length LFSR tap sets (1-indexed, XNOR feedback; all-ones is the lock-up state, all-zeros is valid)
TAPS = {32: [32, 22, 2, 1], 31: [31, 28], 30: [30, 6, 4, 1], 29: [29, 27], 28: [28, 25], 27: [27, 5, 2, 1], 26: [26, 6, 2, 1],
        25: [25, 22], 24: [24, 23, 22, 17], 23: [23, 18], 22: [22, 21], 20: [20, 17], 16: [16, 15, 13, 4], 15: [15, 14], 12: [12, 6, 4, 1],
        10: [10, 7], 9: [9, 5], 8: [8, 6, 5, 4], 7: [7, 6], 6: [6, 5], 5: [5, 3], 4: [4, 3], 64: [64, 63, 61, 60], 48: [48, 47, 21, 20],
        40: [40, 38, 21, 19], 36: [36, 25]}
BANK_W = [32, 31, 30, 29, 28, 27, 26, 25]
MAX_BANKS = 8
# source: standard CRC generator polynomials (width, poly)
POLYS = {"crc8": (8, 0x07), "crc16ccitt": (16, 0x1021), "crc16ibm": (16, 0x8005), "crc32": (32, 0x04C11DB7), "crc32c": (32, 0x1EDC6F41)}


class Design:
    def __init__(s, kind, seed, style="min", virtclk=False):
        s.kind, s.seed, s.style, s.virtclk = kind, seed, style, virtclk
        s.rng = random.Random(f"hl:{kind}:{seed}")
        s.decl, s.body, s.truth, s.obs, s.ports, s.virt, s.files = [], [], [], [], [], [], {}
        s.n, s.banks, s.params, s.qsf, s.used_pairs = 0, [], {}, [], set()
        s.counts = {}

    def nm(s, p):
        s.n += 1
        return f"{p}{s.n}"

    # ---- truth bookkeeping
    def T(s, kind, role="dut", counts=None, **params):
        s.truth.append(dict(kind=kind, role=role, **params))
        for k, v in (counts or {}).items():
            s.counts[k] = s.counts.get(k, 0) + v

    # ---- stimulus
    def _bank(s):
        w = BANK_W[len(s.banks) % len(BANK_W)]
        i = len(s.banks)
        nm = f"stim{i}"
        fb = " ^ ".join(f"{nm}[{t - 1}]" for t in TAPS[w])
        s.decl.append(f"reg [{w - 1}:0] {nm};")
        s.body.append(f"always @(posedge clk) {nm} <= {{{nm}[{w - 2}:0], ~({fb})}};")
        s.T("lfsr", "stimulus", {"shift_registers": 1, "reg_bits": w}, width=w, taps=TAPS[w], form="fibonacci_xnor")
        order = list(range(w))
        s.rng.shuffle(order)
        s.banks.append([nm, w, order, 0])

    def stim1(s):
        """one stimulus bit (expression)."""
        if s.style == "virt":
            return s.stim(1)
        if len(s.banks) < MAX_BANKS and (not s.banks or s.banks[-1][3] >= s.banks[-1][1]):
            s._bank()
        b = s.banks[-1] if len(s.banks) < MAX_BANKS or s.banks[-1][3] < s.banks[-1][1] else s.banks[s.rng.randrange(len(s.banks))]
        nm, w, order, k = b
        b[3] += 1
        return f"{nm}[{order[k % w]}]"

    def stim(s, n):
        """n-bit stimulus expression (MSB first concat)."""
        if s.style == "virt":
            p = s.nm("in_")
            s.ports.append(f"input [{n - 1}:0] {p}")
            s.virt.append(p)
            return p
        return "{" + ", ".join(s.stim1() for _ in range(n)) + "}" if n > 1 else s.stim1()

    def stimx(s, n):
        """n bits, each the XOR of two distinct stimulus bits (unique per bit: keeps registers from being merged)."""
        if s.style == "virt":
            return s.stim(n)
        out = []
        for _ in range(n):
            while True:
                a, b = s.stim1(), s.stim1()
                if a != b and (a, b) not in s.used_pairs:
                    s.used_pairs.add((a, b))
                    break
            out.append(f"({a} ^ {b})")
        return "{" + ", ".join(out) + "}"

    def observe(s, sig, w):
        s.obs.append((sig, w))

    # ---- assembly
    def verilog(s):
        ports = ["input clk"] + s.ports
        obs_lines, outs = [], []
        if s.style == "virt":
            for i, (sig, w) in enumerate(s.obs):
                p = f"out_{i}"
                ports.append(f"output [{w - 1}:0] {p}")
                obs_lines.append(f"assign {p} = {sig};")
                s.virt.append(p)
        else:
            ports.append("output y")
            terms = " ^ ".join(f"(^{sig})" if w > 1 else sig for sig, w in s.obs)
            s.decl.append("reg y_q;")
            obs_lines.append(f"always @(posedge clk) y_q <= {terms};")
            obs_lines.append("assign y = y_q;")
            s.T("xor_reduce", "observer", {}, inputs=len(s.obs))
            s.T("register", "observer", {"reg_bits": 1}, width=1)
        return ("module top (\n  " + ",\n  ".join(ports) + "\n);\n" + "\n".join(s.decl) + "\n" + "\n".join(s.body) + "\n" + "\n".join(obs_lines) + "\nendmodule\n")

    def qsf_lines(s):
        q = list(s.qsf)
        for p in s.virt:
            q.append(f"set_instance_assignment -name VIRTUAL_PIN ON -to {p}")
        if s.virtclk:
            q.append("set_instance_assignment -name VIRTUAL_PIN ON -to clk")
        return q


# ---------------------------------------------------------------------------------------------------------------------------------
# parts.  Each appends decl/body/truth and observes its state.  Returns outputs for composites.
# ---------------------------------------------------------------------------------------------------------------------------------
def regs_ab(d, w):
    a, b = d.nm("a"), d.nm("b")
    d.decl += [f"reg [{w - 1}:0] {a}, {b};"]
    d.body.append(f"always @(posedge clk) begin {a} <= {d.stimx(w)}; {b} <= {d.stimx(w)}; end")
    return a, b


def p_counter(d, w=None, mode=None, en=None, ld=None, clr=None, step=None):
    r = d.rng
    w = w or r.choice([4, 6, 8, 10, 12, 16, 20, 24, 32])
    mode = mode or r.choice(["up", "down", "updown"])
    en = r.random() < .5 if en is None else en
    ld = r.random() < .3 if ld is None else ld
    clr = r.random() < .4 if clr is None else clr
    step = step or (1 if r.random() < .6 else r.choice([2, 3, 5, 7]) if w > 4 else 1)
    c = d.nm("cnt")
    d.decl.append(f"reg [{w - 1}:0] {c};")
    ops = {"up": f"{c} + {w}'d{step}", "down": f"{c} - {w}'d{step}", "updown": f"{d.stim1()} ? {c} + {w}'d{step} : {c} - {w}'d{step}"}[mode]
    ch = [f"if ({d.stim1()} & {d.stim1()} & {d.stim1()}) {c} <= {{{w}{{1'b0}}}};"] if clr else []
    if ld:
        ch.append(f"{'else ' if ch else ''}if ({d.stim1()} & {d.stim1()}) {c} <= {d.stim(w)};")
    ch.append(f"{'else ' if ch else ''}{'if (' + d.stim1() + ') ' if en else ''}{c} <= {ops};")
    d.body.append(f"always @(posedge clk) begin\n  " + "\n  ".join(ch) + "\nend")
    d.T("counter", counts={"counters": 1, "reg_bits": w}, width=w, mode=mode, step=step, enable=en, load=ld, clear=clr)
    d.observe(c, w)
    return c, w


def p_adder(d, w=None, op=None):
    r = d.rng
    w = w or r.choice([4, 8, 12, 16, 24, 32])
    op = op or r.choice(["add", "sub", "addconst", "addcin", "add3"])
    a, b = regs_ab(d, w)
    q = d.nm("s")
    if op == "add":
        e, cn, ex = f"{a} + {b}", {"adders": 1}, w + 1
    elif op == "sub":
        e, cn, ex = f"{a} - {b}", {"subtractors": 1}, w + 1
    elif op == "addconst":
        k = r.randrange(1, 1 << w)
        e, cn, ex = f"{a} + {w + 1}'d{k}", {"adders": 1}, w + 1
    elif op == "addcin":
        e, cn, ex = f"{a} + {b} + {d.stim1()}", {"adders": 1}, w + 1
    else:
        c3 = d.nm("c")
        d.decl.append(f"reg [{w - 1}:0] {c3};")
        d.body.append(f"always @(posedge clk) {c3} <= {d.stimx(w)};")
        e, cn, ex = f"{a} + {b} + {c3}", {"adders": 2}, w + 2
        cn["reg_bits"] = w
    d.decl.append(f"reg [{ex - 1}:0] {q};")
    d.body.append(f"always @(posedge clk) {q} <= {e};")
    cn["reg_bits"] = cn.get("reg_bits", 0) + 2 * w + ex
    d.T("subtractor" if op == "sub" else "adder", counts=cn, width=w, op=op)
    d.observe(q, ex)
    return q, ex


def p_cmp(d, w=None, op=None, signed=None):
    r = d.rng
    w = w or r.choice([4, 8, 12, 16, 24, 32])
    op = op or r.choice(["lt", "le", "gt", "ge", "eq", "ne"])
    signed = (r.random() < .3 and op in ("lt", "le", "gt", "ge")) if signed is None else signed
    a, b = regs_ab(d, w)
    q = d.nm("f")
    sym = {"lt": "<", "le": "<=", "gt": ">", "ge": ">=", "eq": "==", "ne": "!="}[op]
    e = f"$signed({a}) {sym} $signed({b})" if signed else f"{a} {sym} {b}"
    d.decl.append(f"reg {q};")
    d.body.append(f"always @(posedge clk) {q} <= {e};")
    mag = op in ("lt", "le", "gt", "ge")
    d.T("comparator" if mag else "equality", counts={"comparators": 1, "reg_bits": 2 * w + 1} if mag else {"reg_bits": 2 * w + 1}, width=w, op=op, signed=signed)
    d.observe(q, 1)
    return q, 1


def p_lfsr(d, w=None, scr=None, xor_form=None):
    r = d.rng
    w = w or r.choice([8, 9, 10, 12, 15, 16, 20, 24, 32, 40, 48, 64])
    scr = r.random() < .4 if scr is None else scr           # scrambler: serial data xored into the feedback
    c = d.nm("lf")
    d.decl.append(f"reg [{w - 1}:0] {c};")
    fb = " ^ ".join(f"{c}[{t - 1}]" for t in TAPS[w])
    din = f" ^ {d.stim1()}" if scr else ""
    d.body.append(f"always @(posedge clk) {c} <= {{{c}[{w - 2}:0], ~({fb}{din})}};")
    d.T("lfsr", counts={"shift_registers": 1, "reg_bits": w}, width=w, taps=TAPS[w], form="fibonacci_xnor", scrambler=scr)
    d.observe(c, w)
    return c, w


def p_shiftreg(d, w=None, kind=None):
    r = d.rng
    w = w or r.choice([4, 8, 12, 16, 24, 32, 48])
    kind = kind or r.choice(["sipo", "en", "load", "rot"])
    c = d.nm("sr")
    d.decl.append(f"reg [{w - 1}:0] {c};")
    if kind == "sipo":
        d.body.append(f"always @(posedge clk) {c} <= {{{c}[{w - 2}:0], {d.stim1()}}};")
    elif kind == "en":
        d.body.append(f"always @(posedge clk) if ({d.stim1()}) {c} <= {{{c}[{w - 2}:0], {d.stim1()}}};")
    elif kind == "load":
        d.body.append(f"always @(posedge clk) if ({d.stim1()} & {d.stim1()}) {c} <= {d.stim(w)}; else {c} <= {{{c}[{w - 2}:0], {d.stim1()}}};")
    else:
        d.body.append(f"always @(posedge clk) if ({d.stim1()} & {d.stim1()}) {c} <= {d.stim(w)}; else {c} <= {{{c}[{w - 2}:0], {c}[{w - 1}]}};")
    d.T("shift_register", counts={"shift_registers": 1, "reg_bits": w}, width=w, variant=kind)
    d.observe(c, w)
    return c, w


def p_crc(d, name=None, dw=None):
    r = d.rng
    name = name or r.choice(list(POLYS))
    w, poly = POLYS[name]
    dw = dw or r.choice([1, 8, 8, 16] if w >= 16 else [1, 8])
    c, f = d.nm("crc"), d.nm("crcf")
    d.decl += [f"reg [{w - 1}:0] {c};",
               f"function [{w - 1}:0] {f}(input [{w - 1}:0] cc, input [{dw - 1}:0] x);\n  integer i; reg [{w - 1}:0] rr;\n  begin\n    rr = cc;\n"
               f"    for (i = 0; i < {dw}; i = i + 1) rr = (rr[{w - 1}] ^ x[{dw - 1} - i]) ? ((rr << 1) ^ {w}'h{poly:X}) : (rr << 1);\n    {f} = rr;\n  end\nendfunction"]
    d.body.append(f"always @(posedge clk) if ({d.stim1()} & {d.stim1()} & {d.stim1()}) {c} <= {{{w}{{1'b1}}}}; else if ({d.stim1()}) {c} <= {f}({c}, {d.stim(dw)});")
    d.T("crc", counts={"reg_bits": w}, width=w, poly=f"0x{poly:X}", name=name, data_width=dw, bit_order="msb_first")
    d.observe(c, w)
    return c, w


def p_fsm(d, n=None, enc=None, ext=None):
    r = d.rng
    enc = enc or r.choice(["binary", "binary", "onehot", "gray"])
    n = n or (r.randint(3, 10) if enc == "onehot" else r.randint(3, 24))
    sw = n if enc == "onehot" else max(2, math.ceil(math.log2(n)))
    code = (lambda i: 1 << i) if enc == "onehot" else (lambda i: i ^ (i >> 1)) if enc == "gray" else (lambda i: i)
    st = d.nm("st")
    lp = [f"localparam [{sw - 1}:0] {st.upper()}_{i} = {sw}'d{code(i)};" for i in range(n)]
    cases, edges = [], 0
    for i in range(n):
        tgt = [(i + 1) % n] + [r.randrange(n) for _ in range(2)]
        g1, g2 = d.stim1(), d.stim1()
        if r.random() < .5:
            cases.append(f"  {st.upper()}_{i}: {st} <= {g1} ? {st.upper()}_{tgt[0]} : {st.upper()}_{tgt[1]};")
            edges += 2
        else:
            cases.append(f"  {st.upper()}_{i}: {st} <= {g1} ? {st.upper()}_{tgt[0]} : {g2} ? {st.upper()}_{tgt[1]} : {st.upper()}_{tgt[2]};")
            edges += 3
    rst = f"{d.stim1()} & {d.stim1()} & {d.stim1()}"
    d.decl += lp + [f"reg [{sw - 1}:0] {st};"]
    d.body.append(f"always @(posedge clk) begin\n if ({rst}) {st} <= {st.upper()}_0;\n else case ({st})\n" + "\n".join(cases) + f"\n  default: {st} <= {st.upper()}_0;\n endcase\nend")
    no = r.randint(1, 3)
    o = d.nm("fo")
    d.decl.append(f"reg [{no - 1}:0] {o};")
    terms = []
    for _ in range(no):
        sel = r.sample(range(n), r.randint(1, max(1, n // 2)))
        terms.append("(" + " | ".join(f"{st} == {st.upper()}_{i}" for i in sel) + ")")
    d.body.append(f"always @(posedge clk) {o} <= {{{', '.join(terms)}}};")
    d.qsf.append('set_global_assignment -name STATE_MACHINE_PROCESSING "USER-ENCODED"')
    d.T("fsm", counts={"fsms": 1, "reg_bits": sw + no}, states=n, encoding=enc, state_bits=sw, edges=edges, outputs=no, reset="sync")
    d.observe(st, sw)
    d.observe(o, no)
    return st, sw


def p_regs(d, w=None, en=None, sclr=None, sload=None, aclr=None):
    r = d.rng
    w = w or r.choice([4, 8, 16, 24, 32])
    en = r.random() < .6 if en is None else en
    sclr = r.random() < .4 if sclr is None else sclr
    sload = r.random() < .3 if sload is None else sload
    aclr = r.random() < .25 if aclr is None else aclr
    c = d.nm("rg")
    d.decl.append(f"reg [{w - 1}:0] {c};")
    ch = []
    if sclr:
        ch.append(f"if ({d.stim1()} & {d.stim1()}) {c} <= {{{w}{{1'b0}}}};")
    if sload:
        ch.append(f"{'else ' if ch else ''}if ({d.stim1()} & {d.stim1()}) {c} <= {d.stimx(w)};")
    ch.append(f"{'else ' if ch else ''}{'if (' + d.stim1() + ') ' if en else ''}{c} <= {d.stimx(w)};")
    if aclr:
        ar = d.nm("ar")
        d.decl.append(f"wire {ar} = {d.stim1()} & {d.stim1()} & {d.stim1()} & {d.stim1()};")
        d.body.append(f"always @(posedge clk or posedge {ar}) begin\n  if ({ar}) {c} <= {{{w}{{1'b0}}}};\n  else begin\n    " + "\n    ".join(ch) + "\n  end\nend")
    else:
        d.body.append("always @(posedge clk) begin\n  " + "\n  ".join(ch) + "\nend")
    d.T("register", counts={"reg_bits": w}, width=w, enable=en, sync_clear=sclr, sync_load=sload, async_clear=aclr)
    d.observe(c, w)
    return c, w


def p_mux(d, n=None, w=None, style=None):
    r = d.rng
    n = n or r.choice([2, 4, 8, 16])
    w = w or r.choice([1, 2, 4, 8])
    style = style or r.choice(["case", "tern", "index"])
    k = int(math.log2(n))
    sel = d.nm("sel")
    ins = [d.stimx(w) for _ in range(n)]
    q = d.nm("mx")
    d.decl += [f"wire [{k - 1}:0] {sel} = {d.stim(k)};", f"reg [{w - 1}:0] {q};"]
    if style == "case":
        d.body.append(f"always @(posedge clk) case ({sel})\n" + "\n".join(f"  {k}'d{i}: {q} <= {ins[i]};" for i in range(n)) + f"\n  default: {q} <= {{{w}{{1'b0}}}};\nendcase")
    elif style == "tern":
        e = ins[-1]
        for i in range(n - 2, -1, -1):
            e = f"({sel} == {k}'d{i}) ? {ins[i]} : {e}"
        d.body.append(f"always @(posedge clk) {q} <= {e};")
    else:
        v = d.nm("mv")
        d.decl.append(f"wire [{n * w - 1}:0] {v} = {{{', '.join(reversed(ins))}}};")
        d.body.append(f"always @(posedge clk) {q} <= {v}[{sel} * {w} +: {w}];")
    d.T("mux", counts={"muxes": 1, "reg_bits": w}, ways=n, width=w, style=style)
    d.observe(q, w)
    return q, w


def p_decoder(d, k=None):
    k = k or d.rng.randint(2, 5)
    q = d.nm("dc")
    d.decl.append(f"reg [{(1 << k) - 1}:0] {q};")
    d.body.append(f"always @(posedge clk) {q} <= {(1 << k)}'d1 << {d.stim(k)};")
    d.T("decoder", counts={"reg_bits": 1 << k}, select_bits=k)
    d.observe(q, 1 << k)
    return q, 1 << k


def p_prienc(d, n=None):
    n = n or d.rng.choice([4, 8, 16])
    k = int(math.log2(n))
    q, v = d.nm("pe"), d.nm("pv")
    req = d.stim(n)
    d.decl += [f"reg [{k - 1}:0] {q};", f"reg {v};"]
    d.body.append(f"always @(posedge clk) begin\n  {v} <= |{req};\n  casez ({req})\n" + "\n".join(
        f"    {n}'b" + "?" * (n - 1 - i) + "1" + "0" * i + f": {q} <= {k}'d{i};" for i in range(n)) + f"\n    default: {q} <= {k}'d0;\n  endcase\nend")
    d.T("prienc", counts={"reg_bits": k + 1}, inputs=n)
    d.observe(q, k)
    d.observe(v, 1)
    return q, k


def write_mif(d, name, depth, width):
    rr = random.Random(f"mif:{d.kind}:{d.seed}:{name}")
    lines = [f"WIDTH={width};", f"DEPTH={depth};", "ADDRESS_RADIX=HEX;", "DATA_RADIX=HEX;", "CONTENT BEGIN"]
    lines += [f"  {i:X} : {rr.getrandbits(width):0{(width + 3) // 4}X};" for i in range(depth)]
    lines.append("END;")
    d.files[name] = "\n".join(lines) + "\n"


def addr_src(d, aw):
    """address source: a private free-running counter (so every address is visited) -> (expr, truth side effect)."""
    a = d.nm("ad")
    d.decl.append(f"reg [{aw - 1}:0] {a};")
    d.body.append(f"always @(posedge clk) {a} <= {a} + {aw}'d1;")
    d.T("counter", counts={"counters": 1, "reg_bits": aw}, width=aw, mode="up", step=1, enable=False, load=False, clear=False, role_note="address")
    return a


def p_rom(d, aw=None, w=None, addr=None):
    r = d.rng
    aw = aw or r.choice([6, 7, 8, 9])
    w = w or r.choice([8, 9, 16, 18, 32])
    m, q = d.nm("rom"), d.nm("rq")
    fn = f"{m}.mif"
    write_mif(d, fn, 1 << aw, w)
    a = addr or addr_src(d, aw)
    d.decl += [f'(* romstyle = "M9K", ram_init_file = "../src/{fn}" *) reg [{w - 1}:0] {m} [0:{(1 << aw) - 1}];', f"reg [{w - 1}:0] {q};"]
    d.body.append(f"always @(posedge clk) {q} <= {m}[{a}];")
    d.T("rom", counts={"m9k": max(1, math.ceil((1 << aw) * w / 9216))}, depth=1 << aw, width=w, init=fn)
    d.observe(q, w)
    return q, w


def p_ram(d, kind=None, aw=None, w=None):
    r = d.rng
    kind = kind or r.choice(["sp", "sdp", "tdp"])
    aw = aw or r.choice([6, 7, 8, 9, 10])
    w = w or r.choice([8, 9, 16, 18, 32])
    m = d.nm("ram")
    d.decl.append(f'(* ramstyle = "M9K, no_rw_check" *) reg [{w - 1}:0] {m} [0:{(1 << aw) - 1}];')
    qs = []
    if kind == "sp":
        a, q = addr_src(d, aw), d.nm("rq")
        d.decl.append(f"reg [{w - 1}:0] {q};")
        d.body.append(f"always @(posedge clk) begin\n  if ({d.stim1()}) {m}[{a}] <= {d.stim(w)};\n  {q} <= {m}[{a}];\nend")
        qs = [q]
    elif kind == "sdp":
        wa, ra, q = addr_src(d, aw), addr_src(d, aw), d.nm("rq")
        d.decl.append(f"reg [{w - 1}:0] {q};")
        d.body.append(f"always @(posedge clk) begin\n  if ({d.stim1()}) {m}[{wa}] <= {d.stim(w)};\n  {q} <= {m}[{ra}];\nend")
        qs = [q]
    else:
        aa, ab, qa, qb = addr_src(d, aw), addr_src(d, aw), d.nm("rqa"), d.nm("rqb")
        d.decl.append(f"reg [{w - 1}:0] {qa}, {qb};")
        d.body.append(f"always @(posedge clk) begin\n  if ({d.stim1()}) {m}[{aa}] <= {d.stim(w)};\n  {qa} <= {m}[{aa}];\nend")
        d.body.append(f"always @(posedge clk) begin\n  if ({d.stim1()}) {m}[{ab}] <= {d.stim(w)};\n  {qb} <= {m}[{ab}];\nend")
        qs = [qa, qb]
    d.T("ram", counts={"m9k": max(1, math.ceil((1 << aw) * w / 9216))}, ports=kind, depth=1 << aw, width=w)
    for q in qs:
        d.observe(q, w)
    return qs[0], w


def p_fifo(d, aw=None, w=None):
    r = d.rng
    aw = aw or r.choice([4, 5, 6, 7, 8, 9])
    w = w or r.choice([8, 9, 16, 18, 32])
    m, wp, rp, cnt, q, fl, em = d.nm("fm"), d.nm("wp"), d.nm("rp"), d.nm("fc"), d.nm("fq"), d.nm("ff"), d.nm("fe")
    depth = 1 << aw
    wr, rd = d.nm("wr"), d.nm("rd")
    d.decl += [f'(* ramstyle = "M9K, no_rw_check" *) reg [{w - 1}:0] {m} [0:{depth - 1}];', f"reg [{aw - 1}:0] {wp}, {rp};", f"reg [{aw}:0] {cnt};",
               f"reg [{w - 1}:0] {q};", f"wire {fl} = ({cnt} == {aw + 1}'d{depth});", f"wire {em} = ({cnt} == {aw + 1}'d0);",
               f"wire {wr} = {d.stim1()} & ~{fl};", f"wire {rd} = {d.stim1()} & ~{em};"]
    d.body.append(f"always @(posedge clk) begin\n  if ({wr}) begin {m}[{wp}] <= {d.stim(w)}; {wp} <= {wp} + {aw}'d1; end\n  if ({rd}) begin {q} <= {m}[{rp}]; {rp} <= {rp} + {aw}'d1; end\n"
                  f"  {cnt} <= {cnt} + {{{{{aw}{{1'b0}}}}, {wr}}} - {{{{{aw}{{1'b0}}}}, {rd}}};\nend")
    d.T("fifo", counts={"m9k": max(1, math.ceil(depth * w / 9216)), "counters": 2, "reg_bits": 2 * aw + (aw + 1)}, depth=depth, width=w,
        parts=["ram", "counter:wptr", "counter:rptr", "updown_count", "equality:empty", "equality:full"])
    d.observe(q, w)
    d.observe(cnt, aw + 1)
    d.observe(wp, aw)
    d.observe(rp, aw)
    return q, w


def p_mac(d, wa=None, wb=None, signed=None, mode=None):
    r = d.rng
    wa = wa or r.choice([8, 9, 12, 16, 18])
    wb = wb or r.choice([8, 9, 12, 16, 18])
    signed = r.random() < .5 if signed is None else signed
    mode = mode or r.choice(["mult", "mult", "mac", "sop"])
    sg = "signed " if signed else ""
    a, b, p = d.nm("ma"), d.nm("mb"), d.nm("mp")
    d.decl += [f"reg {sg}[{wa - 1}:0] {a};", f"reg {sg}[{wb - 1}:0] {b};", f"reg {sg}[{wa + wb - 1}:0] {p};"]
    d.body.append(f"always @(posedge clk) begin {a} <= {d.stimx(wa)}; {b} <= {d.stimx(wb)}; end")
    nm = 1
    if mode == "mult":
        d.body.append(f"always @(posedge clk) {p} <= {a} * {b};")
        cn = {"mac": 1}
    elif mode == "mac":
        d.body.append(f"always @(posedge clk) {p} <= {p} + {a} * {b};")
        cn = {"mac": 1, "adders": 1, "reg_bits": wa + wb}
    else:
        a2, b2 = d.nm("ma"), d.nm("mb")
        d.decl += [f"reg {sg}[{wa - 1}:0] {a2};", f"reg {sg}[{wb - 1}:0] {b2};"]
        d.body.append(f"always @(posedge clk) begin {a2} <= {d.stimx(wa)}; {b2} <= {d.stimx(wb)}; {p} <= {a} * {b} + {a2} * {b2}; end")
        cn, nm = {"mac": 2, "adders": 1}, 2
    d.T("mac", counts=cn, wa=wa, wb=wb, signed=signed, mode=mode, mults=nm, absorbed_regs="operand/product registers inside the multiplier block")
    d.observe(p, wa + wb)
    return p, wa + wb


def p_pipe(d, stages=None, w=None):
    r = d.rng
    stages = stages or r.randint(2, 8)
    w = w or r.choice([4, 8, 16, 32])
    prev = d.nm("pi")
    d.decl.append(f"wire [{w - 1}:0] {prev} = {d.stimx(w)};")
    nadd = 0
    for i in range(stages):
        q = d.nm("pp")
        d.decl.append(f"reg [{w - 1}:0] {q};")
        f = r.choice(["xorc", "rot", "addc", "not", "mix"]) if nadd < 2 else r.choice(["xorc", "rot", "not", "mix"])
        e = {"xorc": f"{prev} ^ {w}'h{r.getrandbits(w):X}", "rot": f"{{{prev}[{w - 2}:0], {prev}[{w - 1}]}}", "addc": f"{prev} + {w}'d{r.randrange(1, 1 << w)}",
             "not": f"~{prev}", "mix": f"{prev} ^ {{{prev}[{w - 2}:0], {prev}[{w - 1}]}} ^ {{{prev}[{w - 3}:0], {prev}[{w - 1}:{w - 2}]}}" if w > 3 else prev}[f]
        nadd += f == "addc"
        d.body.append(f"always @(posedge clk) {q} <= {e};")
        prev = q
    d.T("pipeline", counts={"reg_bits": stages * w, "adders": nadd}, stages=stages, width=w, adders=nadd)
    d.observe(prev, w)
    return prev, w


# ---- composites -------------------------------------------------------------------------------------------------------------------
def c_cnt_cmp_fsm(d):
    """counter -> magnitude compare vs a register -> FSM whose state gates the counter."""
    r = d.rng
    w = r.choice([8, 12, 16])
    c, lim, f, st = d.nm("cnt"), d.nm("lim"), d.nm("cmp"), d.nm("st")
    d.decl += [f"reg [{w - 1}:0] {c}, {lim};", f"reg {f};", "localparam [1:0] RUN = 2'd0, HOLD = 2'd1, CLR = 2'd2, WAIT = 2'd3;", f"reg [1:0] {st};"]
    d.body.append(f"always @(posedge clk) {lim} <= {d.stimx(w)};")
    d.body.append(f"always @(posedge clk) {f} <= {c} >= {lim};")
    d.body.append(f"always @(posedge clk) case ({st})\n  RUN: {st} <= {f} ? HOLD : RUN;\n  HOLD: {st} <= {d.stim1()} ? CLR : WAIT;\n  CLR: {st} <= RUN;\n  WAIT: {st} <= {d.stim1()} ? RUN : WAIT;\nendcase")
    d.body.append(f"always @(posedge clk) if ({st} == CLR) {c} <= {{{w}{{1'b0}}}}; else if ({st} == RUN) {c} <= {c} + {w}'d1;")
    d.T("counter", counts={"counters": 1, "reg_bits": w}, width=w, mode="up", step=1, enable=True, load=False, clear=True)
    d.T("register", counts={"reg_bits": w}, width=w)
    d.T("comparator", counts={"comparators": 1, "reg_bits": 1}, width=w, op="ge", signed=False)
    d.T("fsm", counts={"fsms": 1, "reg_bits": 2}, states=4, encoding="binary", state_bits=2, edges=8, outputs=0, reset="none")
    d.qsf.append('set_global_assignment -name STATE_MACHINE_PROCESSING "USER-ENCODED"')
    for s_, ww in ((c, w), (st, 2), (f, 1)):
        d.observe(s_, ww)
    d.params["composite"] = "counter->comparator->fsm->counter"


def c_lfsr_acc(d):
    """LFSR word accumulated into a register; low bits compared."""
    r = d.rng
    w = r.choice([16, 24, 32])
    lf, _ = p_lfsr(d, w=w, scr=False)
    acc, f = d.nm("acc"), d.nm("lt")
    d.decl += [f"reg [{w - 1}:0] {acc};", f"reg {f};"]
    d.body.append(f"always @(posedge clk) {acc} <= {acc} + {lf};")
    d.body.append(f"always @(posedge clk) {f} <= {acc} < {lf};")
    d.T("adder", counts={"adders": 1, "reg_bits": w}, width=w, op="accumulate")
    d.T("comparator", counts={"comparators": 1, "reg_bits": 1}, width=w, op="lt", signed=False)
    d.observe(acc, w)
    d.observe(f, 1)
    d.params["composite"] = "lfsr->accumulator->comparator"


def c_fifo_sum(d):
    """counter data -> FIFO -> checksum adder on the read side."""
    r = d.rng
    aw, w = r.choice([5, 6, 7, 8]), r.choice([8, 16])
    cn, _ = p_counter(d, w=w, mode="up", en=False, ld=False, clr=False, step=1)
    q, _ = p_fifo(d, aw=aw, w=w)
    sm = d.nm("sum")
    d.decl.append(f"reg [{w + 3}:0] {sm};")
    d.body.append(f"always @(posedge clk) {sm} <= {sm} + {q};")
    d.T("adder", counts={"adders": 1, "reg_bits": w + 4}, width=w + 4, op="accumulate")
    d.observe(sm, w + 4)
    d.params["composite"] = "counter->fifo->checksum"


def c_cnt_crc(d):
    """counter -> CRC engine -> equality against a register."""
    cn, w = p_counter(d, w=8, mode="up", en=False, ld=False, clr=False, step=1)
    c, cw = p_crc(d, name=d.rng.choice(["crc8", "crc16ccitt"]), dw=8)
    d.params["composite"] = "counter, crc (independent stimulus)"


def c_shift_cmp_fsm(d):
    """serial shift register -> pattern compare (equality) -> FSM (sequence detector)."""
    r = d.rng
    w = r.choice([4, 6, 8])
    sr, hit, st = d.nm("sr"), d.nm("hit"), d.nm("sd")
    pat = r.getrandbits(w)
    d.decl += [f"reg [{w - 1}:0] {sr};", f"reg {hit};", "localparam [1:0] A = 2'd0, B = 2'd1, C = 2'd2;", f"reg [1:0] {st};"]
    d.body.append(f"always @(posedge clk) {sr} <= {{{sr}[{w - 2}:0], {d.stim1()}}};")
    d.body.append(f"always @(posedge clk) {hit} <= ({sr} == {w}'d{pat});")
    d.body.append(f"always @(posedge clk) case ({st})\n  A: {st} <= {hit} ? B : A;\n  B: {st} <= {hit} ? C : A;\n  C: {st} <= {d.stim1()} ? A : C;\n  default: {st} <= A;\nendcase")
    d.qsf.append('set_global_assignment -name STATE_MACHINE_PROCESSING "USER-ENCODED"')
    d.T("shift_register", counts={"shift_registers": 1, "reg_bits": w}, width=w, variant="sipo")
    d.T("equality", counts={"reg_bits": 1}, width=w, op="eq_const", const=pat)
    d.T("fsm", counts={"fsms": 1, "reg_bits": 2}, states=3, encoding="binary", state_bits=2, edges=6, outputs=0, reset="none")
    for s_, ww in ((sr, w), (hit, 1), (st, 2)):
        d.observe(s_, ww)
    d.params["composite"] = "shift register->pattern compare->fsm"


def c_dsp_chain(d):
    """MAC feeding an accumulator register bank with a down counter gate."""
    p, w = p_mac(d, wa=9, wb=9, signed=True, mode="mult")
    acc = d.nm("acc")
    d.decl.append(f"reg signed [{w + 3}:0] {acc};")
    d.body.append(f"always @(posedge clk) {acc} <= {acc} + {p};")
    d.T("adder", counts={"adders": 1, "reg_bits": w + 4}, width=w + 4, op="accumulate")
    p_counter(d, w=8, mode="down", en=False, ld=False, clr=False, step=1)
    d.observe(acc, w + 4)
    d.params["composite"] = "mac->accumulator + down counter"


COMPOSITES = [c_cnt_cmp_fsm, c_lfsr_acc, c_fifo_sum, c_cnt_crc, c_shift_cmp_fsm, c_dsp_chain]
PARTS = {"counter": p_counter, "adder": p_adder, "cmp": p_cmp, "lfsr": p_lfsr, "shiftreg": p_shiftreg, "crc": p_crc, "fsm": p_fsm, "regs": p_regs,
         "mux": p_mux, "decoder": p_decoder, "prienc": p_prienc, "rom": p_rom, "ram": p_ram, "fifo": p_fifo, "mac": p_mac, "pipe": p_pipe}


# ---- large designs ----------------------------------------------------------------------------------------------------------------
def big_regs(d):
    r = d.rng
    for _ in range(r.choice([20, 24])):
        p_regs(d, w=32, en=r.random() < .5, sclr=r.random() < .5, sload=r.random() < .4, aclr=False)
    for _ in range(4):
        p_lfsr(d, w=r.choice([32, 40, 48, 64]))
    d.params["resource"] = "registers (>= 600)"


def big_rom(d):
    n = d.rng.choice([60, 64])
    aw = 8
    a = addr_src(d, aw)
    for _ in range(n):
        p_rom(d, aw=aw, w=32, addr=a)
    d.params["resource"] = f"{n} M9K ROM, unique contents"


def big_mac(d):
    n = d.rng.choice([96, 120])
    for _ in range(n):
        p_mac(d, wa=18, wb=18, signed=True, mode="mult")
    d.params["resource"] = f"{n} 18x18 multipliers"


def big_add(d):
    for _ in range(24):
        p_adder(d, w=32, op=d.rng.choice(["add", "sub"]))
    for _ in range(12):
        p_cmp(d, w=32, op=d.rng.choice(["lt", "ge"]))
    d.params["resource"] = "36 wide arithmetic units"


def build_mix(d):
    r = d.rng
    for _ in range(r.randint(4, 12)):
        if r.random() < .25:
            r.choice(COMPOSITES)(d)
        else:
            PARTS[r.choice(["counter", "adder", "cmp", "lfsr", "shiftreg", "crc", "fsm", "regs", "mux", "pipe", "fifo", "ram", "mac"])](d)


def one_part(kind):
    return lambda d: PARTS[kind](d)


def multi(kind, lo, hi):
    return lambda d: [PARTS[kind](d) for _ in range(d.rng.randint(lo, hi))]


# kind -> (n designs, builder).  kind names are alphanumeric (design name hl_<kind>_<seed>).
PLAN = {"counter": (12, multi("counter", 1, 3)), "adder": (10, multi("adder", 1, 3)), "cmp": (8, multi("cmp", 1, 3)), "lfsr": (10, multi("lfsr", 1, 3)),
        "shiftreg": (6, multi("shiftreg", 1, 3)), "crc": (8, multi("crc", 1, 2)), "fsm": (14, multi("fsm", 1, 3)), "regs": (8, multi("regs", 2, 6)),
        "mux": (6, multi("mux", 1, 3)), "decoder": (3, multi("decoder", 1, 2)), "prienc": (3, multi("prienc", 1, 2)), "rom": (6, multi("rom", 1, 3)),
        "ram": (8, multi("ram", 1, 2)), "fifo": (8, multi("fifo", 1, 2)), "mac": (8, multi("mac", 1, 4)), "pipe": (5, multi("pipe", 1, 2)),
        "dpath": (10, lambda d: d.rng.choice(COMPOSITES)(d)), "mix": (14, build_mix),
        "bigregs": (2, big_regs), "bigrom": (2, big_rom), "bigmac": (1, big_mac), "bigadd": (1, big_add)}


def make(kind, seed, style="min", virtclk=False, builder=None):
    d = Design(kind, seed, style, virtclk)
    (builder or PLAN[kind][1])(d)
    return d


def expected(d):
    return dict(sorted(d.counts.items()))


def write_design(d, root):
    name = f"hl_{d.kind}_{d.seed}"
    p = Path(root) / name
    (p / "src").mkdir(parents=True, exist_ok=True)
    (p / "src" / "top.v").write_text(d.verilog())
    for fn, txt in d.files.items():
        (p / "src" / fn).write_text(txt)
    truth = dict(design=name, kind=d.kind, seed=d.seed, style=d.style, device=DEVICE, params=d.params, constructs=d.truth, expected=expected(d),
                 notes="expected = counts per lifter report key; roles: dut / stimulus (on-chip LFSR banks) / observer (output XOR)")
    (p / "src" / "hl_truth.json").write_text(json.dumps(truth, indent=1) + "\n")
    q = d.qsf_lines()
    ex = sorted({t["kind"] for t in d.truth if t["role"] == "dut"})
    toml = lambda xs: "[" + ", ".join(json.dumps(x) for x in xs) + "]"
    (p / "design.toml").write_text(f'top = "top"\npurpose = "highlevel: {d.kind} seed {d.seed} ({d.style} IO)"\nexercises = {toml(["highlevel", *ex])}\n'
                                   f"qsf = {toml(q)}\ndevice = \"{DEVICE}\"\n")
    return name


def generate(root, style="min"):
    names = []
    for kind, (n, _b) in PLAN.items():
        for seed in range(1, n + 1):
            names.append(write_design(make(kind, seed, style), root))
    return names


def lint(root, names):
    """iverilog parse of every generated top.v (syntax only)."""
    import heavy_guard
    bad = []
    for n in names:
        r = heavy_guard.guarded(["iverilog", "-g2012", "-o", os.devnull, str(Path(root) / n / "src" / "top.v")], "iverilog", log)
        if r.returncode:
            bad.append((n, r.stderr.strip()[:200]))
    return bad


def build(root, match, jobs, force, scale=1):
    import cycloneiv_fuzz as F
    import heavy_guard
    from concurrent.futures import ThreadPoolExecutor
    # overall backstops x scale: the 60 s stall guard (no output and no CPU) is primary; large designs (60 M9K, 100 multipliers) run longer than the small-design worst case
    F.OVERALL_S.update({k: v * scale for k, v in F.OVERALL_S.items()})
    root = Path(root).resolve()
    names = sorted(p.name for p in root.iterdir() if (p / "design.toml").exists() and fnmatch.fnmatch(p.name, match) and (force or not (p / "bitstream.rbf").exists()))
    log.info("%d designs to build under %s, %d jobs", len(names), root, jobs)
    bad = {}

    def one(n):
        F._tl.corpus = root
        F._tl.qtmp = REPO / "tmp" / "quartus_tmp"
        t0 = time.monotonic()
        with heavy_guard.lease(2.0, "hl_build", log):
            f = F.build_one(n)
        el = time.monotonic() - t0
        (root / n / "rebuild.json").write_text(json.dumps({"status": "ok" if f is None else f"failed:{f}", "attempts": 1, "elapsed_s": round(el, 1)}))
        log.info("%s: %s (%.1fs)", n, "ok" if f is None else f"FAIL at {f}", el)
        if f is None:
            fit_summary(root / n)
        else:
            bad[n] = f
    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(one, names))
    log.info("built %d, failed %d %s", len(names) - len(bad), len(bad), bad)
    return 1 if bad else 0


def fit_summary(d):
    """Quartus fit.rpt resource figures -> src/hl_truth.json['fit'] (what the tool built, next to what the source asked for)."""
    import re
    t = (d / "fit.rpt").read_text(errors="replace")

    def g(pat):
        m = re.search(pat, t)
        return int(m[1].replace(",", "")) if m else None
    fit = dict(logic_elements=g(r"Total logic elements\s*;\s*([\d,]+)"), registers=g(r"Total registers\s*;\s*([\d,]+)"), pins=g(r"Total pins\s*;\s*([\d,]+)"),
               virtual_pins=g(r"Total virtual pins\s*;\s*([\d,]+)"), m9k=g(r"M9Ks\s*;\s*([\d,]+)"), mult9=g(r"Embedded Multiplier 9-bit elements\s*;\s*([\d,]+)"),
               memory_bits=g(r"Total memory bits\s*;\s*([\d,]+)"))
    p = d / "src" / "hl_truth.json"
    j = json.loads(p.read_text())
    j["fit"] = fit
    p.write_text(json.dumps(j, indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--feasibility", action="store_true")
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--root", default=str(REPO / "corpus" / "cycloneiv"))
    ap.add_argument("--match", default="hl_*")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--style", default="min", choices=["min", "virt"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--scale", type=int, default=6, help="multiplier on the per-step overall backstops of cycloneiv_fuzz.OVERALL_S")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_hl_corpus.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    rc = 0
    if a.feasibility:
        root = REPO / "tmp" / "hlcorpus"
        names = []
        specs = [("counter", lambda d: p_counter(d, w=16, mode="up", en=True, ld=True, clr=True, step=1)),
                 ("fsm", lambda d: p_fsm(d, n=7, enc="binary")),
                 ("fifo", lambda d: p_fifo(d, aw=8, w=16))]
        for kind, b in specs:
            names.append(write_design(make(kind + "A", 1, "virt", False, b), root))     # A: all virtual (data ports); clock real
            names.append(write_design(make(kind + "Av", 1, "virt", True, b), root))     # A': clock virtual too
            names.append(write_design(make(kind + "B", 1, "min", False, b), root))      # B: minimal IO
        log.info("feasibility designs: %s; lint %s", names, lint(root, names))
    if a.generate:
        names = generate(a.root, a.style)
        bad = lint(a.root, names)
        log.info("generated %d designs into %s; iverilog lint failures %d %s", len(names), a.root, len(bad), bad[:5])
        rc = 1 if bad else 0
    if a.build:
        rc = build(a.root, a.match, a.jobs, a.force, a.scale) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
