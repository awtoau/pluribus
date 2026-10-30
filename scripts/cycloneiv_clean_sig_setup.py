#!/usr/bin/env python3.15t
"""Assemble the signature specimens in tmp/sig/<name>/ from tmp/sig/_cand/<set>/ (third-party, untracked) + own wrappers.

  python3.15t scripts/cycloneiv_clean_sig_setup.py [NAME ...]      (default: all)
Writes sig.toml, wrapper tops (own code, registers around combinational cores), copies sources + LICENCE-NOTE.txt.
Patches are parameter edits on the COPY in tmp/ (rs_parameters.svh n/check).  Build: cycloneiv_clean_sig_build.py.
"""
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SIG = REPO / "tmp" / "sig"
CAND = SIG / "_cand"

LFSR_WRAP = """module {top} (input clk, input rst, input v, input [{dw}-1:0] d, output [{dw}-1:0] q, output [{w}-1:0] s);
  reg [{w}-1:0] st; wire [{dw}-1:0] o; wire [{w}-1:0] n;
  lfsr #(.LFSR_WIDTH({w}), .LFSR_POLY({w}'h{poly}), .LFSR_CONFIG("{cfg}"), .LFSR_FEED_FORWARD({ff}), .REVERSE({rev}), .DATA_WIDTH({dw}))
    u (.data_in(d), .state_in(st), .data_out(o), .state_out(n));
  reg [{dw}-1:0] qr;
  always @(posedge clk) if (rst) st <= {init}; else if (v) begin st <= n; qr <= o; end
  assign q = qr; assign s = st;
endmodule
"""

SPEC = {
    "sine_rom": dict(src=[], top="rom_top", files=["rom_top.v", "rom.hex"]),
    "wimax_prbs": dict(src=["wimax_prbs"], top="prbs", files=["prbs.vhd"]),
    "scr_80211b": dict(src=["scr_80211b"], top="scrambler", files=["scrambler.v"]),
    "scr_xband": dict(src=["scr_xband"], top="Scrambler", files=["PRS.vhd", "Scrambler.vhd"]),
    "conv_k7": dict(src=["fec_convenc"], top="vit_enc", files=["vit_enc.sv"], qsf=['set_global_assignment -name SEARCH_PATH ..']),
    "viterbi_k7": dict(src=["fec_viterbi"], top="vit_dec", qsf=["set_global_assignment -name SEARCH_PATH .."],
                       files=["vit_dec_types.svh", "vit_dec_acsu.sv", "vit_dec_acsu_la.sv", "vit_dec_bmc.sv", "vit_dec_rp.sv",
                              "vit_trb.sv", "vit_trb_ctrl.sv", "vit_trb_decision.sv", "vit_trb_engine.sv", "vit_trb_lifo.sv",
                              "vit_trb_ram.sv", "vit_dec.sv"]),
    "rs255_enc": dict(src=["fec_rs"], top="rs_enc", files=["rs_enc.sv"], patch=("n", 255, "check", 16),
                      qsf=["set_global_assignment -name SEARCH_PATH .."]),
    "rs255_dec": dict(src=["fec_rs"], top="rs_dec", patch=("n", 255, "check", 16),
                      qsf=["set_global_assignment -name SEARCH_PATH .."],
                      files=["rs_syndrome_count.sv", "rs_berlekamp.sv", "rs_berlekamp_ribm_1check.sv", "rs_berlekamp_ribm_1p5check_by_check.sv",
                             "rs_berlekamp_ribm_3check.sv", "rs_berlekamp_ribm_6check.sv", "rs_chieny_search.sv", "rs_gf_div.sv", "bch_buffer.sv", "rs_dec.sv"]),
    "fft64_r22sdf": dict(src=["fft_r22sdf"], top="FFT", files=["Butterfly.v", "DelayBuffer.v", "Multiply.v", "SdfUnit.v", "SdfUnit2.v",
                                                              "Twiddle64.v", "TwiddleConvert4.v", "TwiddleConvert8.v", "FFT64.v"]),
    "fft64_dit": dict(src=["fft_dit"], top="dit", files=["butterfly.v", "dit.v"],
                      qsf=["set_parameter -name N 64", "set_parameter -name NLOG2 6", "set_parameter -name X_WDTH 16", "set_parameter -name TF_WDTH 16"]),
    "interleaver_wimax": dict(src=["wimax_interleaver"], top="inter_top", files=["sipo.vhd", "piso.vhd", "inter_top.vhd"]),
    "uart": dict(src=["uart_af"], top="uart", files=["uart_tx.v", "uart_rx.v", "uart.v"]),
    "prbs15_lfsr": dict(src=["crc_lfsr"], top="w_prbs15", files=["lfsr.v", "w.v"],
                        wrap=LFSR_WRAP.format(top="w_prbs15", w=15, poly="4001", cfg="FIBONACCI", ff=0, rev=0, dw=8, init="15'h6e2a")),
    "crc32_lfsr": dict(src=["crc_lfsr"], top="w_crc32", files=["lfsr.v", "w.v"],
                       wrap=LFSR_WRAP.format(top="w_crc32", w=32, poly="04c11db7", cfg="GALOIS", ff=0, rev=1, dw=8, init="32'hffffffff")),
    "crc8_lfsr": dict(src=["crc_lfsr"], top="w_crc8", files=["lfsr.v", "w.v"],
                      wrap=LFSR_WRAP.format(top="w_crc8", w=8, poly="07", cfg="GALOIS", ff=0, rev=0, dw=8, init="8'h00")),
}


ROM_TOP = """module rom_top (input clk, input [7:0] addr, output reg [15:0] q);
  reg [15:0] mem [0:255];
  initial $readmemh("rom.hex", mem);
  always @(posedge clk) q <= mem[addr];
endmodule
"""


def rom_hex():
    import math
    return "\n".join("%04x" % (round(32000 * math.cos(2 * math.pi * i / 256)) & 0xFFFF) for i in range(256)) + "\n"


def setup(name):
    s = SPEC[name]
    d = SIG / name
    d.mkdir(exist_ok=True)
    if name == "sine_rom":     # own code: full-wave cosine table, 256 x 16 signed, in M9K
        (d / "rom_top.v").write_text(ROM_TOP)
        (d / "rom.hex").write_text(rom_hex())
    for c in s["src"]:
        for f in (CAND / c).iterdir():
            shutil.copyfile(f, d / f.name)
    if "patch" in s:
        p = d / "rs_parameters.svh"
        t = p.read_text()
        a, av, b, bv = s["patch"]
        for k, v in ((a, av), (b, bv)):
            t, n = re.subn(rf"(parameter int {k}\s*=\s*)\d+", rf"\g<1>{v}", t)
            assert n == 1, (k, n)
        p.write_text(t)
    if "wrap" in s:
        (d / "w.v").write_text(s["wrap"])
    files = s["files"]
    q = "".join(f'"{x}", ' for x in files)
    extra = s.get("qsf", [])
    (d / "sig.toml").write_text(f'top = "{s["top"]}"\nfiles = [{q.rstrip(", ")}]\nqsf = [' + ", ".join(f'"{x}"' for x in extra) + "]\n")


if __name__ == "__main__":
    for n in (sys.argv[1:] or SPEC):
        setup(n)
        print("setup", n)
