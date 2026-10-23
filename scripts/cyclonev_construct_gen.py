#!/usr/bin/env python3
"""Generate the construct-dictionary designs into corpus/cyclonev/c_*/ (issue #104).

One design per (construct, variant, width).  Variants:
  v95  plain Verilog-95 (qsf VERILOG_INPUT_VERSION VERILOG_1995)
  vnd  Quartus-specific: lpm_*/altsyncram megafunctions or synthesis attributes
  sv   SystemVerilog (qsf VERILOG_INPUT_VERSION SYSTEMVERILOG_2005)
Names: c_<construct>_<variant>_<width>.  Output is deterministic; rerun is idempotent.
Skips (no vendor form): none; every construct has a vnd variant (lpm_* / attribute / pragma).
Usage: python3.15t scripts/cyclonev_construct_gen.py
Log: tmp/logs/cyclonev_construct_gen.log
"""
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus" / "cyclonev"
LOG = REPO / "tmp" / "logs" / "cyclonev_construct_gen.log"
WIDTHS = (1, 4, 8, 16)
log = logging.getLogger("construct_gen")

QSF_LANG = {"v95": "VERILOG_1995", "vnd": "VERILOG_2001", "sv": "SYSTEMVERILOG_2005"}
RAM_DEPTH_BITS = 6



def R(w):
    return f"[{w - 1}:0]"


# Each generator: fn(name, w) -> source text or None (skip reason via SKIP_REASON).
# Verilog-95 style: non-ANSI ports, explicit sensitivity lists.

def counter(v, n, w):
    if v == "v95":
        return (f"module {n} (clk, q);\n  input clk;\n  output {R(w)} q;\n  reg {R(w)} q;\n"
                f"  always @(posedge clk) q <= q + 1;\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (clk, q);\n  input clk;\n  output {R(w)} q;\n"
                f"  lpm_counter #(.lpm_width({w}), .lpm_direction(\"UP\")) u (.clock(clk), .q(q));\n"
                f"endmodule\n")
    return (f"module {n} (input logic clk, output logic {R(w)} q);\n"
            f"  always_ff @(posedge clk) q <= q + 1'b1;\nendmodule\n")


def updown(v, n, w):
    if v == "v95":
        return (f"module {n} (clk, up, q);\n  input clk, up;\n  output {R(w)} q;\n  reg {R(w)} q;\n"
                f"  always @(posedge clk) if (up) q <= q + 1; else q <= q - 1;\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (clk, up, q);\n  input clk, up;\n  output {R(w)} q;\n"
                f"  lpm_counter #(.lpm_width({w}), .lpm_direction(\"UNUSED\")) u "
                f"(.clock(clk), .updown(up), .q(q));\nendmodule\n")
    return (f"module {n} (input logic clk, input logic up, output logic {R(w)} q);\n"
            f"  always_ff @(posedge clk) q <= up ? q + 1'b1 : q - 1'b1;\nendmodule\n")


def adder(v, n, w):
    if v == "v95":
        return (f"module {n} (a, b, s);\n  input {R(w)} a, b;\n  output [{w}:0] s;\n"
                f"  assign s = {{1'b0, a}} + {{1'b0, b}};\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (a, b, s);\n  input {R(w)} a, b;\n  output [{w}:0] s;\n  wire {R(w)} r;\n  wire co;\n"
                f"  lpm_add_sub #(.lpm_width({w}), .lpm_direction(\"ADD\"), "
                f".lpm_representation(\"UNSIGNED\")) u (.dataa(a), .datab(b), .result(r), .cout(co));\n"
                f"  assign s = {{co, r}};\nendmodule\n")
    return (f"module {n} (input logic signed {R(w)} a, b, output logic signed [{w}:0] s);\n"
            f"  always_comb s = a + b;\nendmodule\n")


def subtractor(v, n, w):
    if v == "v95":
        return (f"module {n} (a, b, d);\n  input {R(w)} a, b;\n  output [{w}:0] d;\n"
                f"  assign d = {{1'b0, a}} - {{1'b0, b}};\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (a, b, d);\n  input {R(w)} a, b;\n  output [{w}:0] d;\n  wire {R(w)} r;\n  wire co;\n"
                f"  lpm_add_sub #(.lpm_width({w}), .lpm_direction(\"SUB\"), "
                f".lpm_representation(\"UNSIGNED\")) u (.dataa(a), .datab(b), .result(r), .cout(co));\n"
                f"  assign d = {{~co, r}};\nendmodule\n")
    return (f"module {n} (input logic signed {R(w)} a, b, output logic signed [{w}:0] d);\n"
            f"  always_comb d = a - b;\nendmodule\n")


def cmp_eq(v, n, w):
    if v == "v95":
        return (f"module {n} (a, b, y);\n  input {R(w)} a, b;\n  output y;\n"
                f"  assign y = (a == b);\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (a, b, y);\n  input {R(w)} a, b;\n  output y;\n"
                f"  lpm_compare #(.lpm_width({w}), .lpm_representation(\"UNSIGNED\")) u "
                f"(.dataa(a), .datab(b), .aeb(y));\nendmodule\n")
    return (f"module {n} (input logic {R(w)} a, b, output logic y);\n"
            f"  always_comb y = (a == b);\nendmodule\n")


def cmp_lt(v, n, w):
    if v == "v95":
        return (f"module {n} (a, b, y);\n  input {R(w)} a, b;\n  output y;\n"
                f"  assign y = (a < b);\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (a, b, y);\n  input {R(w)} a, b;\n  output y;\n"
                f"  lpm_compare #(.lpm_width({w}), .lpm_representation(\"UNSIGNED\")) u "
                f"(.dataa(a), .datab(b), .alb(y));\nendmodule\n")
    return (f"module {n} (input logic signed {R(w)} a, b, output logic y);\n"
            f"  always_comb y = (a < b);\nendmodule\n")


def mux2(v, n, w):
    if v == "v95":
        return (f"module {n} (a, b, s, y);\n  input {R(w)} a, b;\n  input s;\n  output {R(w)} y;\n"
                f"  assign y = s ? b : a;\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (a, b, s, y);\n  input {R(w)} a, b;\n  input s;\n  output {R(w)} y;\n"
                f"  lpm_mux #(.lpm_width({w}), .lpm_size(2), .lpm_widths(1)) u "
                f"(.data({{b, a}}), .sel(s), .result(y));\nendmodule\n")
    return (f"module {n} (input logic {R(w)} a, b, input logic s, output logic {R(w)} y);\n"
            f"  always_comb if (s) y = b; else y = a;\nendmodule\n")


def mux4(v, n, w):
    if v == "v95":
        return (f"module {n} (a, b, c, d, s, y);\n  input {R(w)} a, b, c, d;\n  input [1:0] s;\n"
                f"  output {R(w)} y;\n  assign y = s[1] ? (s[0] ? d : c) : (s[0] ? b : a);\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (a, b, c, d, s, y);\n  input {R(w)} a, b, c, d;\n  input [1:0] s;\n"
                f"  output {R(w)} y;\n  lpm_mux #(.lpm_width({w}), .lpm_size(4), .lpm_widths(2)) u "
                f"(.data({{d, c, b, a}}), .sel(s), .result(y));\nendmodule\n")
    return (f"module {n} (input logic {R(w)} a, b, c, d, input logic [1:0] s, output logic {R(w)} y);\n"
            f"  always_comb begin\n    unique case (s)\n      2'd0: y = a;\n      2'd1: y = b;\n"
            f"      2'd2: y = c;\n      2'd3: y = d;\n    endcase\n  end\nendmodule\n")


def casemux(v, n, w):
    """3 data inputs on a 2-bit select: select value 3 is unspecified."""
    z = f"{w}'d0"
    if v == "v95":
        return (f"module {n} (a, b, c, s, y);\n  input {R(w)} a, b, c;\n  input [1:0] s;\n"
                f"  output {R(w)} y;\n  reg {R(w)} y;\n  always @(a or b or c or s)\n    case (s)\n"
                f"      2'd0: y = a;\n      2'd1: y = b;\n      2'd2: y = c;\n      default: y = {z};\n"
                f"    endcase\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (a, b, c, s, y);\n  input {R(w)} a, b, c;\n  input [1:0] s;\n"
                f"  output {R(w)} y;\n  reg {R(w)} y;\n  always @(a or b or c or s)\n"
                f"    case (s) // synthesis full_case parallel_case\n"
                f"      2'd0: y = a;\n      2'd1: y = b;\n      2'd2: y = c;\n    endcase\nendmodule\n")
    return (f"module {n} (input logic {R(w)} a, b, c, input logic [1:0] s, output logic {R(w)} y);\n"
            f"  always_comb begin\n    case (s)\n      2'd0: y = a;\n      2'd1: y = b;\n"
            f"      2'd2: y = c;\n      default: y = '0;\n    endcase\n  end\nendmodule\n")


def decoder(v, n, s):
    nn = 2 ** s
    if v == "v95":
        return (f"module {n} (sel, y);\n  input {R(s)} sel;\n  output {R(nn)} y;\n"
                f"  assign y = 1 << sel;\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (sel, y);\n  input {R(s)} sel;\n  output {R(nn)} y;\n"
                f"  lpm_decode #(.lpm_width({s}), .lpm_decodes({nn})) u (.data(sel), .eq(y));\nendmodule\n")
    return (f"module {n} (input logic {R(s)} sel, output logic {R(nn)} y);\n"
            f"  always_comb begin\n    y = '0;\n    y[sel] = 1'b1;\n  end\nendmodule\n")


def shiftreg(v, n, w):
    if v == "v95":
        body = "q <= d;" if w == 1 else f"q <= {{q[{w - 2}:0], d}};"
        return (f"module {n} (clk, d, q);\n  input clk, d;\n  output {R(w)} q;\n  reg {R(w)} q;\n"
                f"  always @(posedge clk) {body}\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (clk, d, q);\n  input clk, d;\n  output {R(w)} q;\n"
                f"  lpm_shiftreg #(.lpm_width({w}), .lpm_direction(\"LEFT\")) u "
                f"(.clock(clk), .shiftin(d), .q(q));\nendmodule\n")
    return (f"module {n} (input logic clk, input logic d, output logic {R(w)} q);\n"
            f"  genvar i;\n  generate for (i = 0; i < {w}; i++) begin : g\n"
            f"    if (i == 0) begin : first\n      always_ff @(posedge clk) q[i] <= d;\n    end\n"
            f"    else begin : rest\n      always_ff @(posedge clk) q[i] <= q[i-1];\n    end\n"
            f"  end endgenerate\nendmodule\n")


def reg_en(v, n, w):
    if v == "v95":
        return (f"module {n} (clk, en, d, q);\n  input clk, en;\n  input {R(w)} d;\n  output {R(w)} q;\n"
                f"  reg {R(w)} q;\n  always @(posedge clk) if (en) q <= d;\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (clk, en, d, q);\n  input clk, en;\n  input {R(w)} d;\n  output {R(w)} q;\n"
                f"  lpm_ff #(.lpm_width({w})) u (.clock(clk), .enable(en), .data(d), .q(q));\nendmodule\n")
    return (f"module {n} (input logic clk, en, input logic {R(w)} d, output logic {R(w)} q);\n"
            f"  always_ff @(posedge clk) if (en) q <= d;\nendmodule\n")


def sync_reset(v, n, w):
    z = f"{w}'d0"
    if v == "v95":
        return (f"module {n} (clk, rst, d, q);\n  input clk, rst;\n  input {R(w)} d;\n  output {R(w)} q;\n"
                f"  reg {R(w)} q;\n  always @(posedge clk) if (rst) q <= {z}; else q <= d;\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (clk, rst, d, q);\n  input clk, rst;\n  input {R(w)} d;\n  output {R(w)} q;\n"
                f"  lpm_ff #(.lpm_width({w})) u (.clock(clk), .sclr(rst), .data(d), .q(q));\nendmodule\n")
    return (f"module {n} (input logic clk, rst, input logic {R(w)} d, output logic {R(w)} q);\n"
            f"  always_ff @(posedge clk) if (rst) q <= '0; else q <= d;\nendmodule\n")


def async_reset(v, n, w):
    z = f"{w}'d0"
    if v == "v95":
        return (f"module {n} (clk, rst, d, q);\n  input clk, rst;\n  input {R(w)} d;\n  output {R(w)} q;\n"
                f"  reg {R(w)} q;\n  always @(posedge clk or posedge rst)\n"
                f"    if (rst) q <= {z}; else q <= d;\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (clk, rst, d, q);\n  input clk, rst;\n  input {R(w)} d;\n  output {R(w)} q;\n"
                f"  lpm_ff #(.lpm_width({w})) u (.clock(clk), .aclr(rst), .data(d), .q(q));\nendmodule\n")
    return (f"module {n} (input logic clk, rst, input logic {R(w)} d, output logic {R(w)} q);\n"
            f"  always_ff @(posedge clk or posedge rst) if (rst) q <= '0; else q <= d;\nendmodule\n")


def comb(v, n, w):
    f = "((a & b) | (~a & c)) ^ (b | c)"
    if v == "v95":
        return (f"module {n} (a, b, c, y);\n  input {R(w)} a, b, c;\n  output {R(w)} y;\n"
                f"  assign y = {f};\nendmodule\n")
    if v == "vnd":
        return (f"module {n} (a, b, c, y);\n  input {R(w)} a, b, c;\n  output {R(w)} y;\n"
                f"  (* keep *) wire {R(w)} t1 = a & b;\n  (* keep *) wire {R(w)} t2 = ~a & c;\n"
                f"  (* keep *) wire {R(w)} t3 = t1 | t2;\n  (* keep *) wire {R(w)} t4 = b | c;\n"
                f"  assign y = t3 ^ t4;\nendmodule\n")
    return (f"module {n} (input logic {R(w)} a, b, c, output logic {R(w)} y);\n"
            f"  always_comb y = {f};\nendmodule\n")


def fsm(v, n, w, enc):
    """w = number of states.  Inputs go/alt, sync rst; outputs done (last state), odd."""
    nb = max(1, (w - 1).bit_length())
    width = w if enc == "oh" else nb
    names = [f"S{i}" for i in range(w)]
    val = {s: (f"{width}'b" + format(1 << i, f"0{width}b") if enc == "oh" else f"{width}'d{i}")
           for i, s in enumerate(names)}

    def nxt(i, ind):
        return (f"{ind}if (alt && {i % 2}) nx = S0;\n" if i % 2 else "") \
            + f"{ind}{'else ' if i % 2 else ''}if (go) nx = S{(i + 1) % w};\n{ind}else nx = S{i};\n"
    odd = " | ".join(f"(st == S{i})" for i in range(1, w, 2)) or "1'b0"
    if v == "sv":
        enum = ", ".join(f"{s} = {val[s]}" for s in names)
        cases = "".join(f"      S{i}: begin\n{nxt(i, '        ')}      end\n" for i in range(w))
        return (f"module {n} (input logic clk, rst, go, alt, output logic done, odd);\n"
                f"  typedef enum logic [{width - 1}:0] {{{enum}}} state_t;\n  state_t st, nx;\n"
                f"  always_comb begin\n    nx = S0;\n    case (st)\n{cases}      default: nx = S0;\n    endcase\n  end\n"
                f"  always_ff @(posedge clk) if (rst) st <= S0; else st <= nx;\n"
                f"  assign done = (st == S{w - 1});\n  assign odd = {odd};\nendmodule\n")
    attr = ""
    if v == "vnd":
        attr = f'(* syn_encoding = "{"one-hot" if enc == "oh" else "sequential"}" *) '
        width = nb          # vendor attribute re-encodes a plain binary-coded source
        val = {s: f"{width}'d{i}" for i, s in enumerate(names)}
    params = "".join(f"  parameter {s} = {val[s]};\n" for s in names)
    cases = "".join(f"      S{i}: begin\n{nxt(i, '        ')}      end\n" for i in range(w))
    return (f"module {n} (clk, rst, go, alt, done, odd);\n  input clk, rst, go, alt;\n  output done, odd;\n"
            f"{params}  {attr}reg {R(width)} st;\n  reg {R(width)} nx;\n"
            f"  always @(st or go or alt) begin\n    nx = S0;\n    case (st)\n{cases}      default: nx = S0;\n"
            f"    endcase\n  end\n  always @(posedge clk) if (rst) st <= S0; else st <= nx;\n"
            f"  assign done = (st == S{w - 1});\n  assign odd = {odd};\nendmodule\n")


def ram(v, n, w, style=None):
    ab = RAM_DEPTH_BITS
    depth = 2 ** ab
    if v == "altsyncram":
        return (f"module {n} (clk, we, waddr, raddr, din, dout);\n  input clk, we;\n"
                f"  input {R(ab)} waddr, raddr;\n  input {R(w)} din;\n  output {R(w)} dout;\n"
                f"  altsyncram #(.operation_mode(\"DUAL_PORT\"), .width_a({w}), .widthad_a({ab}), "
                f".numwords_a({depth}), .width_b({w}), .widthad_b({ab}), .numwords_b({depth}), "
                f".outdata_reg_b(\"UNREGISTERED\"), .address_reg_b(\"CLOCK0\"), "
                f".ram_block_type(\"AUTO\"), .intended_device_family(\"Cyclone V\"), "
                f".lpm_type(\"altsyncram\"), .power_up_uninitialized(\"FALSE\")) u "
                f"(.clock0(clk), .address_a(waddr), .data_a(din), .wren_a(we), "
                f".address_b(raddr), .q_b(dout));\nendmodule\n")
    attr = f'(* ramstyle = "{style}" *) ' if style else ""
    if v == "sv":
        return (f"module {n} (input logic clk, we, input logic {R(ab)} waddr, raddr, "
                f"input logic {R(w)} din, output logic {R(w)} dout);\n"
                f"  logic {R(w)} mem [0:{depth - 1}];\n  always_ff @(posedge clk) begin\n"
                f"    if (we) mem[waddr] <= din;\n    dout <= mem[raddr];\n  end\nendmodule\n")
    return (f"module {n} (clk, we, waddr, raddr, din, dout);\n  input clk, we;\n"
            f"  input {R(ab)} waddr, raddr;\n  input {R(w)} din;\n  output {R(w)} dout;\n"
            f"  reg {R(w)} dout;\n  {attr}reg {R(w)} mem [0:{depth - 1}];\n"
            f"  always @(posedge clk) begin\n    if (we) mem[waddr] <= din;\n    dout <= mem[raddr];\n"
            f"  end\nendmodule\n")


# construct -> (generator, widths, variants, purpose, exercises)
SIMPLE = {
    "counter": (counter, WIDTHS, "free-running up counter", ["counter", "carry"]),
    "updown": (updown, WIDTHS, "up/down counter", ["counter", "carry", "updown"]),
    "adder": (adder, WIDTHS, "a+b with carry out", ["adder", "carry"]),
    "subtractor": (subtractor, WIDTHS, "a-b with borrow bit", ["subtractor", "carry"]),
    "cmp_eq": (cmp_eq, WIDTHS, "equality comparator", ["comparator", "eq"]),
    "cmp_lt": (cmp_lt, WIDTHS, "less-than comparator", ["comparator", "lt"]),
    "mux2": (mux2, WIDTHS, "2:1 mux, ?: select", ["mux"]),
    "mux4": (mux4, WIDTHS, "4:1 mux", ["mux"]),
    "casemux": (casemux, WIDTHS, "case mux, 3 inputs on 2-bit select (value 3 unspecified)", ["mux", "case"]),
    "decoder": (decoder, (1, 2, 3, 4), "binary-to-one-hot decoder; width = select bits", ["decoder"]),
    "shiftreg": (shiftreg, WIDTHS, "serial-in parallel-out shift register", ["shiftreg", "dffeas"]),
    "reg_en": (reg_en, WIDTHS, "register with enable", ["dffeas", "ena"]),
    "sync_reset": (sync_reset, WIDTHS, "register with synchronous reset", ["dffeas", "sclr"]),
    "async_reset": (async_reset, WIDTHS, "register with asynchronous reset", ["dffeas", "aclr"]),
    "comb": (comb, WIDTHS, "pure combinational assign logic", ["lut", "comb"]),
}
VARIANT_NOTE = {"v95": "Verilog-95", "vnd": "vendor", "sv": "SystemVerilog"}


def toml(top, construct, variant, width, purpose, exercises, lang, extra_qsf=()):
    qsf = [f"set_global_assignment -name VERILOG_INPUT_VERSION {QSF_LANG[lang]}"] + list(extra_qsf)
    q = ", ".join('"%s"' % s for s in qsf)
    ex = ", ".join('"%s"' % s for s in exercises)
    return (f'top = "{top}"\npurpose = "{purpose}"\nexercises = [{ex}]\nqsf = [{q}]\n'
            f'construct = "{construct}"\nvariant = "{variant}"\nwidth = {width}\n')


def emit(construct, variant, width, text, purpose, exercises, lang, extra_qsf=()):
    name = f"c_{construct}_{variant}_{width}"
    d = CORPUS / name
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "src" / f"{name}.v").write_text(text)
    (d / "design.toml").write_text(
        toml(name, construct, variant, width, purpose, exercises, lang, extra_qsf))
    return name


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)])
    names = []
    for c, (fn, widths, purpose, ex) in SIMPLE.items():
        for v in ("v95", "vnd", "sv"):
            for w in widths:
                nm = f"c_{c}_{v}_{w}"
                text = fn(v, nm, w)
                names.append(emit(c, v, w, text, f"{purpose} [{VARIANT_NOTE[v]}]", ex, v))
    for states in (4, 8, 16):
        for enc in ("bin", "oh"):
            for v in ("v95", "vnd", "sv"):
                c = f"fsm_{enc}"
                nm = f"c_{c}_{v}_{states}"
                names.append(emit(c, v, states, fsm(v, nm, states, enc),
                                  f"{states}-state FSM, {'one-hot' if enc == 'oh' else 'binary'} "
                                  f"[{VARIANT_NOTE[v]}]", ["fsm", "dffeas"], v))
    ram_variants = [("v95", "v95", None), ("vnd_m10k", "vnd", "M10K"), ("vnd_mlab", "vnd", "MLAB"),
                    ("vnd_logic", "vnd", "logic"), ("vnd_altsyncram", "altsyncram", None),
                    ("sv", "sv", None)]
    for w in WIDTHS:
        for vname, kind, style in ram_variants:
            nm = f"c_ram_{vname}_{w}"
            lang = "v95" if kind == "v95" else ("sv" if kind == "sv" else "vnd")
            names.append(emit("ram", vname, w, ram(kind, nm, w, style),
                              f"64x{w} simple-dual-port RAM, registered read [{vname}]",
                              ["ram", "ram_block"], lang))
    log.info("generated %d designs", len(names))


if __name__ == "__main__":
    main()
