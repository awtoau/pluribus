#!/usr/bin/env python3.15t
"""TX-first + loopback / real-capture RX simulation of the lifted DJI m2001 image (#189 steps 2-4).

  python3.15t scripts/cycloneiv_clean_loopback_sim.py build   [--work tmp/image_sim_dji_push]      TB + verilator (RTL emit, ~90 s)
  python3.15t scripts/cycloneiv_clean_loopback_sim.py stim    [--frames 3] [--radio]                 m1400 boot script + per-frame SPI replay -> stim_tx.txt
  python3.15t scripts/cycloneiv_clean_loopback_sim.py run     --tag T [--stim F] [--rx F] [--cyc N]  run the binary (stall guard)
  python3.15t scripts/cycloneiv_clean_loopback_sim.py analyse --tag T                                TX pads -> samples, AC8/R22/R25 timing, bit order, OFDM stats
  python3.15t scripts/cycloneiv_clean_loopback_sim.py rxgen   --tag T --from loopback|capture ...    RX stimulus file (DDR words per DATA_CLK edge)
  python3.15t scripts/cycloneiv_clean_loopback_sim.py probes  --tag T                                decode probe trace (ID register, comparator counter, demux, FIFO, AC11 bytes)
Stimulus language (stim file, one op per line): W aa vv | R aa | X b1 b2 b3 | RMW aa or and | D cycles | S timeout | RXSTART | M text | END.
Clocks (TB inputs, no PLL in the emit): clk_main 100 MHz, pll_b 50 MHz, pll_c +pllc_half (default 5.6 MHz = PLL_2 c0 at Fin 40 MHz, U),
b14 40 MHz, N25 DATA_CLK 22.4 MHz (section 3), resets = the 5 async-clear sources low for 8 slow periods. Work dir tmp/loopback/, log tmp/logs/loopback_sim.log.
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
import cycloneiv_clean_image_sim as IS            # noqa: E402  (sh = guarded subprocess, THREADS)
import cycloneiv_clean_uplink_record as UR        # noqa: E402

OUT = os.path.join(REPO, "tmp", "loopback")
LOG = os.path.join(REPO, "tmp", "logs", "loopback_sim.log")
log = logging.getLogger("loopback")
CLK_MAIN, CLK_PLLB, CLK_PLLC, CLK_B14, CLK_COREA, CLK_COREB = ("u_clkbuf_out_0_46_30_0", "u_clkbuf_out_0_46_31_0", "u_clkbuf_out_57_91_33_0",
                                                               "u_clkbuf_out_57_91_29_0", "u_clkbuf_out_0_46_33_0", "u_clkbuf_out_0_46_29_0")
HALF = {CLK_MAIN: 5000, CLK_PLLB: 10000, CLK_B14: 12500, CLK_COREA: 5000, CLK_COREB: 5000}     # ps; pll_c from +pllc_half
BLK_PLLC = ("u_blk_clk_buf_23_62_0_2", "u_blk_clk_buf_23_63_0_1")      # TX playback RAM block clocks (undecoded source) -> pll_c
BLK_MAIN = ("u_blk_clk_buf_7_85_0_4", "u_blk_clk_buf_7_86_0_4")
DCLK_HALF = 22321            # 22.4 MHz AD9363 DATA_CLK on N25 (section 3, 2R2T DDR)
SPI = dict(mosi="AB11", sck="AA8", cs="AA9", miso="AA7")
RX_ORDER = ["M25", "T25", "T24", "U26", "U25", "V26", "W26", "W25", "W24", "Y25", "Y24", "AB26", "AA25"]   # M9K (52,74) data[0..12]
# physical TX bit order from the playback RAM lanes (V): bit b<9 of lane j = m9k_23_62_o[9j+b], b>=9 = m9k_23_63_o[18+3j+b-9];
# the pins.tsv TXD_n draft labels run the other way (E25 = TXD_0 is the MSB here)
TX_PADS = {"L26": 0, "L25": 1, "K26": 2, "J26": 3, "H26": 4, "H25": 5, "G25": 6, "H24": 7, "F26": 8, "G26": 9, "E26": 10, "E25": 11}
PROBE_FFS = {   # name -> flat FF list (RTL names via ffmap.json); vectors are concatenated MSB-first in this order
    "id_rx": ["ff_33_89_%d" % i for i in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)] + ["ff_33_90_%d" % i for i in (0, 3, 4, 7, 8, 14, 15)] + ["ff_34_90_0", "ff_34_90_2", "ff_34_90_3"],
    "deser": ["ff_31_65_%d" % i for i in range(5, 16)],
    "demux": ["ff_11_45_3", "ff_11_45_6", "ff_12_47_4"],
    "gate": ["ff_40_88_10", "ff_40_88_11"],
}
FORCE_TARGETS = ["sr_19[0]", "sr_13[2]"]      # ff_35_67_0, ff_38_79_4: RX-side frame-detect leaves feeding the frame FSM (38,86)/(39,86)
PROBE_REGS = ["cnt_82", "cnt_65", "cnt_220", "cnt_147", "cnt_193", "r_401", "r_594"]   # RTL vectors: ID-match counter, frame counter, DUML FIFO w/r ptr, FX3 FIFO wptr, AC11 bit ctr, field reg


def nl_load(work):
    return pickle.load(open(os.path.join(work, "nl.pkl"), "rb"))


def gen_tb(nl, work, ffmap):
    pads = {io["ball"]: io["dir"] for io in nl.ios}
    clks = {c for c in HALF} | {CLK_PLLC}
    rst = sorted(collections.Counter(F["aclr"] for F in nl.ffs if F.get("aclr") in nl.srcs and F["aclr"] not in clks))
    L = ["`timescale 1ps/1ps", "module tb;", "integer pllc_half;", "initial if (!$value$plusargs(\"pllc_half=%d\", pllc_half)) pllc_half = 89286;"]
    for c in clks:
        L.append(f"reg {c} = 1'b0;")
    for r in rst:
        L.append(f"reg {r} = 1'b0;")
    L.append("reg dclk = 1'b0;")
    conn, outs, ins = [], [], []
    for b, d in sorted(pads.items()):
        if d == "input":
            L.append(f"reg pad_{b}_r = 1'b0;")
            conn.append(f".io_{b}(pad_{b}_r)")
            ins.append(b)
        else:
            L.append(f"wire pad_{b}_w;")
            conn.append(f".io_{b}(pad_{b}_w)")
            outs.append(b)
    for s in sorted(nl.srcs):
        if s in clks or s in rst:
            v = s
        elif s in BLK_PLLC:
            v = CLK_PLLC
        elif s in BLK_MAIN:
            v = CLK_MAIN
        else:
            v = "1'b0"
        conn.append(f".{s}({v})")
    L.append("cyc4_top dut(" + ",\n  ".join(conn) + ");")
    for c, h in HALF.items():
        L.append(f"always #{h} {c} = ~{c};")
    L.append(f"always #(pllc_half) {CLK_PLLC} = ~{CLK_PLLC};")
    L.append(f"always #{DCLK_HALF} dclk = ~dclk;")
    L.append("assign pad_N25_r_drv = dclk;")      # placeholder replaced below
    L[-1] = "always @(dclk) pad_N25_r = dclk;"
    hmax = max(HALF.values())
    for r in rst:
        L.append(f"initial begin {r} = 1'b0; #{8 * hmax} {r} = 1'b1; end")
    # half-cycle counter on clk_main, recorders 2.5 ns after each edge
    L.append(f"longint hc = 0; always @({CLK_MAIN}) hc = hc + 1;")
    ov = ", ".join(f"pad_{b}_w" for b in outs)
    L.append(f"wire [{len(outs) - 1}:0] outv = {{{ov}}}; reg [{len(outs) - 1}:0] outp = 0;")
    L.append("integer fo, fp, fr; string tag; initial begin if (!$value$plusargs(\"tag=%s\", tag)) tag = \"x\";"
             f" fo = $fopen({{\"{OUT}/out_\", tag, \".txt\"}}, \"w\"); fp = $fopen({{\"{OUT}/probe_\", tag, \".txt\"}}, \"w\");"
             f" fr = $fopen({{\"{OUT}/spi_\", tag, \".txt\"}}, \"w\"); end")
    L.append(f"always @({CLK_MAIN}) begin #2500; if (outv !== outp) begin $fwrite(fo, \"%0d %h\\n\", hc, outv); outp = outv; end end")
    # probes
    pv, widths = [], []
    probes = dict(PROBE_FFS)
    extra = os.path.join(OUT, "probes_extra.json")      # regfile bits / FSM / TX-RAM enables, from the SPI trace register map
    if os.path.exists(extra):
        probes.update(json.load(open(extra)))
    for name, ffs in probes.items():
        bits = ["dut." + ffmap[f] for f in ffs]
        pv.append("{" + ", ".join(bits) + "}")
        widths.append((name, len(bits)))
    for r in PROBE_REGS:
        pv.append("dut." + r)
        widths.append((r, None))
    L.append("wire [1023:0] prv = {" + ", ".join(pv) + "}; reg [1023:0] prp = 0;")
    L.append(f"always @({CLK_MAIN}) begin #2600; if (prv !== prp) begin $fwrite(fp, \"%0d %h\\n\", hc, prv); prp = prv; end end")
    # SPI master (same byte protocol as image_sim: data on MOSI before SCK rise, MISO sampled at SCK rise)
    L.append(f"integer q = 160000; reg [23:0] mrise; reg [7:0] miso;")
    L.append(f"task spi_byte(input [7:0] b); integer i; begin for (i = 7; i >= 0; i = i - 1) begin pad_{SPI['mosi']}_r = b[i]; #(q);"
             f" pad_{SPI['sck']}_r = 1'b1; mrise = {{mrise[22:0], pad_{SPI['miso']}_w}}; #(2 * q); pad_{SPI['sck']}_r = 1'b0; #(q); end end endtask")
    L.append(f"task spi_xfer(input [7:0] op, input [7:0] rg, input [7:0] v); begin pad_{SPI['cs']}_r = 1'b0; #(4 * q);"
             f" spi_byte(op); spi_byte(rg); spi_byte(v); #(4 * q); pad_{SPI['cs']}_r = 1'b1; miso = mrise[7:0]; #(8 * q); end endtask")
    # sync wait: falling edge on the sync pad (AC8 default, +sync=AB12)
    L.append("string syncp; reg sync_w; initial if (!$value$plusargs(\"sync=%s\", syncp)) syncp = \"AC8\";")
    L.append("always @(*) sync_w = (syncp == \"AB12\") ? pad_AB12_w : pad_AC8_w;")
    L.append(f"task wait_sync(input integer tmo); integer k; reg p; begin k = 0; p = sync_w; while (k < tmo) begin @(posedge {CLK_MAIN}); #1;"
             " if (p && !sync_w) begin $fwrite(fr, \"%0d SYNC\\n\", hc); k = tmo + 1; end p = sync_w; k = k + 1; end"
             " if (k == tmo) $fwrite(fr, \"%0d SYNC_TIMEOUT\\n\", hc); end endtask")
    # RX playback: one 16-bit word per DATA_CLK edge: [11:0] data -> RX_ORDER[0..11], [12] -> RX_ORDER[12], [13] spare
    L.append("integer frx = 0, rx_go = 0, rxn = 0, rxw = 0; string rxf; reg [15:0] rxv = 0;")
    L.append("initial if ($value$plusargs(\"rx=%s\", rxf)) frx = $fopen(rxf, \"r\");")
    L.append("always @(dclk) begin #2000; if (rx_go && frx != 0 && !$feof(frx)) begin rxn = $fscanf(frx, \"%h\\n\", rxv); if (rxn == 1) begin rxw = rxw + 1;")
    for i, b in enumerate(RX_ORDER):
        L.append(f"  pad_{b}_r = rxv[{i}];")
    L.append("end end end")
    # stimulus interpreter
    L.append("integer fs = 0, n, k; string stimf, line; reg [7:0] a, b, c; integer ops = 0;")
    L.append(f"initial begin pad_{SPI['cs']}_r = 1'b1; pad_{SPI['sck']}_r = 1'b0; pad_{SPI['mosi']}_r = 1'b0;")
    L.append("  if ($value$plusargs(\"stim=%s\", stimf)) begin fs = $fopen(stimf, \"r\");")
    L.append(f"  #{8 * hmax + 2000 * 2 * hmax};")
    L.append("  while (!$feof(fs)) begin n = $fgets(line, fs); if (n == 0) break; ops = ops + 1;")
    L.append("    if (line.substr(0, 6) == \"RXSTART\") begin rx_go = 1; $fwrite(fr, \"%0d RXSTART\\n\", hc); end")
    L.append("    else if (line.substr(0, 0) == \"M\") $fwrite(fr, \"%0d %s\", hc, line);")
    L.append("    else if (line.substr(0, 2) == \"END\") break;")
    L.append("    else if ($sscanf(line, \"W %h %h\", a, b) == 2) spi_xfer(8'h0E, a, b);")
    L.append("    else if ($sscanf(line, \"RMW %h %h %h\", a, b, c) == 3) begin spi_xfer(8'h0F, a, 8'hFF); $fwrite(fr, \"%0d R %02h %02h\\n\", hc, a, miso); spi_xfer(8'h0E, a, (miso & c) | b); end")
    L.append("    else if ($sscanf(line, \"R %h\", a) == 1) begin spi_xfer(8'h0F, a, 8'hFF); $fwrite(fr, \"%0d R %02h %02h\\n\", hc, a, miso); end")
    L.append("    else if ($sscanf(line, \"X %h %h %h\", a, b, c) == 3) spi_xfer(a, b, c);")
    L.append(f"    else if ($sscanf(line, \"D %d\", n) == 1) repeat (n) @(posedge {CLK_MAIN});")
    L.append("    else if ($sscanf(line, \"S %d\", n) == 1) wait_sync(n);")
    L.append("  end $fwrite(fr, \"%0d STIMDONE ops=%0d\\n\", hc, ops); $display(\"STIMDONE ops=%0d hc=%0d\", ops, hc); end end")
    # bypass experiment (+force=N): pulse an RX-sync FF high for 2000 clk_main cycles, once per 14 ms frame, from link start on
    L.append("integer fsel; initial begin if (!$value$plusargs(\"force=%d\", fsel)) fsel = -1;")
    L.append(f"  if (fsel >= 0) begin #(64'd1000000 * 10000); forever begin")
    for i, tgt in enumerate(FORCE_TARGETS):
        L.append(f"    if (fsel == {i}) force dut.{tgt} = 1'b1;")
    L.append("    $fwrite(fr, \"%0d FORCE on %0d\\n\", hc, fsel); #(64'd2000 * 10000);")
    for i, tgt in enumerate(FORCE_TARGETS):
        L.append(f"    if (fsel == {i}) release dut.{tgt};")
    L.append("    #(64'd1398000 * 10000); end end end")
    L.append("longint ncyc; initial begin ncyc = 1000000; void'($value$plusargs(\"cyc=%d\", ncyc)); #(ncyc * 64'd10000);")
    L.append("  $fwrite(fr, \"%0d SIMDONE rxwords=%0d\\n\", hc, rxw); $display(\"SIMDONE hc=%0d rxwords=%0d\", hc, rxw); $fclose(fo); $fclose(fp); $fclose(fr); $finish; end")
    L.append("endmodule")
    meta = dict(outs=outs, ins=ins, probes=widths, rx_order=RX_ORDER, resets=rst, half=HALF)
    return "\n".join(L) + "\n", meta


def cmd_build(a):
    nl = nl_load(a.work)
    ffmap = json.load(open(os.path.join(a.work, "ffmap.json")))
    tb, meta = gen_tb(nl, a.work, ffmap)
    tbp = os.path.join(OUT, "tb_loop.v")
    open(tbp, "w").write(tb)
    json.dump(meta, open(os.path.join(OUT, "tb_meta.json"), "w"), indent=1)
    src = os.path.join(a.work, "rtl_s.v")
    md = os.path.join(OUT, "obj_loop")
    rc, s, rss, last, out = IS.sh(["verilator", "--binary", "--timing", "--threads", str(IS.THREADS), "-j", str(IS.THREADS), "-O1", "--x-assign", "0",
                                   "--x-initial", "0", "--converge-limit", "100000", "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-UNOPTFLAT",
                                   "-Wno-WIDTH", "-Wno-MULTIDRIVEN", "-Wno-TIMESCALEMOD", "--top-module", "tb", "--Mdir", md, tbp, src], "build_loop", 1800)
    log.info("BUILD verilator loop: rc=%s %.0fs peak RSS %.0f MB last=%r", rc, s, rss, last[-200:])
    if rc:
        for l in out.splitlines():
            if "%Error" in l:
                log.error("%s", l[:300])


# ----------------------------------------------------------------------------------------------------------------------------- stimulus
LISTING = "/mnt/2tb/git/awto-dji/tmp/m1400_fpga_script_listing.txt"
DECODER = "/mnt/2tb/git/awto-dji/scripts/re/m1400_fpga_script_decode.py"
MCU_CYC = {"mr0": 139000, "mr1": 833000, "mr2": 1250000}      # TIMER1 360 kHz ticks 500/3000/4500 at 100 MHz sim clock
BAND24 = [("ba", 0x7A), ("bb", 0x00), ("bc", 0x62), ("bd", 0x66), ("be", 0x26), ("b0", 0x7A), ("b1", 0x00), ("b2", 0x95), ("b3", 0x99), ("b4", 0x29)]  # FUN_00016ef6 2.4 GHz


def boot_ops(mode, radio):
    if not os.path.exists(LISTING):
        subprocess.run(["python3", DECODER], cwd=os.path.dirname(os.path.dirname(os.path.dirname(DECODER))), check=True)
    sec, cur = {}, None
    for line in open(LISTING):
        if line.startswith("== "):
            cur = line.split()[1]
            sec[cur] = []
        elif cur and line.strip():
            sec[cur].append(line.split())
    ops = [f"M boot table {mode} ({len(sec[mode])} records, radio={'replayed' if radio else 'skipped'})"]
    for _addr, op, x, y in sec[mode]:
        x, y = int(x, 16), (int(y, 16) if y.startswith("0x") else y)
        if op == "FPGA_RAW":
            ops.append(f"X {x >> 8:02X} {x & 0xFF:02X} {y:02X}")
        elif op == "MODE":
            ops.append(f"W 01 {y:02X}")
        elif op == "AD_WR":
            if radio:
                ops += ["W 01 01", f"X {0x80 | (x >> 8):02X} {x & 0xFF:02X} {y:02X}", "W 01 02"]
        elif op == "DELAY":
            ops.append(f"D {1000 * y}")
    # post-boot (FUN_00015b86, success path: lock checks need the radio): engine mode, reg0 bit0 pulse (FUN_00015b5e)
    ops += ["M post-boot", "W 01 02", "RMW 00 01 FF", "RMW 00 00 FE"]
    return ops


def link_ops(id5, mode):
    # FUN_0001755c: ID regs 3..7 under reg0 bit7 (FUN_00016850), hop words (FUN_00016896), reg0 bit0 pulse
    ops = ["M link start", "RMW 00 80 FF"] + [f"W {3 + i:02X} {v:02X}" for i, v in enumerate(id5)] + ["RMW 00 00 7F"]
    ops += [f"W {r} {v:02X}" for r, v in BAND24[:5]] + ["RMW 00 01 FF", "RMW 00 00 FE"]
    return ops


def frame_ops(k, rec, idb, first):
    ops = [f"M frame {k}", f"S {2500000}", f"D {MCU_CYC['mr0']}", "R c5", "R c6", "R d9", "R da", "R ea",
           f"D {MCU_CYC['mr1'] - MCU_CYC['mr0']}"]
    if first:      # FUN_00016ef6 band switch (radio regs 0x004/0x005 bridged), FUN_00016166 mode bits
        ops += ["RMW 00 01 FF", "W 01 01", "X 80 04 03", "W 01 02", "W 01 01", "X 80 05 11", "W 01 02"] + [f"W {r} {v:02X}" for r, v in BAND24] + ["RMW 00 00 FE"]
        ops += ["RMW 9d 40 3F", "RMW 8c E0 FF"]
    ops += [f"W {r} {v:02X}" for r, v in BAND24[:5]]            # FUN_0001625e per-hop words (table values U: band words reused)
    ops += [f"D {MCU_CYC['mr2'] - MCU_CYC['mr1']}"]
    ops += [f"R {r}" for r in ("e0", "e1", "e2", "e7", "e8", "e9", "eb", "ee", "ef", "d0", "d1", "c0", "c8", "c9", "ca", "cb", "cc", "cd", "ce", "cf")]
    ops += ["RMW 00 80 FF"] + [f"W {0x40 + i:02X} {idb[i]:02X}" for i in range(4)] + [f"W {0x7C + i:02X} {idb[4 + i]:02X}" for i in range(4)]
    ops += [f"W {0x44 + i:02X} {rec[i]:02X}" for i in range(0x38)] + ["RMW 00 00 7F"]
    ops += ["R e3", "R e4", "R e5", "R e6", "RMW 00 02 FF", "RMW 00 00 FD"]     # peer-ID check fails without a link -> FUN_00015cfa toggle
    ops += [f"W {r} {v:02X}" for r, v in BAND24[5:]] + ["W 23 00"] + [f"W {0xB5 + i:02X} {v:02X}" for i, (_r, v) in enumerate(BAND24[5:])]   # FUN_00016414
    if first:
        ops += ["W 9f 00"]
    return ops


def shadow_rmw(ops):
    """RMW -> plain W from the MCU-side value last written (sim readback of reg 0 returns a rotating bit, not the register; #189)."""
    sh, out = {}, []
    for o in ops:
        f = o.split()
        if f[0] == "X" and f[1] == "0E":
            sh[int(f[2], 16)] = int(f[3], 16)
        elif f[0] == "W":
            sh[int(f[1], 16)] = int(f[2], 16)
        elif f[0] == "RMW":
            r, orv, andv = int(f[1], 16), int(f[2], 16), int(f[3], 16)
            v = (sh.get(r, 0) & andv) | orv
            sh[r] = v
            o = f"W {r:02X} {v:02X}"
        out.append(o)
    return out


def cmd_stim(a):
    id5 = bytes([0x12, 0x34, 0x56, 0x78, 0x9A])
    idb = UR.build_id_block(bytes([0x12, 0x34, 0x56, 0x78, 0x00, 0x01, 0x02]), 3)
    key = bytes(range(1, 9))
    tmpl = bytes([0x01, 0x12, 0x34, 0x56, 0x78] + [0] * 10) + bytes(2) + bytes([0x80, 0x00] * 5) + bytes([23]) + bytes(0x38 - 0x1C)
    ops = boot_ops(a.mode, a.radio) + link_ops(id5, 3)
    if a.rx_after_boot:
        ops.append("RXSTART")
    for k in range(a.frames):
        chunk = UR.duml_frame(0x09, 0x0C, bytes([0xA5, 0x5A, k, 0xC3]))[:23]
        rec = UR.build_record(tmpl, chunk, k + 1, key, scramble=not a.no_scramble)
        ops += frame_ops(k, rec, idb, k == 0)
    ops.append("END")
    ops = shadow_rmw(ops)
    p = os.path.join(OUT, a.out)
    open(p, "w").write("\n".join(ops) + "\n")
    log.info("stim -> %s (%d ops, %d frames, boot table %s)", p, len(ops), a.frames, a.mode)


def cmd_run(a):
    args = [os.path.join(OUT, "obj_loop", "Vtb"), f"+tag={a.tag}", f"+cyc={a.cyc}"]
    if a.stim:
        args.append(f"+stim={os.path.abspath(a.stim)}")
    if a.rx:
        args.append(f"+rx={os.path.abspath(a.rx)}")
    if a.pllc_half:
        args.append(f"+pllc_half={a.pllc_half}")
    if a.sync:
        args.append(f"+sync={a.sync}")
    if a.force is not None:
        args.append(f"+force={a.force}")
    log.info("RUN %s: %s", a.tag, " ".join(args[1:]))
    rc, s, rss, last, out = IS.sh(args, "run_" + a.tag, a.run_limit)
    log.info("SIM %s: rc=%s %.1fs wall, peak RSS %.0f MB, last=%r cycles/s=%.0f", a.tag, rc, s, rss, last[-120:], a.cyc / s if s else 0)


# ----------------------------------------------------------------------------------------------------------------------------- analysis
def read_changes(path, width):
    rows = []
    for line in open(path):
        t, v = line.split()
        rows.append((int(t), int(v, 16)))
    return rows


def bit(v, i):
    return (v >> i) & 1


def cmd_analyse(a):
    meta = json.load(open(os.path.join(OUT, "tb_meta.json")))
    outs = meta["outs"]
    idx = {b: len(outs) - 1 - i for i, b in enumerate(outs)}        # outv = {pad0, pad1, ...}: pad0 is the MSB
    rows = read_changes(os.path.join(OUT, f"out_{a.tag}.txt"), len(outs))
    log.info("analyse %s: %d output-change rows, %d output pads", a.tag, len(rows), len(outs))
    # per-pad toggle counts
    tog = collections.Counter()
    prev = None
    for t, v in rows:
        if prev is not None:
            d = v ^ prev
            for b in outs:
                if bit(d, idx[b]):
                    tog[b] += 1
        prev = v
    log.info("toggles per pad: %s", {b: tog[b] for b in outs if tog[b]})
    # AC8 bursts (TX gate)
    gate = [(t, bit(v, idx["AC8"])) for t, v in rows]
    bursts, on = [], None
    last = None
    for t, g in gate:
        if g != last:
            if g:
                on = t
            elif on is not None:
                bursts.append((on, t))
            last = g
    log.info("AC8 high intervals (half-cycles @100 MHz; /200 = us): %s", [(s, e, (e - s) / 200.0) for s, e in bursts[:12]])
    if len(bursts) > 1:
        log.info("AC8 period(s) us: %s", [((bursts[i + 1][0] - bursts[i][0]) / 200.0) for i in range(min(8, len(bursts) - 1))])
    # TX word stream: sample the 12 TXD pads at every change row; a "word" = the 12-bit value, with R25 (frame candidate) and R22 (clk candidate)
    txb = sorted(TX_PADS, key=lambda b: TX_PADS[b])
    words = []
    for t, v in rows:
        w = sum(bit(v, idx[b]) << TX_PADS[b] for b in txb)
        words.append((t, w, bit(v, idx["R25"]), bit(v, idx["R22"]), bit(v, idx["AC8"])))
    # distinct TX words inside AC8 bursts
    inb = [w for w in words if w[4]]
    vals = collections.Counter(w[1] for w in inb)
    log.info("TX rows inside AC8 bursts: %d, distinct 12-bit words: %d, top: %s", len(inb), len(vals), vals.most_common(8))
    # change cadence of TXD inside bursts
    tt = [w[0] for w in inb]
    if len(tt) > 2:
        d = collections.Counter(tt[i + 1] - tt[i] for i in range(len(tt) - 1))
        log.info("TXD change spacing (half-cycles) histogram top: %s", d.most_common(6))
    # per-bit toggle inside bursts (bit order evidence: MSB/sign toggles least for small signals)
    bt = collections.Counter()
    for i in range(1, len(inb)):
        d = inb[i][1] ^ inb[i - 1][1]
        for k in range(12):
            if bit(d, k):
                bt[k] += 1
    log.info("TXD per-bit toggles inside bursts (draft bit labels): %s", dict(sorted(bt.items())))
    samples = [(t, w, f) for t, w, f, _c, g in words if g]
    json.dump(dict(bursts=bursts, n_rows=len(rows), toggles=dict(tog), tx_samples=samples[:200000], bit_toggles=dict(bt)),
              open(os.path.join(OUT, f"analysis_{a.tag}.json"), "w"))
    log.info("-> %s", os.path.join(OUT, f"analysis_{a.tag}.json"))
    try:
        import numpy as np
        if len(samples) > 64:
            w = np.array([s[1] for s in samples], dtype=np.int64)
            w = np.where(w >= 2048, w - 4096, w)       # two's complement 12-bit (UG-570)
            f = np.array([s[2] for s in samples])
            log.info("TX words: n=%d mean=%.1f std=%.1f min=%d max=%d; R25 duty inside bursts=%.3f", w.size, w.mean(), w.std(), w.min(), w.max(), f.mean())
            # I/Q split by R25 (frame candidate) phase
            if 0.2 < f.mean() < 0.8:
                I, Q = w[f == 1], w[f == 0]
                n = min(I.size, Q.size)
                z = I[:n] + 1j * Q[:n]
                ac = np.abs(np.fft.ifft(np.abs(np.fft.fft(z - z.mean(), 1 << int(np.ceil(np.log2(2 * n))))) ** 2))[:n // 2]
                pk = int(np.argmax(ac[8:]) + 8)
                log.info("I/Q by R25: n=%d, |autocorr| peak lag (>=8) = %d samples, ratio to lag0 = %.3f", n, pk, ac[pk] / ac[0])
                spec = np.abs(np.fft.fftshift(np.fft.fft(z - z.mean())))
                occ = spec > spec.max() * 0.1
                log.info("I/Q spectrum: occupied fraction of bins (> -20 dB of peak) = %.3f", occ.mean())
    except ImportError:
        log.info("numpy missing: no sample statistics")


def cmd_rxgen(a):
    """RX stimulus: 16-bit words, one per DATA_CLK edge (DDR). [11:0] data, [12] frame (high for the I1/Q1 half of each 2R2T sample)."""
    import numpy as np
    if a.source == "loopback":
        an = json.load(open(os.path.join(OUT, f"analysis_{a.tag}.json")))
        ws = [w for _t, w, _f in an["tx_samples"]]
        words = []
        for i, w in enumerate(ws):          # 1R word stream -> 2R2T: I1,Q1,I2,Q2 with both channels equal; frame high on I1/Q1
            words.append(w | ((i % 2 == 0) << 12))
        out = [f"{w:04x}" for w in words]
    else:
        # real downlink capture: int16 IQ @ fs -> mix to the burst centre, LPF, resample to 11.2 MS/s, 12-bit two's complement
        fs = a.fs
        x = np.fromfile(a.capture, dtype="<i2", count=2 * a.nsamp, offset=a.offset * 4).astype(np.float32).reshape(-1, 2)
        z = (x[:, 0] + 1j * x[:, 1]).astype(np.complex64)
        z -= z.mean()
        n = np.arange(z.size)
        y = z * np.exp(-2j * np.pi * a.fc / fs * n).astype(np.complex64)
        from scipy import signal
        taps = signal.firwin(255, min(0.98, 0.6 * a.bw / (fs / 2) + 0.02))
        y = signal.lfilter(taps, 1.0, y).astype(np.complex64)[127:]
        up, down = 11200000, int(fs)
        g = np.gcd(up, down)
        y = signal.resample_poly(y, up // g, down // g).astype(np.complex64)
        pk = np.percentile(np.abs(y), 99.9) + 1e-9
        y = y / pk * 1800.0                        # ~-1.1 dBFS at the 99.9th percentile; 12-bit full scale 2047
        I = np.clip(np.round(y.real), -2048, 2047).astype(np.int64) & 0xFFF
        Q = np.clip(np.round(y.imag), -2048, 2047).astype(np.int64) & 0xFFF
        words = []
        for i in range(I.size):                    # 2R2T DDR: I1 Q1 I2 Q2 (both channels the same stream), frame high for I1/Q1
            words += [int(I[i]) | (1 << 12), int(Q[i]) | (1 << 12), int(I[i]), int(Q[i])]
        out = [f"{w:04x}" for w in words]
        log.info("rxgen capture: %d complex samples in, %d at 11.2 MS/s, %d DDR words (%.2f ms of DATA_CLK)", z.size, I.size, len(out), len(out) / 44.8e3)
    p = os.path.join(OUT, a.out)
    open(p, "w").write("\n".join(out) + "\n")
    log.info("rx stimulus -> %s (%d words)", p, len(out))


def cmd_probes(a):
    meta = json.load(open(os.path.join(OUT, "tb_meta.json")))
    rows = read_changes(os.path.join(OUT, f"probe_{a.tag}.txt"), 512)
    # widths: PROBE_FFS known, PROBE_REGS from rtl_s.v declarations
    widths = []
    decl = {}
    for line in open(os.path.join(a.work, "rtl_s.v")):
        m = re.match(r"\s*reg \[(\d+):0\] (\w+) ", line)
        if m:
            decl[m.group(2)] = int(m.group(1)) + 1
        if line.startswith("assign") or len(decl) > 5000:
            break
    for name, w in meta["probes"]:
        widths.append((name, w if w else decl[name]))
    total = sum(w for _n, w in widths)
    fields = {}
    pos = total
    for name, w in widths:
        pos -= w
        fields[name] = (pos, w)
    log.info("probe fields: %s", fields)
    def fv(v, name):
        p, w = fields[name]
        return (v >> p) & ((1 << w) - 1)
    firsts, lasts, nchg = {}, {}, collections.Counter()
    prev = None
    for t, v in rows:
        for name in fields:
            x = fv(v, name)
            if prev is None or fv(prev, name) != x:
                nchg[name] += 1
                firsts.setdefault(name, (t, x))
                lasts[name] = (t, x)
        prev = v
    for name in fields:
        log.info("probe %-8s changes=%-7d first=%s last=%s", name, nchg[name], firsts.get(name), lasts.get(name))
    # AC11 UART bytes: decode from the output trace (391 clk_main per bit = 782 half-cycles)
    outs = meta["outs"]
    idx = {b: len(outs) - 1 - i for i, b in enumerate(outs)}
    orows = read_changes(os.path.join(OUT, f"out_{a.tag}.txt"), len(outs))
    for pad in ("AC11", "AC10"):
        edges = []
        last = None
        for t, v in orows:
            b = bit(v, idx[pad])
            if b != last:
                edges.append((t, b))
                last = b
        bytes_out = []
        i = 0
        while i < len(edges):
            t, b = edges[i]
            if b == 0 and (i == 0 or edges[i - 1][1] == 1) and i > 0:     # start bit (falling edge from idle high)
                val = 0
                for k in range(8):
                    ts = t + 782 * (k + 1) + 391
                    lvl = 1
                    for tt, bb in edges:
                        if tt <= ts:
                            lvl = bb
                        else:
                            break
                    val |= lvl << k
                bytes_out.append((t, val))
                while i + 1 < len(edges) and edges[i + 1][0] < t + 782 * 10:
                    i += 1
            i += 1
        log.info("%s: %d edges, %d UART bytes @256000: %s", pad, len(edges), len(bytes_out), " ".join(f"{v:02x}" for _t, v in bytes_out[:64]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "stim", "run", "analyse", "rxgen", "probes"])
    ap.add_argument("--work", default=os.path.join(REPO, "tmp", "image_sim_dji_push"))
    ap.add_argument("--tag", default="tx")
    ap.add_argument("--stim")
    ap.add_argument("--rx")
    ap.add_argument("--cyc", type=int, default=2000000)
    ap.add_argument("--pllc-half", type=int, default=0)
    ap.add_argument("--sync", default="")
    ap.add_argument("--force", type=int, help="index into FORCE_TARGETS: per-frame bypass pulse")
    ap.add_argument("--run-limit", type=int, default=3600)
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--mode", default="mode3")
    ap.add_argument("--radio", action="store_true", help="replay the 2607 bridged AD9363 writes too (3 SPI frames each)")
    ap.add_argument("--no-scramble", action="store_true")
    ap.add_argument("--rx-after-boot", action="store_true", help="RXSTART after link start (before the first frame)")
    ap.add_argument("--out", default="stim_tx.txt")
    ap.add_argument("--source", choices=["loopback", "capture"], default="loopback")
    ap.add_argument("--capture")
    ap.add_argument("--fs", type=float, default=120e6)
    ap.add_argument("--fc", type=float, default=0.0, help="burst centre offset from capture centre, Hz")
    ap.add_argument("--bw", type=float, default=10e6)
    ap.add_argument("--nsamp", type=int, default=1 << 21)
    ap.add_argument("--offset", type=int, default=0, help="complex samples to skip")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    IS.log = log
    {"build": cmd_build, "stim": cmd_stim, "run": cmd_run, "analyse": cmd_analyse, "rxgen": cmd_rxgen, "probes": cmd_probes}[a.cmd](a)


if __name__ == "__main__":
    main()
