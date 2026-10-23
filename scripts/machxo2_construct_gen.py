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


FORCE_VEC = False  # vendor designs index bit-selects even at width 1


def rng(w):
    return f"[{w - 1}:0] " if (w > 1 or FORCE_VEC) else ""


def decl(style, ports, name="top"):
    """Module header + port declarations. ports = (dir, name, width, is_reg)."""
    names = ", ".join(p[1] for p in ports)
    if style == "v01":
        style = "vnd2001"
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
    t += f"  always @(posedge clk) par <= {red};\nendmodule\n"
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


# ---------------------------------------------------------------- constructs
# Each: f(w, v) -> (ports, body, pre) or None.   v in v95 | vnd | v01 (Verilog-2001: ANSI ports,
# generate, signed, always @*, localparam).  vnd bodies for most constructs come from vendor().
CL = ("input", "clk", 1, False)
FF = "always @(posedge clk)"


def counter(w, v):
    ports = [CL, ("input", "en", 1, False), ("output", "q", w, True)]
    if v == "vnd":
        return None
    return ports, f"  {FF} if (en) q <= q + 1'b1;\n", ""


def updown(w, v):
    ports = [CL, ("input", "up", 1, False), ("output", "q", w, True)]
    if v == "vnd":
        SKIPPED["updown_vnd"] = "no Lattice-specific form: an up/down counter has no CCU2D template (the add/sub select needs per-bit INIT hand-derivation)"
        return None
    if v == "v01":
        return ports, f"  {FF} q <= up ? q + 1'b1 : q - 1'b1;\n", ""
    return ports, f"  {FF} begin\n    if (up) q <= q + 1;\n    else q <= q - 1;\n  end\n", ""


def adder(w, v):
    ports = [CL, ("input", "a", w, False), ("input", "b", w, False), ("output", "y", w + 1, True)]
    if v == "vnd":
        return None
    if v == "v01":  # generate-for ripple of full adders
        pre = f"  wire [{w}:0] c;\n  wire [{w - 1}:0] s;\n  assign c[0] = 1'b0;\n"
        body = (f"  genvar i;\n  generate for (i = 0; i < {w}; i = i + 1) begin : fa\n"
                "    assign s[i] = a[i] ^ b[i] ^ c[i];\n    assign c[i+1] = (a[i] & b[i]) | (c[i] & (a[i] ^ b[i]));\n"
                f"  end endgenerate\n  {FF} y <= {{c[{w}], s}};\n")
        return ports, body, pre
    return ports, f"  {FF} y <= {{1'b0, a}} + {{1'b0, b}};\n", ""


def sub(w, v):
    ports = [CL, ("input", "a", w, False), ("input", "b", w, False), ("output", "y", w + 1, True)]
    if v == "vnd":
        return None
    if v == "v01":  # signed operands
        pre = f"  wire signed [{w}:0] sa = $signed({{1'b0, a}});\n  wire signed [{w}:0] sb = $signed({{1'b0, b}});\n"
        return ports, f"  {FF} y <= sa - sb;\n", pre
    return ports, f"  {FF} y <= {{1'b0, a}} - {{1'b0, b}};\n", ""


def eq(w, v):
    ports = [CL, ("input", "a", w, False), ("input", "b", w, False), ("output", "y", 1, True)]
    if v == "vnd":  # syn_keep on per-bit xnor nets
        pre = f"  (* syn_keep = 1 *) wire {rng(w)}x;\n"
        return ports, f"  assign x = ~(a ^ b);\n  {FF} y <= &x;\n", pre
    if v == "v01":
        pre = f"  wire [{w - 1}:0] x;\n"
        body = (f"  genvar i;\n  generate for (i = 0; i < {w}; i = i + 1) begin : gb\n"
                f"    assign x[i] = ~(a[i] ^ b[i]);\n  end endgenerate\n  {FF} y <= &x;\n")
        return ports, body, pre
    return ports, f"  {FF} y <= (a == b);\n", ""


def lt(w, v):
    ports = [CL, ("input", "a", w, False), ("input", "b", w, False), ("output", "y", 1, True)]
    if v == "vnd":  # syn_keep on a-b borrow result
        pre = f"  (* syn_keep = 1 *) wire {rng(w + 1)}d;\n"
        return ports, f"  assign d = {{1'b0, a}} - {{1'b0, b}};\n  {FF} y <= d[{w}];\n", pre
    if v == "v01":  # signed compare
        pre = f"  wire signed [{w - 1}:0] sa = a;\n  wire signed [{w - 1}:0] sb = b;\n"
        return ports, f"  {FF} y <= (sa < sb);\n", pre
    return ports, f"  {FF} y <= (a < b);\n", ""


def mux2(w, v):
    ports = [CL, ("input", "a", w, False), ("input", "b", w, False), ("input", "s", 1, False),
             ("output", "y", w, True)]
    if v == "vnd":
        return None
    if v == "v01":
        pre = f"  wire [{w - 1}:0] m;\n"
        body = (f"  genvar i;\n  generate for (i = 0; i < {w}; i = i + 1) begin : g\n"
                f"    assign m[i] = s ? b[i] : a[i];\n  end endgenerate\n  {FF} y <= m;\n")
        return ports, body, pre
    return ports, f"  {FF} y <= s ? b : a;\n", ""


def mux4(w, v):
    ports = [CL] + [("input", n, w, False) for n in "abcd"] + [("input", "s", 2, False), ("output", "y", w, True)]
    if v == "vnd":
        return None
    if v == "v01":
        pre = f"  reg [{w - 1}:0] m;\n"
        body = ("  always @* begin\n    case (s)\n      2'd0: m = a;\n      2'd1: m = b;\n      2'd2: m = c;\n"
                f"      default: m = d;\n    endcase\n  end\n  {FF} y <= m;\n")
        return ports, body, pre
    return ports, f"  {FF} y <= s[1] ? (s[0] ? d : c) : (s[0] ? b : a);\n", ""


def casemux(w, v):
    ports = [CL, ("input", "a", w, False), ("input", "b", w, False), ("input", "s", 2, False),
             ("output", "y", w, True)]
    if v == "vnd":
        SKIPPED["casemux_vnd"] = "no Lattice-specific form: a logic-op case mux has no attribute or primitive beyond the LUT4/PFUMX covered by mux2_vnd and mux4_vnd"
        return None
    case = ("    case (s)\n      2'd0: y <= a;\n      2'd1: y <= b;\n      2'd2: y <= a & b;\n"
            "      default: y <= a ^ b;\n    endcase\n")
    if v == "v01":  # combinational always @* then register
        pre = f"  reg [{w - 1}:0] m;\n"
        body = ("  always @* begin\n    case (s)\n      2'd0: m = a;\n      2'd1: m = b;\n      2'd2: m = a & b;\n"
                f"      default: m = a ^ b;\n    endcase\n  end\n  {FF} y <= m;\n")
        return ports, body, pre
    return ports, f"  {FF} begin\n" + case + "  end\n", ""


def decoder(n, v):
    m = 1 << n
    ports = [CL, ("input", "en", 1, False), ("input", "s", n, False), ("output", "y", m, True)]
    if v == "vnd":
        return None
    if v == "v01":
        pre = f"  localparam M = {m};\n"
        return ports, f"  {FF} y <= en ? ({m}'d1 << s) : {m}'d0;\n", pre
    return ports, f"  {FF} begin\n    y <= 0;\n    if (en) y[s] <= 1'b1;\n  end\n", ""


def shiftreg(w, v):
    ports = [CL, ("input", "din", 1, False), ("output", "q", w, True)]
    if v == "vnd":
        return None
    if w == 1:
        return ports, f"  {FF} q <= din;\n", ""
    if v == "v01":
        body = (f"  genvar i;\n  generate for (i = 1; i < {w}; i = i + 1) begin : st\n"
                f"    {FF} q[i] <= q[i-1];\n  end endgenerate\n  {FF} q[0] <= din;\n")
        return ports, body, ""
    return ports, f"  {FF} q <= {{q[{w - 2}:0], din}};\n", ""


def regen(w, v):
    ports = [CL, ("input", "en", 1, False), ("input", "d", w, False), ("output", "q", w, True)]
    if v == "vnd":
        return None
    return ports, f"  {FF} if (en) q <= d;\n", ""


def syncrst(w, v):
    ports = [CL, ("input", "rst", 1, False), ("input", "d", w, False), ("output", "q", w, True)]
    if v == "vnd":
        return None
    return ports, f"  {FF} if (rst) q <= {w}'d0; else q <= d;\n", ""


def asyncrst(w, v):
    ports = [CL, ("input", "rst", 1, False), ("input", "d", w, False), ("output", "q", w, True)]
    if v == "vnd":
        return None
    return ports, f"  always @(posedge clk or posedge rst) if (rst) q <= {w}'d0; else q <= d;\n", ""


def comb(w, v):
    ports = [("input", "a", w, False), ("input", "b", w, False), ("input", "c", w, False), ("output", "y", w, False)]
    if v == "vnd":
        return None
    if v == "v01":
        body = (f"  genvar i;\n  generate for (i = 0; i < {w}; i = i + 1) begin : g\n"
                "    assign y[i] = (a[i] & b[i]) ^ (a[i] | c[i]);\n  end endgenerate\n")
        return ports, body, ""
    return ports, "  assign y = (a & b) ^ (a | c);\n", ""


def ram(w, v):
    ports = [CL, ("input", "we", 1, False), ("input", "addr", 8, False), ("input", "din", w, False),
             ("output", "dout", w, True)]
    attr = '(* syn_ramstyle = "block_ram" *) ' if v == "vnd" else ""
    pre = f"  {attr}reg {rng(w)}mem [0:255];\n"
    body = f"  {FF} begin\n    if (we) mem[addr] <= din;\n    dout <= mem[addr];\n  end\n"
    if v == "v01":
        pre = f"  localparam DEPTH = 256;\n  reg {rng(w)}mem [0:DEPTH-1];\n"
    return ports, body, pre


def fsm(n, v, onehot):
    """n states: advance on go, return to 0 on abort; last = in last state, busy = not idle."""
    ports = [CL, ("input", "go", 1, False), ("input", "abort", 1, False),
             ("output", "last", 1, True), ("output", "busy", 1, True)]
    bits = n if onehot else max(1, (n - 1).bit_length())
    val = (lambda i: f"{bits}'d{1 << i}") if onehot else (lambda i: f"{bits}'d{i}")
    attr = ""
    if v == "vnd":
        attr = '(* syn_encoding = "%s" *) ' % ("onehot" if onehot else "binary")
        sw = max(1, (n - 1).bit_length())  # vendor variant: attribute on a plainly binary-coded reg
        vals = [f"{sw}'d{i}" for i in range(n)]
    else:
        sw, vals = bits, [val(i) for i in range(n)]
    kw = "localparam" if v == "v01" else "parameter"
    pre = "".join(f"  {kw} S{i} = {vals[i]};\n" for i in range(n))
    pre += f"  {attr}reg [{sw - 1}:0] st;\n  reg [{sw - 1}:0] ns;\n"
    cases = "".join(f"      S{i}: if (abort) ns = S0; else if (go) ns = S{(i + 1) % n};\n" for i in range(n))
    sens = "@*" if v == "v01" else "@(st or go or abort)"
    body = (f"  always {sens} begin\n    ns = st;\n    case (st)\n" + cases +
            "      default: ns = S0;\n    endcase\n  end\n"
            f"  {FF} begin\n    st <= ns;\n    last <= (ns == S{n - 1});\n    busy <= (ns != S0);\n  end\n")
    return ports, body, pre


# SystemVerilog feature probes: each tiny, built as top.v (Diamond rejects .sv in prj_src add).
PROBES = {
    "logic_port": "module top (input clk, input d, output logic q);\n  always @(posedge clk) q <= d;\nendmodule\n",
    "logic_var": "module top (input clk, input d, output reg q);\n  logic t;\n  always @(posedge clk) begin t <= d; q <= t; end\nendmodule\n",
    "always_ff": "module top (input clk, input d, output reg q);\n  always_ff @(posedge clk) q <= d;\nendmodule\n",
    "always_comb": "module top (input a, input b, output reg y);\n  always_comb y = a & b;\nendmodule\n",
    "enum_typedef": "module top (input clk, input go, output reg q);\n  typedef enum reg [1:0] {A=0, B=1, C=2} st_t;\n  st_t st;\n  always @(posedge clk) begin if (go) st <= B; q <= (st == B); end\nendmodule\n",
    "enum_inline": "module top (input clk, input go, output reg q);\n  enum reg [1:0] {A=0, B=1} st;\n  always @(posedge clk) begin if (go) st <= B; q <= (st == B); end\nendmodule\n",
    "genvar_in_for": "module top (input [3:0] a, output [3:0] y);\n  for (genvar i = 0; i < 4; i++) begin : g\n    assign y[i] = ~a[i];\n  end\nendmodule\n",
    "int_loop": "module top (input [3:0] a, output reg [3:0] y);\n  always @* for (int i = 0; i < 4; i++) y[i] = ~a[i];\nendmodule\n",
    "unique_case": "module top (input [1:0] s, input a, b, output reg y);\n  always @* unique case (s)\n    2'd0: y = a;\n    default: y = b;\n  endcase\nendmodule\n",
    "increment_op": "module top (input clk, output reg [3:0] q);\n  always @(posedge clk) q++;\nendmodule\n",
    "compound_assign": "module top (input clk, input [3:0] d, output reg [3:0] q);\n  always @(posedge clk) q += d;\nendmodule\n",
    "dollar_clog2": "module top (input clk, input d, output reg q);\n  localparam W = $clog2(10);\n  reg [W-1:0] r;\n  always @(posedge clk) begin r <= {W{d}}; q <= r[0]; end\nendmodule\n",
    "struct_packed": "module top (input clk, input [1:0] d, output reg q);\n  typedef struct packed { logic a; logic b; } s_t;\n  s_t s;\n  always @(posedge clk) begin s <= d; q <= s.a; end\nendmodule\n",
    "ansi_ports_v01": "module top (input clk, input [3:0] a, output reg [3:0] q);\n  always @(posedge clk) q <= a;\nendmodule\n",
    "signed_arith": "module top (input clk, input signed [3:0] a, input signed [3:0] b, output reg y);\n  always @(posedge clk) y <= a < b;\nendmodule\n",
    "generate_if": "module top (input clk, input d, output reg q);\n  parameter P = 1;\n  generate if (P) begin : g\n    always @(posedge clk) q <= d;\n  end else begin : h\n    always @(posedge clk) q <= ~d;\n  end endgenerate\nendmodule\n",
    "localparam_func": "module top (input clk, input [3:0] a, output reg [3:0] q);\n  function [3:0] inv(input [3:0] x); inv = ~x; endfunction\n  always @(posedge clk) q <= inv(a);\nendmodule\n",
}


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
            f"  LUT4 #(.init({init})) l{i} (.A(a[{i}]), .B(b[{i}]), .C(s), .D(1'b0), .Z(m[{i}]));\n" for i in range(w))
        body += "  always @(posedge clk) y <= m;\n"
        return ports, body, pre
    if kind == "mux4":
        ports = [cl] + [("input", n, w, False) for n in "abcd"] + [
            ("input", "s", 2, False), ("output", "y", w, True)]
        init = lut4_init(lambda a, b, c, d: b if c else a)  # A=in0 B=in1 C=s0
        pre = f"  wire {rng(w)}ma, mb, m;\n"
        body = ""
        for i in range(w):
            body += (f"  LUT4 #(.init({init})) la{i} (.A(a[{i}]), .B(b[{i}]), .C(s[0]), .D(1'b0), .Z(ma[{i}]));\n"
                     f"  LUT4 #(.init({init})) lb{i} (.A(c[{i}]), .B(d[{i}]), .C(s[0]), .D(1'b0), .Z(mb[{i}]));\n"
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
                body += (f"  LUT4 #(.init({init})) l{k} (.A({pins[0]}), .B({pins[1]}), .C({pins[2]}), "
                         f".D(en), .Z(z[{k}]));\n")
            else:
                # 4 select bits + en = 5 inputs: LUT4 on s[2:0]+en splitting by s[3] via PFUMX
                init0 = lut4_init(lambda a, b, c, d, k=k: 1 if (((a | (b << 1) | (c << 2))) == (k & 7) and d and not (k >> 3)) else 0)
                init1 = lut4_init(lambda a, b, c, d, k=k: 1 if (((a | (b << 1) | (c << 2))) == (k & 7) and d and (k >> 3)) else 0)
                body += (f"  wire t0_{k}, t1_{k};\n"
                         f"  LUT4 #(.init({init0})) l0_{k} (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(t0_{k}));\n"
                         f"  LUT4 #(.init({init1})) l1_{k} (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(t1_{k}));\n"
                         f"  assign z[{k}] = t0_{k} | t1_{k};\n")
        body += "  always @(posedge clk) y <= z;\n"
        return ports, body, pre
    if kind == "comb":
        ports = [("input", "a", w, False), ("input", "b", w, False), ("input", "c", w, False),
                 ("output", "y", w, False)]
        init = lut4_init(lambda a, b, c, d: (a & b) ^ (a | c))
        body = "".join(
            f"  LUT4 #(.init({init})) l{i} (.A(a[{i}]), .B(b[{i}]), .C(c[{i}]), .D(1'b0), .Z(y[{i}]));\n" for i in range(w))
        return ports, body, ""
    if kind in ("shiftreg", "regen", "syncrst", "asyncrst"):
        return ff_prims(kind, w, cl)
    if kind == "dp8kc":
        return dp8kc(w, cl)
    raise KeyError(kind)


def carry_chain(kind, w, cl):
    """CCU2D chain in the form LSE emits (INIT words and cell layout read from the plain builds'
    impl1/top_prim.v: counter F000/0555 + FAAA, add 7000/5666, sub 0000/5999). Not simulated."""
    g = "1'b0"

    def op(x, i):
        return f"{x}[{i}]" if i < w else g

    def cell(k, a0, b0, a1, b1, i0, i1, cin, cout, s0, s1):
        return (f"  CCU2D #(.INIT0(16'h{i0}), .INIT1(16'h{i1}), .INJECT1_0(\"NO\"), .INJECT1_1(\"NO\")) u{k} "
                f"(.A0({a0}), .B0({b0}), .C0({g}), .D0({g}), .A1({a1}), .B1({b1}), .C1({g}), .D1({g}), "
                f"{('.CIN(' + cin + '), ') if cin else ''}.COUT({cout}), .S0({s0}), .S1({s1}));\n")
    if kind == "counter":
        n = 1 + (w) // 2          # cell 0 = bit 0, cell k = bits 2k-1, 2k
        ports = [cl, ("input", "en", 1, False), ("output", "q", w, True)]
        pre = f"  wire [{n}:0] c;\n  wire [{2 * n}:0] s;\n"
        body = cell(0, g, g, "q[0]", g, "F000", "0555", None, "c[1]", "s[2*0]", "s[0]").replace("s[2*0]", "nc0")
        pre += "  wire nc0;\n"
        for k in range(1, n):
            body += cell(k, op("q", 2 * k - 1), g, op("q", 2 * k), g, "FAAA", "FAAA", f"c[{k}]", f"c[{k + 1}]",
                         f"s[{2 * k - 1}]", f"s[{2 * k}]")
        body += f"  always @(posedge clk) if (en) q <= s[{w - 1}:0];\n"
        return ports, body, pre
    ports = [cl, ("input", "a", w, False), ("input", "b", w, False), ("output", "y", w + 1, True)]
    if kind == "adder":
        n = (w - 1 + 1) // 2 + 1
        pre = f"  wire [{n}:0] c;\n  wire [{2 * n + 1}:0] s;\n  wire nc0;\n  wire y0 = a[0] ^ b[0];\n"
        body = cell(0, "a[0]", "b[0]", op("a", 1), op("b", 1), "7000", "5666", None, "c[1]", "nc0", "s[1]")
        for k in range(1, n):
            body += cell(k, op("a", 2 * k), op("b", 2 * k), op("a", 2 * k + 1), op("b", 2 * k + 1), "5666", "5666",
                         f"c[{k}]", f"c[{k + 1}]", f"s[{2 * k}]", f"s[{2 * k + 1}]")
        body += f"  always @(posedge clk) y <= {{s[{w}:1], y0}};\n"
        return ports, body, pre
    n = (w + 1) // 2 + 1
    pre = f"  wire [{n}:0] c;\n  wire [{2 * n + 1}:0] s;\n  wire nc0;\n"
    body = cell(0, g, g, "a[0]", "b[0]", "0000", "5999", None, "c[1]", "nc0", "s[0]")
    for k in range(1, n):
        body += cell(k, op("a", 2 * k - 1), op("b", 2 * k - 1), op("a", 2 * k), op("b", 2 * k), "5999", "5999",
                     f"c[{k}]", f"c[{k + 1}]", f"s[{2 * k - 1}]", f"s[{2 * k}]")
    body += f"  always @(posedge clk) y <= s[{w}:0];\n"
    return ports, body, pre


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
    """DP8KC primitive, port A write / port B read, data width w in {1,4,9}; 9-bit data ports."""
    aw = {1: 13, 4: 11, 9: 10}[w]
    sh = 13 - aw
    ports = [cl, ("input", "we", 1, False), ("input", "wa", aw, False), ("input", "ra", aw, False),
             ("input", "din", w, False), ("output", "dout", w, False)]
    da = [f"din[{i}]" if i < w else "1'b0" for i in range(9)]
    ada = [f"wa[{i - sh}]" if i >= sh else "1'b0" for i in range(13)]
    adb = [f"ra[{i - sh}]" if i >= sh else "1'b0" for i in range(13)]
    dob = [f"dout[{i}]" if i < w else f"nc{i}" for i in range(9)]
    doa = [f"nca{i}" for i in range(9)]
    pre = "".join(f"  wire nc{i};\n" for i in range(w, 9)) + "".join(f"  wire nca{i};\n" for i in range(9))
    pins = ", ".join([f".DIA{i}({da[i]})" for i in range(9)] + [f".DIB{i}(1'b0)" for i in range(9)] +
                     [f".ADA{i}({ada[i]})" for i in range(13)] + [f".ADB{i}({adb[i]})" for i in range(13)] +
                     [f".DOA{i}({doa[i]})" for i in range(9)] + [f".DOB{i}({dob[i]})" for i in range(9)])
    body = (f"  DP8KC #(.DATA_WIDTH_A({w}), .DATA_WIDTH_B({w}), .REGMODE_A(\"NOREG\"), .REGMODE_B(\"NOREG\"), "
            f".CSDECODE_A(\"0b000\"), .CSDECODE_B(\"0b000\"), .WRITEMODE_A(\"NORMAL\"), .WRITEMODE_B(\"NORMAL\"), "
            f".GSR(\"DISABLED\")) u0 (.CEA(1'b1), .OCEA(1'b1), .CLKA(clk), .WEA(we), .CSA0(1'b0), .CSA1(1'b0), .CSA2(1'b0), "
            f".RSTA(1'b0), .CEB(1'b1), .OCEB(1'b1), .CLKB(clk), .WEB(1'b0), .CSB0(1'b0), .CSB1(1'b0), .CSB2(1'b0), "
            f".RSTB(1'b0), {pins});\n")
    return ports, body, pre


# ------------------------------------------------------------------- driver
LANG = {"v95": "verilog-95", "vnd": "verilog-95+lattice", "v01": "verilog-2001"}


def write_src(name, text, ext="v"):
    d = os.path.join(OUT, name)
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    tgt = os.path.join(d, "src", f"top.{ext}")
    for old in os.listdir(os.path.join(d, "src")):
        if os.path.join(d, "src", old) != tgt:
            os.remove(os.path.join(d, "src", old))
    if not (os.path.exists(tgt) and open(tgt).read() == text):  # keep mtime when unchanged (resumable builds)
        with open(tgt, "w") as fh:
            fh.write(text)
    return d


def write_toml(d, **kv):
    with open(os.path.join(d, "design.toml"), "w") as fh:
        fh.write('top = "top"\n')
        for k, v in kv.items():
            fh.write(f"{k} = {str(v).lower() if isinstance(v, bool) else json.dumps(v)}\n")


def emit(name, construct, variant, width, purpose, spec, lang, ext="v"):
    ports, body, pre = spec
    text, red = finish("v01" if variant == "v01" else "v95", ports, body, pre)
    d = write_src(name, text, ext)
    io = sum(p[2] for p in ports) if not red else sum(p[2] for p in ports if p[0] == "input") + 1
    write_toml(d, purpose=purpose, construct=construct, variant=variant, width=width, lang=lang,
               io_bits=io, io_reduced=red)
    return name


def main():
    global FORCE_VEC
    os.makedirs(OUT, exist_ok=True)
    names = []
    simple = [("counter", counter, WIDTHS, "up counter with enable"),
              ("updown", updown, WIDTHS, "up/down counter"),
              ("adder", adder, WIDTHS, "a+b with carry out, registered"),
              ("sub", sub, WIDTHS, "a-b with borrow, registered"),
              ("eq", eq, WIDTHS, "equality comparator, registered"),
              ("lt", lt, WIDTHS, "less-than comparator, registered (signed in v01)"),
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
        for v in ("v95", "vnd", "v01"):
            for w in widths:
                FORCE_VEC = v in ("vnd", "v01")
                spec = vendor(cons, w) if (v == "vnd" and cons in vend_ok) else fn(w, v)
                if spec is not None:
                    names.append(emit(f"{cons}_{v}_{w}", cons, v, w, purpose, spec, LANG[v]))
                FORCE_VEC = False
    for enc, onehot in (("bin", False), ("oh", True)):
        for n in (4, 8, 16):
            for v in ("v95", "vnd", "v01"):
                FORCE_VEC = v in ("vnd", "v01")
                names.append(emit(f"fsm{enc}_{v}_{n}", f"fsm_{enc}", v, n,
                                  f"{n}-state FSM, {'one-hot' if onehot else 'binary'} encoding",
                                  fsm(n, v, onehot), LANG[v]))
                FORCE_VEC = False
    FORCE_VEC = True
    for w in (1, 4, 9):
        names.append(emit(f"dp8kc_vnd_{w}", "dp8kc", "vnd", w, "DP8KC primitive, A write / B read",
                          vendor("dp8kc", w), LANG["vnd"]))
    FORCE_VEC = False
    for k, text in PROBES.items():
        d = write_src(f"probe_{k}", text)
        write_toml(d, purpose=f"SystemVerilog feature probe: {k}", construct="probe", variant="sv", width=0,
                   lang="systemverilog-in-.v", feature=k, io_bits=0, io_reduced=False)
        names.append(f"probe_{k}")
    d = write_src("probe_sv_extension", PROBES["always_ff"], "sv")
    write_toml(d, purpose="SystemVerilog source named top.sv (project-level)", construct="probe", variant="sv",
               width=0, lang="systemverilog", feature="sv_extension", io_bits=0, io_reduced=False)
    names.append("probe_sv_extension")
    with open(os.path.join(OUT, "_skipped.json"), "w") as fh:
        json.dump(SKIPPED, fh, indent=1, sort_keys=True)
    import shutil
    for n in os.listdir(OUT):  # drop designs of earlier generator revisions
        if os.path.isdir(os.path.join(OUT, n)) and n not in names:
            shutil.rmtree(os.path.join(OUT, n))
    print(f"{len(names)} designs, skipped {list(SKIPPED)}")
    return names


if __name__ == "__main__":
    main()
