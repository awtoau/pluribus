#!/usr/bin/env python3.15t
"""Generate the MachXO2 construct dictionary sources (tracked): corpus/machxo2/constructs/<name>/{src,design.toml}.

Variants (names mirror corpus/cyclonev): v95 = plain Verilog-95; vnd = Lattice vendor feature
(synthesis attributes, primitive instantiation); sv = Verilog-2001/SystemVerilog features.
A construct with no vendor feature gets a SKIPPED entry in constructs/_skipped.json (one-line reason).
Outputs are registered / reduced to a parity bit when the port count would exceed the TQFP100 budget.

Usage: python3.15t scripts/machxo2_construct_gen.py
Log:   tmp/logs/machxo2_construct_gen.log
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "corpus", "machxo2", "constructs")
IO_BUDGET = 72  # TQFP100: ~79 usable I/O (brief); 72 leaves margin for clk + JTAG-shared pins
WIDTHS = (1, 4, 8, 16)
SKIPPED = {}


def rng(w):
    return f"[{w - 1}:0] " if w > 1 else ""


def decl(style, ports, name="top"):
    """Module header + port declarations. ports = (dir, name, width, is_reg)."""
    names = ", ".join(p[1] for p in ports)
    if style == "sv":
        items = []
        for d, n, w, r in ports:
            t = "logic " if (r or d == "output") else ""
            items.append(f"    {d} {t}{rng(w)}{n}")
        return f"module {name} (\n" + ",\n".join(items) + "\n);\n"
    if style == "vnd2001":
        items = [f"    {d}{' reg' if r else ''} {rng(w)}{n}" for d, n, w, r in ports]
        return f"module {name} (\n" + ",\n".join(items) + "\n);\n"
    lines = [f"module {name} ({names});"]
    for d, n, w, r in ports:
        lines.append(f"  {d} {rng(w)}{n};")
        if r:
            lines.append(f"  reg {rng(w)}{n};")
    return "\n".join(lines) + "\n"


def wrap_reduced(style, ports, core):
    """top = core + registered parity of all outputs (cuts I/O to inputs + 1)."""
    ins = [p for p in ports if p[0] == "input"]
    outs = [p for p in ports if p[0] == "output"]
    has_clk = any(p[1] == "clk" for p in ins)
    tports = ([("input", "clk", 1, False)] if not has_clk else []) + [
        (d, n, w, False) for d, n, w, r in ins] + [("output", "par", 1, True)]
    t = decl(style, tports)
    for d, n, w, r in outs:
        t += f"  wire {rng(w)}{n}_w;\n"
    conn = ", ".join(f".{p[1]}({p[1]})" for p in ins) + (", " if ins else "") + ", ".join(
        f".{n}({n}_w)" for d, n, w, r in outs)
    t += f"  core u0 ({conn});\n"
    red = " ^ ".join(f"(^{n}_w)" for d, n, w, r in outs)
    ff = "always_ff @(posedge clk)" if style == "sv" else "always @(posedge clk)"
    t += f"  {ff} par <= {red};\nendmodule\n"
    return core + "\n" + t


def finish(style, ports, body, pre="", core_name="top"):
    """Assemble module text; reduce I/O if over budget."""
    nbits = sum(p[2] for p in ports)
    red = nbits > IO_BUDGET
    if red:
        text = decl(style, ports, "core") + pre + body + "endmodule\n"
        text = wrap_reduced(style, ports, text)
    else:
        text = decl(style, ports, core_name) + pre + body + "endmodule\n"
    return text, red


def ffk(style):
    return "always_ff @(posedge clk)" if style == "sv" else "always @(posedge clk)"


# ---------------------------------------------------------------- constructs
# Each: f(w, v) -> (ports, body, pre) or None.   v in v95 | vnd | sv   (sv ANSI)
def st(v):
    return "sv" if v == "sv" else "v95"


def counter(w, v):
    ports = [("input", "clk", 1, False), ("input", "en", 1, False), ("output", "q", w, True)]
    if v == "vnd":
        return None  # replaced by ccu2d chain in vendor()
    return ports, f"  {ffk(v)} if (en) q <= q + 1'b1;\n", ""


def updown(w, v):
    ports = [("input", "clk", 1, False), ("input", "up", 1, False), ("output", "q", w, True)]
    if v == "vnd":
        SKIPPED["updown_vnd"] = "no Lattice-specific form: an up/down counter has no CCU2D template (the add/sub select needs per-bit INIT hand-derivation)"
        return None
    if v == "sv":
        return ports, "  always_ff @(posedge clk) q <= up ? q + 1'b1 : q - 1'b1;\n", ""
    return ports, "  always @(posedge clk) begin\n    if (up) q <= q + 1;\n    else q <= q - 1;\n  end\n", ""


def adder(w, v):
    ports = [("input", "clk", 1, False), ("input", "a", w, False), ("input", "b", w, False),
             ("output", "y", w + 1, True)]
    if v == "vnd":
        return None
    if v == "sv":
        return ports, f"  always_ff @(posedge clk) y <= {{1'b0, a}} + {{1'b0, b}};\n", ""
    return ports, f"  always @(posedge clk) y <= {{1'b0, a}} + {{1'b0, b}};\n", ""


def sub(w, v):
    ports = [("input", "clk", 1, False), ("input", "a", w, False), ("input", "b", w, False),
             ("output", "y", w + 1, True)]
    if v == "vnd":
        return None
    if v == "sv":
        return ports, f"  always_ff @(posedge clk) y <= {{1'b0, a}} - {{1'b0, b}};\n", ""
    return ports, f"  always @(posedge clk) y <= {{1'b0, a}} - {{1'b0, b}};\n", ""


def eq(w, v):
    ports = [("input", "clk", 1, False), ("input", "a", w, False), ("input", "b", w, False),
             ("output", "y", 1, True)]
    if v == "vnd":  # syn_keep on per-bit xnor nets
        pre = f"  (* syn_keep = 1 *) wire {rng(w)}x;\n"
        body = "  assign x = ~(a ^ b);\n  always @(posedge clk) y <= &x;\n"
        return ports, body, pre
    if v == "sv":
        return ports, "  always_ff @(posedge clk) y <= (a == b);\n", ""
    return ports, "  always @(posedge clk) y <= (a == b);\n", ""


def lt(w, v):
    sgn = v == "sv"
    ports = [("input", "clk", 1, False), ("input", "a", w, False), ("input", "b", w, False),
             ("output", "y", 1, True)]
    if v == "vnd":  # syn_keep on a-b borrow chain result
        pre = f"  (* syn_keep = 1 *) wire {rng(w + 1)}d;\n"
        body = "  assign d = {1'b0, a} - {1'b0, b};\n  always @(posedge clk) y <= d[%d];\n" % w
        return ports, body, pre
    if sgn:  # signed compare, SV
        pre = f"  logic signed {rng(w)}sa, sb;\n"
        body = "  assign sa = a;\n  assign sb = b;\n  always_ff @(posedge clk) y <= (sa < sb);\n"
        return ports, body, pre
    return ports, "  always @(posedge clk) y <= (a < b);\n", ""


def mux2(w, v):
    ports = [("input", "clk", 1, False), ("input", "a", w, False), ("input", "b", w, False),
             ("input", "s", 1, False), ("output", "y", w, True)]
    if v == "vnd":
        return None
    if v == "sv":
        return ports, "  always_ff @(posedge clk) y <= s ? b : a;\n", ""
    return ports, "  always @(posedge clk) y <= s ? b : a;\n", ""


def mux4(w, v):
    ports = [("input", "clk", 1, False)] + [("input", n, w, False) for n in "abcd"] + [
        ("input", "s", 2, False), ("output", "y", w, True)]
    if v == "vnd":
        return None
    if v == "sv":
        pre = f"  logic {rng(w)}m;\n"
        return ports, ("  always_comb begin\n    unique case (s)\n      2'd0: m = a;\n      2'd1: m = b;\n"
                       "      2'd2: m = c;\n      default: m = d;\n    endcase\n  end\n"
                       "  always_ff @(posedge clk) y <= m;\n"), pre
    return ports, "  always @(posedge clk) y <= s[1] ? (s[0] ? d : c) : (s[0] ? b : a);\n", ""


def casemux(w, v):
    ports = [("input", "clk", 1, False), ("input", "a", w, False), ("input", "b", w, False),
             ("input", "s", 2, False), ("output", "y", w, True)]
    if v == "vnd":
        SKIPPED["casemux_vnd"] = "no Lattice-specific form: a logic-op case mux has no attribute or primitive beyond the LUT4/PFUMX covered by mux2_vnd and mux4_vnd"
        return None
    case = ("    case (s)\n      2'd0: y <= a;\n      2'd1: y <= b;\n      2'd2: y <= a & b;\n"
            "      default: y <= a ^ b;\n    endcase\n")
    if v == "sv":
        return ports, "  always_ff @(posedge clk) begin\n" + case + "  end\n", ""
    return ports, "  always @(posedge clk) begin\n" + case + "  end\n", ""


def decoder(n, v):
    m = 1 << n
    ports = [("input", "clk", 1, False), ("input", "en", 1, False), ("input", "s", n, False),
             ("output", "y", m, True)]
    if v == "vnd":
        return None
    if v == "sv":
        return ports, f"  always_ff @(posedge clk) y <= en ? ({m}'d1 << s) : {m}'d0;\n", ""
    body = "  always @(posedge clk) begin\n    y <= 0;\n    if (en) y[s] <= 1'b1;\n  end\n"
    return ports, body, ""


def shiftreg(w, v):
    ports = [("input", "clk", 1, False), ("input", "din", 1, False), ("output", "q", w, True)]
    if v == "vnd":
        return None
    if w == 1:
        return ports, f"  {ffk(v)} q <= din;\n", ""
    if v == "sv":
        return ports, f"  always_ff @(posedge clk) q <= {{q[{w - 2}:0], din}};\n", ""
    return ports, f"  always @(posedge clk) q <= {{q[{w - 2}:0], din}};\n", ""


def regen(w, v):
    ports = [("input", "clk", 1, False), ("input", "en", 1, False), ("input", "d", w, False),
             ("output", "q", w, True)]
    if v == "vnd":
        return None
    return ports, f"  {ffk(v)} if (en) q <= d;\n", ""


def syncrst(w, v):
    ports = [("input", "clk", 1, False), ("input", "rst", 1, False), ("input", "d", w, False),
             ("output", "q", w, True)]
    if v == "vnd":
        return None
    return ports, f"  {ffk(v)} if (rst) q <= {w}'d0; else q <= d;\n", ""


def asyncrst(w, v):
    ports = [("input", "clk", 1, False), ("input", "rst", 1, False), ("input", "d", w, False),
             ("output", "q", w, True)]
    if v == "vnd":
        return None
    ff = "always_ff @(posedge clk or posedge rst)" if v == "sv" else "always @(posedge clk or posedge rst)"
    return ports, f"  {ff} if (rst) q <= {w}'d0; else q <= d;\n", ""


def comb(w, v):
    ports = [("input", "a", w, False), ("input", "b", w, False), ("input", "c", w, False),
             ("output", "y", w, False)]
    if v == "vnd":
        return None
    if v == "sv":
        pre = ""
        body = ("  for (genvar i = 0; i < %d; i++) begin : g\n    assign y[i] = (a[i] & b[i]) ^ (a[i] | c[i]);\n"
                "  end\n" % w)
        return ports, body, pre
    return ports, "  assign y = (a & b) ^ (a | c);\n", ""


def ram(w, v):
    ports = [("input", "clk", 1, False), ("input", "we", 1, False), ("input", "addr", 8, False),
             ("input", "din", w, False), ("output", "dout", w, True)]
    attr = '(* syn_ramstyle = "block_ram" *) ' if v == "vnd" else ""
    if v == "sv":
        pre = f"  {attr}logic {rng(w)}mem [0:255];\n"
        body = "  always_ff @(posedge clk) begin\n    if (we) mem[addr] <= din;\n    dout <= mem[addr];\n  end\n"
        return ports, body, pre
    pre = f"  {attr}reg {rng(w)}mem [0:255];\n"
    body = "  always @(posedge clk) begin\n    if (we) mem[addr] <= din;\n    dout <= mem[addr];\n  end\n"
    return ports, body, pre


def fsm(n, v, onehot):
    """n states: advance on go, return to 0 on abort; out = last state, busy = not idle."""
    ports = [("input", "clk", 1, False), ("input", "go", 1, False), ("input", "abort", 1, False),
             ("output", "last", 1, True), ("output", "busy", 1, True)]
    bits = n if onehot else max(1, (n - 1).bit_length())
    val = (lambda i: f"{bits}'d{1 << i}") if onehot else (lambda i: f"{bits}'d{i}")
    nxt = ("    if (abort) ns = %s;\n    else if (go) ns = %s;\n" )
    if v == "sv":
        names = ", ".join(f"S{i} = {val(i)}" for i in range(n))
        pre = f"  typedef enum logic [{bits - 1}:0] {{{names}}} state_t;\n  state_t st, ns;\n"
        cases = "".join(f"      S{i}: if (abort) ns = S0; else if (go) ns = S{(i + 1) % n};\n" for i in range(n))
        body = ("  always_comb begin\n    ns = st;\n    case (st)\n" + cases +
                "      default: ns = S0;\n    endcase\n  end\n"
                "  always_ff @(posedge clk) begin\n    st <= ns;\n    last <= (ns == S%d);\n    busy <= (ns != S0);\n  end\n" % (n - 1))
        return ports, body, pre
    attr = ""
    if v == "vnd":
        attr = '(* syn_encoding = "%s" *) ' % ("onehot" if onehot else "binary")
        coded = False  # vendor variant: attribute on a plainly coded state reg
    pre = "".join(f"  parameter S{i} = {val(i) if v != 'vnd' else '%d' % i};\n" for i in range(n))
    sw = bits if v != "vnd" else max(1, (n - 1).bit_length())
    pre += f"  {attr}reg [{sw - 1}:0] st;\n  reg [{sw - 1}:0] ns;\n"
    cases = "".join(f"      S{i}: if (abort) ns = S0; else if (go) ns = S{(i + 1) % n};\n" for i in range(n))
    body = ("  always @(st or go or abort) begin\n    ns = st;\n    case (st)\n" + cases +
            "      default: ns = S0;\n    endcase\n  end\n"
            "  always @(posedge clk) begin\n    st <= ns;\n    last <= (ns == S%d);\n    busy <= (ns != S0);\n  end\n" % (n - 1))
    return ports, body, pre


# ------------------------------------------------------------ vendor forms
def lut4_init(fn):
    v = 0
    for i in range(16):
        a, b, c, d = i & 1, (i >> 1) & 1, (i >> 2) & 1, (i >> 3) & 1
        v |= (fn(a, b, c, d) & 1) << i
    return f"16'h{v:04X}"


def vendor(kind, w):
    """Hand-built vendor-primitive designs. Returns (ports, body, pre) or None."""
    cl = ("input", "clk", 1, False)
    if kind in ("adder", "sub", "counter"):
        # CCU2D chain, 2 bits per CCU2D; INIT values from the LSE mapping of the plain build
        # (see docs/machxo2-construct-dictionary.md); CIN of the first is tied via INJECT/const.
        return carry_chain(kind, w, cl)
    if kind == "mux2":
        ports = [cl, ("input", "a", w, False), ("input", "b", w, False), ("input", "s", 1, False),
                 ("output", "y", w, True)]
        init = lut4_init(lambda a, b, c, d: b if c else a)  # A=a B=b C=s
        pre = f"  wire {rng(w)}m;\n"
        body = "".join(
            f"  LUT4 #(.INIT({init})) l{i} (.A(a[{i}]), .B(b[{i}]), .C(s), .D(1'b0), .Z(m[{i}]));\n" for i in range(w))
        body += "  always @(posedge clk) y <= m;\n"
        return ports, body, pre
    if kind == "mux4":
        ports = [cl] + [("input", n, w, False) for n in "abcd"] + [
            ("input", "s", 2, False), ("output", "y", w, True)]
        init = lut4_init(lambda a, b, c, d: b if c else a)  # A=in0 B=in1 C=s0
        pre = f"  wire {rng(w)}ma, mb, m;\n"
        body = ""
        for i in range(w):
            body += (f"  LUT4 #(.INIT({init})) la{i} (.A(a[{i}]), .B(b[{i}]), .C(s[0]), .D(1'b0), .Z(ma[{i}]));\n"
                     f"  LUT4 #(.INIT({init})) lb{i} (.A(c[{i}]), .B(d[{i}]), .C(s[0]), .D(1'b0), .Z(mb[{i}]));\n"
                     f"  PFUMX p{i} (.ALUT(mb[{i}]), .BLUT(ma[{i}]), .C0(s[1]), .Z(m[{i}]));\n")
        body += "  always @(posedge clk) y <= m;\n"
        return ports, body, pre
    if kind == "decoder":
        n = w
        m = 1 << n
        ports = [cl, ("input", "en", 1, False), ("input", "s", n, False), ("output", "y", m, True)]
        pre = f"  wire [{m - 1}:0] z;\n"
        body = ""
        for k in range(m):
            sel = lambda a, b, c, d, k=k: 1 if (a | (b << 1) | (c << 2)) == k and d else 0
            # LUT4 inputs A,B,C = s[0..2] (s padded), D = en; n <= 3 per LUT, n=4 uses two LUT4 + AND
            if n <= 3:
                init = lut4_init(lambda a, b, c, d, k=k: 1 if (((a | (b << 1) | (c << 2)) & (m - 1)) == k and d) else 0)
                pins = [f"s[{j}]" if j < n else "1'b0" for j in range(3)]
                if n == 1:
                    # unused address bits tied 0: only k values 0..1 are reachable
                    pass
                body += (f"  LUT4 #(.INIT({init})) l{k} (.A({pins[0]}), .B({pins[1]}), .C({pins[2]}), "
                         f".D(en), .Z(z[{k}]));\n")
            else:
                # 4 select bits + en = 5 inputs: LUT4 on s[2:0]+en splitting by s[3] via PFUMX
                init0 = lut4_init(lambda a, b, c, d, k=k: 1 if (((a | (b << 1) | (c << 2))) == (k & 7) and d and not (k >> 3)) else 0)
                init1 = lut4_init(lambda a, b, c, d, k=k: 1 if (((a | (b << 1) | (c << 2))) == (k & 7) and d and (k >> 3)) else 0)
                body += (f"  wire t0_{k}, t1_{k};\n"
                         f"  LUT4 #(.INIT({init0})) l0_{k} (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(t0_{k}));\n"
                         f"  LUT4 #(.INIT({init1})) l1_{k} (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(t1_{k}));\n"
                         f"  assign z[{k}] = t0_{k} | t1_{k};\n")
        body += "  always @(posedge clk) y <= z;\n"
        return ports, body, pre
    if kind == "comb":
        ports = [("input", "a", w, False), ("input", "b", w, False), ("input", "c", w, False),
                 ("output", "y", w, False)]
        init = lut4_init(lambda a, b, c, d: (a & b) ^ (a | c))
        body = "".join(
            f"  LUT4 #(.INIT({init})) l{i} (.A(a[{i}]), .B(b[{i}]), .C(c[{i}]), .D(1'b0), .Z(y[{i}]));\n" for i in range(w))
        return ports, body, ""
    if kind in ("shiftreg", "regen", "syncrst", "asyncrst"):
        return ff_prims(kind, w, cl)
    if kind == "dp8kc":
        return dp8kc(w, cl)
    raise KeyError(kind)


def carry_chain(kind, w, cl):
    """CCU2D chain. INIT0/INIT1 values below are the ones LSE emits for these functions (verified
    by the plain build's postpar.vo; see the dictionary)."""
    n2 = (w + 1) // 2
    if kind == "counter":
        ports = [cl, ("input", "en", 1, False), ("output", "q", w, True)]
        pre = f"  wire [{2 * n2}:0] c;\n  wire [{2 * n2 - 1}:0] s;\n  assign c[0] = 1'b0;\n"
        body = ""
        for k in range(n2):
            a0 = f"q[{2 * k}]"
            a1 = f"q[{2 * k + 1}]" if 2 * k + 1 < w else "1'b0"
            body += (f"  CCU2D #(.INIT0(16'h{CC['cnt'][0]}), .INIT1(16'h{CC['cnt'][1]}), .INJECT1_0(\"NO\"), .INJECT1_1(\"NO\")) u{k} "
                     f"(.A0({a0}), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1({a1}), .B1(1'b0), .C1(1'b0), .D1(1'b1), "
                     f".CIN({'1' + chr(39) + 'b1' if k == 0 else f'c[{k}]'}), .S0(s[{2 * k}]), .S1(s[{2 * k + 1}]), .COUT(c[{k + 1}]));\n")
        pre = f"  wire [{n2}:0] c;\n  wire [{2 * n2 - 1}:0] s;\n"
        body += f"  always @(posedge clk) if (en) q <= s[{w - 1}:0];\n"
        return ports, body, pre
    ports = [cl, ("input", "a", w, False), ("input", "b", w, False), ("output", "y", w + 1, True)]
    key = "add" if kind == "adder" else "sub"
    pre = f"  wire [{n2}:0] c;\n  wire [{2 * n2 + 1}:0] s;\n"
    body = ""
    for k in range(n2):
        def pin(x, i):
            return f"{x}[{i}]" if i < w else "1'b0"
        body += (f"  CCU2D #(.INIT0(16'h{CC[key][0]}), .INIT1(16'h{CC[key][1]}), .INJECT1_0(\"NO\"), .INJECT1_1(\"NO\")) u{k} "
                 f"(.A0({pin('a', 2 * k)}), .B0({pin('b', 2 * k)}), .C0(1'b0), .D0(1'b1), "
                 f".A1({pin('a', 2 * k + 1)}), .B1({pin('b', 2 * k + 1)}), .C1(1'b0), .D1(1'b1), "
                 f".CIN({'1' + chr(39) + 'b0' if k == 0 and key == 'add' else ('1' + chr(39) + 'b1' if k == 0 else f'c[{k}]')}), "
                 f".S0(s[{2 * k}]), .S1(s[{2 * k + 1}]), .COUT(c[{k + 1}]));\n")
    body += f"  always @(posedge clk) y <= {{c[{n2}], s[{w - 1}:0]}};\n"
    return ports, body, pre


# CCU2D INIT words (INIT0, INIT1) per function, filled from the LSE mapping of the plain builds.
CC = {"add": ("96AA", "96AA"), "sub": ("69AA", "69AA"), "cnt": ("96AA", "96AA")}


def ff_prims(kind, w, cl):
    if kind == "shiftreg":
        ports = [cl, ("input", "din", 1, False), ("output", "q", w, False)]
        body = "".join(
            f"  FD1S3AX #(.GSR(\"DISABLED\")) f{i} (.D({'din' if i == 0 else f'q[{i - 1}]'}), .CK(clk), .Q(q[{i}]));\n" for i in range(w))
        return ports, body, ""
    if kind == "regen":
        ports = [cl, ("input", "en", 1, False), ("input", "d", w, False), ("output", "q", w, False)]
        body = "".join(f"  FD1P3AX #(.GSR(\"DISABLED\")) f{i} (.D(d[{i}]), .SP(en), .CK(clk), .Q(q[{i}]));\n" for i in range(w))
        return ports, body, ""
    if kind == "syncrst":
        ports = [cl, ("input", "rst", 1, False), ("input", "d", w, False), ("output", "q", w, False)]
        body = "".join(f"  FD1P3IX #(.GSR(\"DISABLED\")) f{i} (.D(d[{i}]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[{i}]));\n" for i in range(w))
        return ports, body, ""
    ports = [cl, ("input", "rst", 1, False), ("input", "d", w, False), ("output", "q", w, False)]
    body = "".join(f"  FD1S3DX #(.GSR(\"DISABLED\")) f{i} (.D(d[{i}]), .CK(clk), .CD(rst), .Q(q[{i}]));\n" for i in range(w))
    return ports, body, ""


def dp8kc(w, cl):
    """DP8KC primitive, port A write / port B read, data width w in {1,4,9,18}."""
    aw = {1: 13, 4: 11, 9: 10, 18: 9}[w]
    ports = [cl, ("input", "we", 1, False), ("input", "wa", aw, False), ("input", "ra", aw, False),
             ("input", "din", w, False), ("output", "dout", w, False)]
    da = [f"din[{i}]" if i < w else "1'b0" for i in range(18)]
    ada = [f"wa[{i}]" if i < aw else "1'b0" for i in range(13)]
    adb = [f"ra[{i}]" if i < aw else "1'b0" for i in range(13)]
    dob = [f"dout[{i}]" if i < w else f"nc{i}" for i in range(18)]
    pre = "".join(f"  wire nc{i};\n" for i in range(w, 18))
    pins = ", ".join([f".DIA{i}({da[i]})" for i in range(18)] + [f".DIB{i}(1'b0)" for i in range(18)] +
                     [f".ADA{i}({ada[i]})" for i in range(13)] + [f".ADB{i}({adb[i]})" for i in range(13)] +
                     [f".DOB{i}({dob[i]})" for i in range(18)])
    body = (f"  DP8KC #(.DATA_WIDTH_A({w}), .DATA_WIDTH_B({w}), .REGMODE_A(\"NOREG\"), .REGMODE_B(\"NOREG\"), "
            f".CSDECODE_A(\"0b000\"), .CSDECODE_B(\"0b000\"), .WRITEMODE_A(\"NORMAL\"), .WRITEMODE_B(\"NORMAL\"), "
            f".GSR(\"DISABLED\")) u0 (.CEA(1'b1), .CLKA(clk), .WEA(we), .CSA0(1'b0), .CSA1(1'b0), .CSA2(1'b0), .RSTA(1'b0), "
            f".CEB(1'b1), .CLKB(clk), .WEB(1'b0), .CSB0(1'b0), .CSB1(1'b0), .CSB2(1'b0), .RSTB(1'b0), {pins});\n")
    return ports, body, pre


# ------------------------------------------------------------------- driver
def emit(name, construct, variant, width, purpose, spec, lang, extra=None):
    ports, body, pre = spec
    style = "sv" if variant == "sv" else "v95"
    text, red = finish(style, ports, body, pre)
    d = os.path.join(OUT, name)
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    ext = "sv" if variant == "sv" else "v"
    for old in os.listdir(os.path.join(d, "src")):
        os.remove(os.path.join(d, "src", old))
    with open(os.path.join(d, "src", f"top.{ext}"), "w") as fh:
        fh.write(text)
    io = sum(p[2] for p in ports) if not red else sum(p[2] for p in ports if p[0] == "input") + 1
    with open(os.path.join(d, "design.toml"), "w") as fh:
        fh.write(f'top = "top"\npurpose = "{purpose}"\nconstruct = "{construct}"\nvariant = "{variant}"\n'
                 f'width = {width}\nlang = "{lang}"\nio_bits = {io}\nio_reduced = {str(red).lower()}\n')
    return name


def main():
    os.makedirs(OUT, exist_ok=True)
    names = []
    simple = [("counter", counter, WIDTHS, "up counter with enable"),
              ("updown", updown, WIDTHS, "up/down counter"),
              ("adder", adder, WIDTHS, "a+b with carry out, registered"),
              ("sub", sub, WIDTHS, "a-b with borrow, registered"),
              ("eq", eq, WIDTHS, "equality comparator, registered"),
              ("lt", lt, WIDTHS, "less-than comparator, registered (signed in sv)"),
              ("mux2", mux2, WIDTHS, "2:1 mux, registered"),
              ("mux4", mux4, WIDTHS, "4:1 mux, registered"),
              ("casemux", casemux, WIDTHS, "case mux with logic-op arms, registered"),
              ("shiftreg", shiftreg, WIDTHS, "serial-in parallel-out shift register"),
              ("regen", regen, WIDTHS, "register with enable"),
              ("syncrst", syncrst, WIDTHS, "register with sync reset"),
              ("asyncrst", asyncrst, WIDTHS, "register with async reset"),
              ("comb", comb, WIDTHS, "combinational assign logic"),
              ("ram", ram, WIDTHS, "inferred 256-deep sync-read RAM"),
              ("decoder", decoder, (1, 2, 3, 4), "decoder with enable (width = select bits)")]
    vend_ok = {"counter", "adder", "sub", "mux2", "mux4", "decoder", "comb", "shiftreg", "regen",
               "syncrst", "asyncrst"}
    for cons, fn, widths, purpose in simple:
        for v in ("v95", "vnd", "sv"):
            for w in widths:
                name = f"{cons}_{v}_{w}"
                lang = {"v95": "verilog-95", "vnd": "verilog-95+lattice", "sv": "systemverilog"}[v]
                if v == "vnd":
                    if cons in vend_ok:
                        spec = vendor(cons, w)
                    else:
                        spec = fn(w, v)
                        if spec is None:
                            continue
                else:
                    spec = fn(w, v)
                if spec is None:
                    continue
                if v == "vnd" and cons in ("eq", "lt", "ram"):
                    pass
                names.append(emit(name, cons, v, w, purpose, spec, lang))
    for enc, onehot in (("bin", False), ("oh", True)):
        for n in (4, 8, 16):
            for v in ("v95", "vnd", "sv"):
                spec = fsm(n, v, onehot)
                lang = {"v95": "verilog-95", "vnd": "verilog-95+lattice", "sv": "systemverilog"}[v]
                names.append(emit(f"fsm{enc}_{v}_{n}", f"fsm_{enc}", v, n,
                                  f"{n}-state FSM, {'one-hot' if onehot else 'binary'} encoding", spec, lang))
    for w in (1, 4, 9, 18):
        names.append(emit(f"dp8kc_vnd_{w}", "dp8kc", "vnd", w,
                          "DP8KC primitive, A write / B read", vendor("dp8kc", w), "verilog-95+lattice"))
    with open(os.path.join(OUT, "_skipped.json"), "w") as fh:
        json.dump(SKIPPED, fh, indent=1, sort_keys=True)
    print(f"{len(names)} designs, skipped {SKIPPED}")
    return names


if __name__ == "__main__":
    main()
