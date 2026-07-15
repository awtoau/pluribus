#!/usr/bin/env python3
"""Mechanically generate RE-focused Diamond fuzz targets — EXHAUSTIVE sweeps.

Fuzzing principle (do NOT violate): sweep the full parameter space, never
prune.  A build that fails or decodes to 0 unknowns is DATA, not waste — it
tells us the vendor/tool did something we didn't predict, which is the whole
point.  Bigger is always better here; targets are cheap.

Families (all auto-discovered by run_all_fuzz.py via iterdir):
  re_ident_*    strategy-2 known-ident SPI readback on ordinary PIO.
  re_cfgspi_*   same, but SPI pins on the sysCONFIG slave-SPI sites (#179).
  re_jtag_*     JTAGF ER1/ER2 bridge (JWBDATO/JTAG disambiguation).
  re_ebr_*      DP8KC + PDPW8KC swept over EVERY DATA_WIDTH x REGMODE x
                WRITEMODE (pluribus#29 EBR.MODE F1B33/34/F1B32).
  re_efb_*      EFB over EVERY i2c1/i2c2/spi/tc/ufm feature combo x SPI_MODE,
                WBDATO wired to fabric (EFB_JF disambiguation, #21/#134/#138).
  re_iostd_*    EVERY BASE_TYPE x PULLMODE x DRIVE on edge pads (#11, #29-4).
  re_edge_*     an output register on EVERY package pin (bottom/right/left/top
                edge routing + CIB — #29-3, #156, #129, the DAC/ADC dead pins).

The EBR/EFB families reuse verified port-lists copied from the existing
corpus templates (dp8kc_x9, pdpw8kc_x18, efb_spi) — only the parameter block
is swept, so the instantiations are always well-formed.
"""
import itertools
from pathlib import Path

TARGETS = Path(__file__).resolve().parents[1] / "targets"

LDF = '''<?xml version="1.0" encoding="UTF-8"?>
<BaliProject version="3.2" title="fuzz" device="LCMXO2-1200HC-5TG100C" default_implementation="impl1">
    <Options/>
    <Implementation title="impl1" dir="impl1" description="impl1" synthesis="lse" default_strategy="Strategy1">
        <Options/>
        <Source name="fuzz.v" type="Verilog" type_short="Verilog"><Options/></Source>
        <Source name="fuzz.lpf" type="Logic Preference" type_short="LPF"><Options/></Source>
    </Implementation>
    <Strategy name="Strategy1" file="../../aw21.sty"/>
</BaliProject>
'''
RUN_TCL = ('prj_project open "[file normalize [file join [file dirname [info script]] fuzz.ldf]]"\n'
           'prj_run PAR    -impl impl1\n'
           'prj_run Export -impl impl1 -task Bitgen\n'
           'prj_project close\n')

def write(name, v, lpf_text):
    d = TARGETS / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "fuzz.v").write_text(v)
    (d / "fuzz.lpf").write_text(lpf_text)
    (d / "fuzz.ldf").write_text(LDF)
    (d / "run.tcl").write_text(RUN_TCL)

def simple_lpf(sites, sysconfig=None):
    out = ["BLOCK RESETPATHS;", "BLOCK ASYNCPATHS;", ""]
    for p, s in sites.items():
        out += [f'LOCATE COMP "{p}" SITE "{s}";', f'IOBUF PORT "{p}" IO_TYPE=LVCMOS33;', ""]
    out.append('FREQUENCY PORT "clk" 100.000000 MHz;' if "clk" in sites
               else 'FREQUENCY PORT "sck" 100.000000 MHz;')
    if sysconfig:
        out += ["", sysconfig]
    return "\n".join(out) + "\n"

N = 0
def emit(name, v, lpf_text):
    global N
    write(name, v, lpf_text); N += 1

# ── ident / cfgspi / jtag (from the first generation) ───────────────────────
def ident_v(hx):
    return (f"module fuzz(input wire sck,input wire cs_n,output wire miso);\n"
            f"  localparam [63:0] IDENT=64'h{hx};\n  reg [5:0] cnt;\n"
            f"  always @(posedge sck) if(cs_n) cnt<=0; else cnt<=cnt+1'b1;\n"
            f"  assign miso=IDENT[6'd63-cnt];\nendmodule\n")
IDENTS = {"counting":"0123456789ABCDEF","a5":"A5A5A5A5A5A5A5A5",
          "ff00":"FF00FF00FF00FF00","adc":"0200010913310785"}
def jtag_v(er1, er2):
    return (f"module fuzz(input wire clk,output wire out0);\n wire g=1'b0;\n"
            f" wire a,b,c,d,e,f;\n JTAGF #(.ER1({er1}),.ER2({er2})) u(.TCK(),.TMS(),.TDI(),"
            f".JTDO1(g),.JTDO2(g),.TDO(),.JTCK(a),.JTDI(b),.JSHIFT(c),.JUPDATE(d),"
            f".JRSTN(e),.JCE1(f),.JCE2(),.JRTI1(),.JRTI2());\n"
            f" reg r; always @(posedge clk) r<=a^b^c^d^e^f; assign out0=r;\nendmodule\n")

# ── EBR: DP8KC + PDPW8KC, exhaustive param sweep ────────────────────────────
DP8KC_PORTS = '''\
) u0 (
    .CLKA(clk),.CEA(g),.OCEA(g),.WEA(g),.CSA2(g),.CSA1(g),.CSA0(g),.RSTA(g),
    .ADA9(g),.ADA8(g),.ADA7(g),.ADA6(g),.ADA5(g),.ADA4(g),.ADA3(g),.ADA2(g),.ADA1(g),.ADA0(g),
    .DIA7(g),.DIA6(g),.DIA5(g),.DIA4(g),.DIA3(g),.DIA2(g),.DIA1(g),.DIA0(g),
    .DOA7(o[7]),.DOA6(o[6]),.DOA5(o[5]),.DOA4(o[4]),.DOA3(o[3]),.DOA2(o[2]),.DOA1(o[1]),.DOA0(o[0]),
    .CLKB(clk),.CEB(g),.OCEB(g),.WEB(g),.CSB2(g),.CSB1(g),.CSB0(g),.RSTB(g),
    .ADB9(g),.ADB8(g),.ADB7(g),.ADB6(g),.ADB5(g),.ADB4(g),.ADB3(g),.ADB2(g),.ADB1(g),.ADB0(g),
    .DIB7(g),.DIB6(g),.DIB5(g),.DIB4(g),.DIB3(g),.DIB2(g),.DIB1(g),.DIB0(g)
);'''
PDPW_PORTS = '''\
) u0 (
    .CLKW(clk),.CEW(g),.CSW2(g),.CSW1(g),.CSW0(g),.RST(g),
    .ADW8(g),.ADW7(g),.ADW6(g),.ADW5(g),.ADW4(g),.ADW3(g),.ADW2(g),.ADW1(g),.ADW0(g),
    .DI17(g),.DI16(g),.DI15(g),.DI14(g),.DI13(g),.DI12(g),.DI11(g),.DI10(g),.DI9(g),
    .DI8(g),.DI7(g),.DI6(g),.DI5(g),.DI4(g),.DI3(g),.DI2(g),.DI1(g),.DI0(g),
    .CLKR(clk),.CER(g),.OCER(g),.CSR2(g),.CSR1(g),.CSR0(g),
    .ADR10(g),.ADR9(g),.ADR8(g),.ADR7(g),.ADR6(g),.ADR5(g),.ADR4(g),.ADR3(g),.ADR2(g),.ADR1(g),.ADR0(g),
    .DO17(o[17]),.DO16(o[16]),.DO15(o[15]),.DO14(o[14]),.DO13(o[13]),.DO12(o[12]),.DO11(o[11]),
    .DO10(o[10]),.DO9(o[9]),.DO8(o[8]),.DO7(o[7]),.DO6(o[6]),.DO5(o[5]),.DO4(o[4]),.DO3(o[3]),
    .DO2(o[2]),.DO1(o[1]),.DO0(o[0])
);'''
def ebr_dp8kc(wa, wb, rega, regb, wma, wmb):
    return (f"module fuzz(input wire clk,output wire out0);\n wire g=1'b0; wire [7:0] o;\n"
            f" DP8KC #(.DATA_WIDTH_A({wa}),.DATA_WIDTH_B({wb}),.REGMODE_A(\"{rega}\"),"
            f".REGMODE_B(\"{regb}\"),.WRITEMODE_A(\"{wma}\"),.WRITEMODE_B(\"{wmb}\"),"
            f".INITVAL_00(\"0x{'0'*80}\")\n"
            f"{DP8KC_PORTS}\n reg r; always @(posedge clk) r<=^o; assign out0=r;\nendmodule\n")
def ebr_pdpw(ww, wr, reg):
    return (f"module fuzz(input wire clk,output wire out0);\n wire g=1'b0; wire [17:0] o;\n"
            f" PDPW8KC #(.DATA_WIDTH_W({ww}),.DATA_WIDTH_R({wr}),.REGMODE(\"{reg}\"),"
            f".INITVAL_00(\"0x{'0'*80}\")\n"
            f"{PDPW_PORTS}\n reg r; always @(posedge clk) r<=^o; assign out0=r;\nendmodule\n")

# ── EFB: exhaustive feature-combo sweep, WBDATO -> fabric ────────────────────
EFB_PORTS = '''\
) u0 (
    .WBCLKI(clk),.WBRSTI(g),.WBCYCI(g),.WBSTBI(g),.WBWEI(g),
    .WBADRI7(g),.WBADRI6(g),.WBADRI5(g),.WBADRI4(g),.WBADRI3(g),.WBADRI2(g),.WBADRI1(g),.WBADRI0(g),
    .WBDATI7(g),.WBDATI6(g),.WBDATI5(g),.WBDATI4(g),.WBDATI3(g),.WBDATI2(g),.WBDATI1(g),.WBDATI0(g),
    .PLL0DATI7(g),.PLL0DATI6(g),.PLL0DATI5(g),.PLL0DATI4(g),.PLL0DATI3(g),.PLL0DATI2(g),.PLL0DATI1(g),.PLL0DATI0(g),.PLL0ACKI(g),
    .PLL1DATI7(g),.PLL1DATI6(g),.PLL1DATI5(g),.PLL1DATI4(g),.PLL1DATI3(g),.PLL1DATI2(g),.PLL1DATI1(g),.PLL1DATI0(g),.PLL1ACKI(g),
    .I2C1SCLI(g),.I2C1SDAI(g),.I2C2SCLI(g),.I2C2SDAI(g),
    .SPISCKI(g),.SPIMISOI(g),.SPIMOSII(g),.SPISCSN(g),
    .TCCLKI(g),.TCRSTN(g),.TCIC(g),.UFMSN(g),
    .WBDATO7(o[7]),.WBDATO6(o[6]),.WBDATO5(o[5]),.WBDATO4(o[4]),
    .WBDATO3(o[3]),.WBDATO2(o[2]),.WBDATO1(o[1]),.WBDATO0(o[0]),.WBACKO(a)
);'''
def efb(i2c1, i2c2, spi, tc, ufm, spi_mode):
    def e(b): return '"ENABLED"' if b else '"DISABLED"'
    return (f"module fuzz(input wire clk,output wire out0);\n wire g=1'b0; wire [7:0] o; wire a;\n"
            f" EFB #(.EFB_I2C1({e(i2c1)}),.EFB_I2C2({e(i2c2)}),.EFB_SPI({e(spi)}),"
            f".EFB_TC({e(tc)}),.EFB_UFM({e(ufm)}),.SPI_MODE(\"{spi_mode}\"),.EFB_WB_CLK_FREQ(\"100.0\")\n"
            f"{EFB_PORTS}\n reg r; always @(posedge clk) r<=a^(^o); assign out0=r;\nendmodule\n")

# ── IO standards: exhaustive BASE_TYPE x PULLMODE x DRIVE on edge pads ───────
# Package pin sites spanning all four edges (from aw2-pins.tsv range).
EDGE_PINS = ["36","38","42","43","45","51","53","60","61","62","63","64","65",
             "66","67","70","74","83","84","85","86","87","88","96","97","98","99",
             "27","2","3","4","8","9","10"]
IOSTD = ["LVCMOS33","LVCMOS25","LVCMOS18","LVCMOS15","LVCMOS12","LVTTL33",
         "SSTL25_I","SSTL25_II","SSTL18_I","SSTL18_II","SSTL15","HSTL18_I",
         "HSTL18_II","HSTL15_I","LVDS25","MLVDS25","LVPECL33","BLVDS25",
         "MIPI","PCI33","LVCMOS33D","LVCMOS25D"]
PULL = ["UP","DOWN","NONE","FAILSAFE"]
DRIVE = ["4","8","12","16"]

def io_v(direction):
    if direction == "out":
        return "module fuzz(input wire clk,output wire d);\n reg t; always @(posedge clk) t<=~t; assign d=t;\nendmodule\n"
    return "module fuzz(input wire clk,input wire d,output wire q);\n reg t; always @(posedge clk) t<=d; assign q=t;\nendmodule\n"

def edge_out_lpf(pin, iotype, pull, drive):
    return ("BLOCK RESETPATHS;\nBLOCK ASYNCPATHS;\n\n"
            'LOCATE COMP "clk" SITE "88";\nIOBUF PORT "clk" IO_TYPE=LVCMOS33;\n\n'
            f'LOCATE COMP "d" SITE "{pin}";\n'
            f'IOBUF PORT "d" IO_TYPE={iotype} PULLMODE={pull} DRIVE={drive};\n\n'
            'FREQUENCY PORT "clk" 100.000000 MHz;\n')

def main():
    print("generating RE fuzz targets (exhaustive):")
    for tag, hx in IDENTS.items():
        emit(f"re_ident_{tag}", ident_v(hx), simple_lpf({"sck":"88","cs_n":"87","miso":"84"}))
        emit(f"re_cfgspi_{tag}", ident_v(hx),
             simple_lpf({"sck":"31","cs_n":"48","miso":"32"}, "SYSCONFIG SLAVE_SPI_PORT=ENABLE ;"))
    for tag,(a,b) in {"er1":('"ENABLED"','"DISABLED"'),"er1er2":('"ENABLED"','"ENABLED"')}.items():
        emit(f"re_jtag_{tag}", jtag_v(a,b), simple_lpf({"clk":"88","out0":"84"}))

    # EBR — every DP8KC width x regmode x writemode
    # DP8KC is a true dual-port 8K x 9 — max 9 bits/port (w18 is PDPW8KC-only
    # and fails elaboration, verified).  Sweep the full VALID domain, no pruning.
    W = [1,2,4,9]; REG=["NOREG","OUTREG"]; WM=["NORMAL","WRITETHROUGH","READBEFOREWRITE"]
    for wa,wb,ra,rb,wma,wmb in itertools.product(W,W,REG,REG,WM,WM):
        emit(f"re_ebr_dp8kc_wa{wa}_wb{wb}_{ra}_{rb}_{wma[:2]}{wmb[:2]}",
             ebr_dp8kc(wa,wb,ra,rb,wma,wmb), simple_lpf({"clk":"88","out0":"84"}))
    # PDPW8KC: write side up to 18, read side up to 9.
    for ww,wr,reg in itertools.product([1,2,4,9,18],[1,2,4,9],REG):
        emit(f"re_ebr_pdpw_ww{ww}_wr{wr}_{reg}", ebr_pdpw(ww,wr,reg),
             simple_lpf({"clk":"88","out0":"84"}))

    # EFB — every feature combo x SPI mode
    for i1,i2,sp,tc,uf in itertools.product([0,1],repeat=5):
        modes = ["SLAVE","MASTER"] if sp else ["SLAVE"]
        for sm in modes:
            tag = f"{i1}{i2}{sp}{tc}{uf}_{sm[0]}"
            emit(f"re_efb_{tag}", efb(i1,i2,sp,tc,uf,sm), simple_lpf({"clk":"88","out0":"84"}))

    # IO standards — every BASE_TYPE x PULLMODE x DRIVE on a representative edge pad,
    # plus every edge pin at the default standard (edge-routing coverage).
    for iotype,pull,drive in itertools.product(IOSTD,PULL,DRIVE):
        emit(f"re_iostd_{iotype}_{pull}_d{drive}", io_v("out"),
             edge_out_lpf("36", iotype, pull, drive))
    for pin in EDGE_PINS:
        emit(f"re_edge_pin{pin}", io_v("out"), edge_out_lpf(pin, "LVCMOS33", "NONE", "8"))

    print(f"done. {N} targets. build with: "
          "python3 diamond-fuzz/scripts/run_all_fuzz.py --targets 're_*' -j 4")

if __name__ == "__main__":
    main()
