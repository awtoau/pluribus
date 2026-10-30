#!/usr/bin/env python3.15t
"""Known-pattern specimens for lifters/cycloneiv_clean/patterns.py (#165): tiny Quartus builds with a stated polynomial / tap set.

  python3.15t scripts/cycloneiv_pattern_specimens.py [--only name,name]       # log tmp/logs/cycloneiv_pattern_specimens.log
Writes tmp/pattern_tests/<name>/{top.v,expected.json,bitstream.rbf}; NOT the corpus.  Black box: quartus only.
expected.json is the ground truth the detectors are scored against (scripts/cycloneiv_pattern_score.py).
Build limits as cycloneiv_clean_carry_specimens (map 180 s, fit 600 s, asm 60 s, cpf 10 s: first-run backstops).
"""
import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("pattern_specimens")
DEVICE = "EP4CGX150DF31C7"
OUT = Path(REPO) / "tmp" / "pattern_tests"
LIMITS = {"quartus_map": 180, "quartus_fit": 600, "quartus_asm": 60, "quartus_cpf": 10}

CRC_FN = """
function [{n1}:0] crc_next(input [{n1}:0] c, input [{w1}:0] d);
  integer i; reg [{n1}:0] r; reg fb;
  begin
    r = c;
    for (i = {w1}; i >= 0; i = i - 1) begin
      fb = r[{n1}] ^ d[i];
      r = {{r[{n2}:0], 1'b0}} ^ (fb ? {n}'h{poly:X} : {n}'h0);
    end
    crc_next = r;
  end
endfunction
"""

GFMUL = """
function [7:0] gfmul_{tag}(input [7:0] a);
  integer i; reg [7:0] p, x;
  begin
    p = 8'h0; x = a;
    for (i = 0; i < 8; i = i + 1) begin
      if (8'h{c:X} & (8'h1 << i)) p = p ^ x;
      x = {{x[6:0], 1'b0}} ^ (x[7] ? 8'h{plo:X} : 8'h0);
    end
    gfmul_{tag} = p;
  end
endfunction
"""


def crc_design(items):
    """items: [(name, n, poly(low n bits), w)] -> Verilog with one registered CRC per item (enable, sync reset to 0)."""
    src = ["module top(input clk, input rst, input en,"]
    ports = []
    for nm, n, poly, w in items:
        ports.append(f"  input [{w - 1}:0] d_{nm}, output [{n - 1}:0] q_{nm}")
    src.append(",\n".join(ports) + ");")
    body = []
    for nm, n, poly, w in items:
        body.append(CRC_FN.format(n1=n - 1, n2=n - 2, w1=w - 1, n=n, poly=poly).replace("crc_next", f"crc_next_{nm}"))
        body.append(f"reg [{n - 1}:0] r_{nm}; assign q_{nm} = r_{nm};")
        body.append(f"always @(posedge clk) if (rst) r_{nm} <= 0; else if (en) r_{nm} <= crc_next_{nm}(r_{nm}, d_{nm});")
    return "\n".join(src + body + ["endmodule"]) + "\n"


def specs():
    out = {}
    # additive whitening (Fibonacci x^15+x^14+1, XNOR so the all-zero reset is legal) + PRBS9 (x^9+x^5+1) + Galois x^7+x^6+1
    out["lfsr"] = (
        """module top(input clk, input rst, input en, input d, output reg q, output reg p9, output reg g7);
reg [14:0] s15; reg [8:0] s9; reg [6:0] g;
always @(posedge clk) begin
  if (rst) begin s15 <= 0; s9 <= 0; g <= 0; end
  else if (en) begin
    s15 <= {s15[13:0], ~(s15[14] ^ s15[13])};
    s9  <= {s9[7:0], ~(s9[8] ^ s9[4])};
    g   <= ({g[5:0], 1'b0} ^ (g[6] ? 7'h41 : 7'h0)) ^ 7'h01;
  end
  q <= d ^ s15[14]; p9 <= s9[8]; g7 <= g[6];
end
endmodule
""",
        dict(lfsr=[dict(n=15, poly=[15, 14, 0], form="fibonacci", data_xor="additive"), dict(n=9, poly=[9, 5, 0], form="fibonacci"),
                   dict(n=7, poly=[7, 6, 0], form="galois")]))
    crc = [("c32", 32, 0x04C11DB7, 8), ("c16", 16, 0x1021, 16), ("c8", 8, 0x07, 8)]
    out["crc"] = (crc_design(crc), dict(crc=[dict(n=n, poly=p, w=w) for _nm, n, p, w in crc]))
    # K=7 rate-1/2 171/133 octal, window = {u, d0..d5}, u (newest) = MSB of the generator
    out["conv"] = (
        """module top(input clk, input u, output reg y0, output reg y1);
reg [5:0] d;
wire [6:0] win = {u, d[0], d[1], d[2], d[3], d[4], d[5]};
always @(posedge clk) begin
  d <= {d[4:0], u};
  y0 <= ^(win & 7'o171);
  y1 <= ^(win & 7'o133);
end
endmodule
""", dict(conv=[dict(k=7, g=[0o171, 0o133])]))
    # self-synchronising descrambler x^7+x^4+1 (IEEE 802.11 s17.3.5.5): out = in ^ in(t-4) ^ in(t-7)
    out["descr"] = (
        """module top(input clk, input d, output reg q);
reg [6:0] sr;
always @(posedge clk) begin sr <= {sr[5:0], d}; q <= d ^ sr[3] ^ sr[6]; end
endmodule
""", dict(fir=[dict(poly=[7, 4, 0])]))
    out["gfmul"] = (
        "module top(input clk, input [7:0] x1, input [7:0] x2, input [7:0] x3, output reg [7:0] y1, output reg [7:0] y2, output reg [7:0] y3);\n"
        + GFMUL.format(tag="a", c=0x57, plo=0x1D) + GFMUL.format(tag="b", c=0x03, plo=0x1B) + GFMUL.format(tag="c", c=0x0E, plo=0x1B)
        + "always @(posedge clk) begin y1 <= gfmul_a(x1); y2 <= gfmul_b(x2); y3 <= gfmul_c(x3); end\nendmodule\n",
        dict(gfmul=[dict(c=0x57, poly=0x11D), dict(c=0x03, poly=0x11B), dict(c=0x0E, poly=0x11B)]))
    out["misc"] = (
        """module top(input clka, input clkb, input din, input [7:0] dwide, output reg flag, output reg [7:0] rq, output sync_o, output [7:0] bq);
reg [12:0] cnt; reg mq;
(* ramstyle = "M9K" *) reg mem [0:8191];
integer k, j; initial for (k = 0; k < 64; k = k + 1) for (j = 0; j < 128; j = j + 1) mem[k * 128 + j] = (((k * 128 + j) * 37) ^ ((k * 128 + j) >> 3)) & 1;
wire [12:0] ad = {cnt[5:0], cnt[12:6]};
always @(posedge clka) begin cnt <= cnt + 13'd1; mq <= mem[ad]; rq <= {rq[6:0], mq}; end
reg [23:0] sr;
always @(posedge clka) begin sr <= {sr[22:0], din}; flag <= (sr == 24'hA5C3F0); end
reg s1, s2; reg a_q;
always @(posedge clka) a_q <= din ^ cnt[0];
always @(posedge clkb) begin s1 <= a_q; s2 <= s1; end
assign sync_o = s2;
reg [7:0] w1, w2;
always @(posedge clka) w1 <= dwide;
always @(posedge clkb) begin w2 <= w1; end
assign bq = w2;
endmodule
""", dict(interleaver=[dict(addr_bits=13, kind="bit_permutation")], counter=[dict(width=13)], sync_word=[dict(n=24)], shift=[dict(n=24)], cdc_sync=[dict(n=1)], cdc_bus=[dict(w=8)]))
    # twiddle ROM (counter addressed) feeding a 16x16 multiplier (MAC)
    out["fftlike"] = (
        """module top(input clk, input [15:0] x, output reg [31:0] p);
reg [8:0] cnt; reg [15:0] coef;
(* ramstyle = "M9K" *) reg [15:0] rom [0:511];
integer k, j; initial for (k = 0; k < 8; k = k + 1) for (j = 0; j < 64; j = j + 1) rom[k * 64 + j] = (k * 64 + j) * 123 + 77;
always @(posedge clk) begin cnt <= cnt + 9'd1; coef <= rom[cnt]; p <= x * coef; end
endmodule
""", dict(counter=[dict(width=9)], mac_rom=[dict(n=1)], m9k_addr=[dict(kind="identity")]))
    # gray-coded write pointer crossing clka -> clkb (2-FF), binary pointer compare in clkb
    out["fifoish"] = (
        """module top(input clka, input clkb, input wen, input ren, output reg [4:0] diff);
reg [4:0] wcnt, rcnt, w1, w2; reg [4:0] wg;
always @(posedge clka) begin if (wen) wcnt <= wcnt + 5'd1; wg <= (wcnt >> 1) ^ wcnt; end
always @(posedge clkb) begin if (ren) rcnt <= rcnt + 5'd1; w1 <= wg; w2 <= w1; diff <= w2 - rcnt; end
endmodule
""", dict(counter=[dict(width=5), dict(width=5)], gray=[dict(n=1)], cdc_bus=[dict(w=5)], pointer_compare=[dict(n=1)]))
    return out


def build(name, src, expected):
    import cycloneiv_fuzz as fz
    import toolchain
    d = OUT / name
    shutil.rmtree(d, ignore_errors=True)
    q = d / "quartus"
    q.mkdir(parents=True)
    (d / "top.v").write_text(src)
    (d / "expected.json").write_text(json.dumps(expected, indent=1))
    (q / "top.v").write_text(src)
    full = ['set_global_assignment -name FAMILY "Cyclone IV GX"', f"set_global_assignment -name DEVICE {DEVICE}",
            "set_global_assignment -name TOP_LEVEL_ENTITY top", "set_global_assignment -name VERILOG_FILE top.v",
            'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
            "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1"]
    (q / "build.qsf").write_text("\n".join(full) + "\n")
    (q / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = toolchain.quartus_bin()
    t0 = time.time()
    steps = [("quartus_map", [f"{qb}/quartus_map", "build"]), ("quartus_fit", [f"{qb}/quartus_fit", "build"]),
             ("quartus_asm", [f"{qb}/quartus_asm", "build"]),
             ("quartus_cpf", [f"{qb}/quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    for step, cmd in steps:
        if not fz.run(step, cmd, q, d / "logs", LIMITS):
            raise SystemExit(f"{name}: {step} failed")
    shutil.copyfile(q / "build.rbf", d / "bitstream.rbf")
    shutil.rmtree(q)
    log.info("%s ok %.0fs", name, time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_pattern_specimens.log"))])
    import heavy_guard
    S = specs()
    names = a.only.split(",") if a.only else list(S)
    with heavy_guard.lease(6, "cyc4_pattern_specimens", log):
        for n in names:
            build(n, *S[n])


if __name__ == "__main__":
    main()
