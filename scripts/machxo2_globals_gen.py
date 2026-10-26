#!/usr/bin/env python3.15t
"""Generate MachXO2 designs that exercise the global network the fuzz corpus never uses (#109).

Real designs use several global clocks (spine tracks 0100/0200, `G_VPTX01xx`+) and global
control nets (`G_HSBX`, `JCE0`/`JLSR0` fed from the secondary network); the old corpus has one
clock per design and low-fanout control. Build with:

    python3.15t scripts/machxo2_globals_gen.py
    python3.15t scripts/machxo2_construct_build.py --dir corpus/machxo2/globals

Designs (all LCMXO2-1200HC-5TG100C, pads LOCATEd):
  pll3dom      EHXPLLJ CLKOP/CLKOS/CLKOS2 -> 3 clock domains, shared high-fanout sync reset + CE
  clk4pad      4 clock pads -> 4 domains (4 primary tracks), shared high-fanout reset + CE
  hsctl        1 clock pad, 3 control nets of fanout >100 (CE, sync reset, async reset)
  pll3dom_x    as pll3dom but domains cross (domain A registers feed domain B)
"""
import os
import sys

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "corpus", "machxo2", "globals")

PINS = iter([48, 30, 77, 84, 47, 49, 51, 52, 53, 54, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70,
             71, 74, 75, 76, 78, 81, 82, 83, 85, 86, 87, 96, 97, 98, 99, 1, 2, 3, 4, 7, 8, 9, 10])

PLL = """
wire gnd = 1'b0, vcc = 1'b1;
wire clkop_w, clkos_w, clkos2_w, lock_w, intlock_w, refclk_w, clkintfb_w;
EHXPLLJ #(.CLKI_DIV(1), .CLKFB_DIV(1), .CLKOP_DIV(1), .CLKOP_ENABLE("ENABLED"),
    .FEEDBK_PATH("CLKOP"), .CLKOS_DIV(4), .CLKOS_ENABLE("ENABLED"),
    .CLKOS2_DIV(2), .CLKOS2_ENABLE("ENABLED"), .CLKOS3_ENABLE("DISABLED")) u0 (
    .CLKI(clk), .CLKFB(clkop_w), .RST(gnd), .STDBY(gnd), .PLLWAKESYNC(gnd),
    .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd), .PHASESTEP(gnd), .LOADREG(gnd),
    .RESETM(gnd), .RESETC(gnd), .RESETD(gnd), .ENCLKOP(vcc), .ENCLKOS(vcc), .ENCLKOS2(vcc),
    .ENCLKOS3(gnd), .PLLCLK(gnd), .PLLRST(gnd), .PLLSTB(gnd), .PLLWE(gnd),
    .PLLADDR4(gnd), .PLLADDR3(gnd), .PLLADDR2(gnd), .PLLADDR1(gnd), .PLLADDR0(gnd),
    .PLLDATI7(gnd), .PLLDATI6(gnd), .PLLDATI5(gnd), .PLLDATI4(gnd),
    .PLLDATI3(gnd), .PLLDATI2(gnd), .PLLDATI1(gnd), .PLLDATI0(gnd),
    .CLKOP(clkop_w), .CLKOS(clkos_w), .CLKOS2(clkos2_w), .LOCK(lock_w), .INTLOCK(intlock_w),
    .REFCLK(refclk_w), .CLKINTFB(clkintfb_w));
"""


def shift(name, clk, n, din, ctl):
    """n-bit shift register with sync reset + CE: every FF reads `rst`/`ce` (fanout n each)."""
    return (f"reg [{n-1}:0] {name};\n"
            f"always @(posedge {clk}) if (rst) {name} <= 0; else if (ce) {name} <= {{{name}[{n-2}:0], {din}}};\n")


def design(kind):
    pins = []
    ports = []

    def inp(n):
        ports.append(f"input wire {n}")
        pins.append((n, next(PINS)))

    def outp(n):
        ports.append(f"output wire {n}")
        pins.append((n, next(PINS)))

    pins.append(("clk", 88))
    ports.append("input wire clk")
    body = ""
    if kind in ("pll3dom", "pll3dom_x"):
        inp("rst"); inp("ce"); inp("d"); outp("q")
        body += PLL
        body += shift("ra", "clkop_w", 120, "d", None)
        body += shift("rb", "clkos_w", 120, "ra[119]" if kind == "pll3dom_x" else "d", None)
        body += shift("rc", "clkos2_w", 120, "rb[119]" if kind == "pll3dom_x" else "d", None)
        body += "reg qr; always @(posedge clk) qr <= ^{ra[119], rb[119], rc[119]};\nassign q = qr;\n"
    elif kind == "clk4pad":
        for i in range(1, 4):
            inp(f"clk{i}")
        inp("rst"); inp("ce"); inp("d"); outp("q")
        body += shift("r0", "clk", 100, "d", None)
        for i in range(1, 4):
            body += shift(f"r{i}", f"clk{i}", 100, "d", None)
        body += "reg qr; always @(posedge clk) qr <= ^{r0[99], r1[99], r2[99], r3[99]};\nassign q = qr;\n"
    elif kind == "hsctl":
        inp("rst"); inp("ce"); inp("arst"); inp("d"); outp("q")
        body += ("reg [149:0] ra, rb;\n"
                 "always @(posedge clk) if (rst) ra <= 0; else if (ce) ra <= {ra[148:0], d};\n"
                 "always @(posedge clk or posedge arst) if (arst) rb <= 0; else rb <= {rb[148:0], ra[149]};\n"
                 "reg qr; always @(posedge clk) qr <= rb[149];\nassign q = qr;\n")
    elif kind == "sec8":
        for i in range(8):
            inp(f"ce{i}"); inp(f"rs{i}")
        inp("d"); outp("q")
        for i in range(8):
            body += (f"reg [89:0] r{i};\n"
                     f"always @(posedge clk) if (rs{i}) r{i} <= 0; else if (ce{i}) "
                     f"r{i} <= {{r{i}[88:0], d ^ r{max(i-1, 0)}[89]}};\n")
        body += "reg qr; always @(posedge clk) qr <= ^{" + ", ".join(f"r{i}[89]" for i in range(8)) + "};\nassign q = qr;\n"
    elif kind == "fanout":
        for i in range(4):
            inp(f"x{i}")
        inp("d"); outp("q")
        body += "reg [239:0] r;\n"
        body += ("always @(posedge clk) r <= {r[238:0], d} ^ ({60{x0}} & r[239:180]) ^ ({60{x1}} & r[179:120])"
                 " ^ ({60{x2}} & r[119:60]) ^ ({60{x3}} & r[59:0]) ^ {r[238:0], 1'b0};\n")
        body += "reg qr; always @(posedge clk) qr <= r[239];\nassign q = qr;\n"
    else:
        raise SystemExit(kind)
    v = "module top (\n    " + ",\n    ".join(ports) + "\n);\n" + body + "endmodule\n"
    lpf = "".join(f'LOCATE COMP "{n}" SITE "{s}";\nIOBUF PORT "{n}" IO_TYPE=LVCMOS33;\n' for n, s in pins)
    return v, lpf


KINDS = sys.argv[1:] or ["pll3dom", "pll3dom_x", "clk4pad", "hsctl", "sec8", "fanout"]


def main():
    global PINS
    for kind in KINDS:
        PINS = iter([48, 30, 77, 84, 47, 49, 51, 52, 53, 54, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70])
        v, lpf = design(kind)
        d = os.path.join(OUT, kind)
        os.makedirs(os.path.join(d, "src"), exist_ok=True)
        open(os.path.join(d, "src", "top.v"), "w").write(v)
        open(os.path.join(d, "placement.lpf"), "w").write(lpf)
        open(os.path.join(d, "design.toml"), "w").write(
            f'top = "top"\npurpose = "global network: {kind}"\nconstruct = "globals"\nvariant = "{kind}"\n')
        print("wrote", d)


if __name__ == "__main__":
    sys.exit(main())
