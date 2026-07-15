// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Thu Jul 16 00:13:51 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(1[24:27])
    output out0;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(1[40:44])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(1[24:27])
    
    wire GND_net, out0_c;
    wire [7:0]o;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(2[26:27])
    
    wire a, out0_N_1, n15, VCC_net, n14;
    
    VHI i17 (.Z(VCC_net));
    LUT4 i6_4_lut (.A(o[1]), .B(o[7]), .C(o[2]), .D(o[3]), .Z(n15)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(16[34:40])
    defparam i6_4_lut.init = 16'h6996;
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(1[40:44])
    EFB u0 (.WBCLKI(clk_c), .WBRSTI(GND_net), .WBCYCI(GND_net), .WBSTBI(GND_net), 
        .WBWEI(GND_net), .WBADRI0(GND_net), .WBADRI1(GND_net), .WBADRI2(GND_net), 
        .WBADRI3(GND_net), .WBADRI4(GND_net), .WBADRI5(GND_net), .WBADRI6(GND_net), 
        .WBADRI7(GND_net), .WBDATI0(GND_net), .WBDATI1(GND_net), .WBDATI2(GND_net), 
        .WBDATI3(GND_net), .WBDATI4(GND_net), .WBDATI5(GND_net), .WBDATI6(GND_net), 
        .WBDATI7(GND_net), .I2C1SCLI(GND_net), .I2C1SDAI(GND_net), .I2C2SCLI(GND_net), 
        .I2C2SDAI(GND_net), .SPISCKI(GND_net), .SPIMISOI(GND_net), .SPIMOSII(GND_net), 
        .SPISCSN(GND_net), .TCCLKI(GND_net), .TCRSTN(GND_net), .TCIC(GND_net), 
        .PLL0DATI0(GND_net), .PLL0DATI1(GND_net), .PLL0DATI2(GND_net), 
        .PLL0DATI3(GND_net), .PLL0DATI4(GND_net), .PLL0DATI5(GND_net), 
        .PLL0DATI6(GND_net), .PLL0DATI7(GND_net), .PLL0ACKI(GND_net), 
        .PLL1DATI0(GND_net), .PLL1DATI1(GND_net), .PLL1DATI2(GND_net), 
        .PLL1DATI3(GND_net), .PLL1DATI4(GND_net), .PLL1DATI5(GND_net), 
        .PLL1DATI6(GND_net), .PLL1DATI7(GND_net), .PLL1ACKI(GND_net), 
        .WBDATO0(o[0]), .WBDATO1(o[1]), .WBDATO2(o[2]), .WBDATO3(o[3]), 
        .WBDATO4(o[4]), .WBDATO5(o[5]), .WBDATO6(o[6]), .WBDATO7(o[7]), 
        .WBACKO(a)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.EFB_I2C1 = "DISABLED";
    defparam u0.EFB_I2C2 = "DISABLED";
    defparam u0.EFB_SPI = "ENABLED";
    defparam u0.EFB_TC = "DISABLED";
    defparam u0.EFB_TC_PORTMODE = "NO_WB";
    defparam u0.EFB_UFM = "DISABLED";
    defparam u0.EFB_WB_CLK_FREQ = "100.0";
    defparam u0.DEV_DENSITY = "1200L";
    defparam u0.UFM_INIT_PAGES = 0;
    defparam u0.UFM_INIT_START_PAGE = 0;
    defparam u0.UFM_INIT_ALL_ZEROS = "ENABLED";
    defparam u0.UFM_INIT_FILE_NAME = "NONE";
    defparam u0.UFM_INIT_FILE_FORMAT = "HEX";
    defparam u0.I2C1_ADDRESSING = "7BIT";
    defparam u0.I2C2_ADDRESSING = "7BIT";
    defparam u0.I2C1_SLAVE_ADDR = "0b1000001";
    defparam u0.I2C2_SLAVE_ADDR = "0b1000010";
    defparam u0.I2C1_BUS_PERF = "100kHz";
    defparam u0.I2C2_BUS_PERF = "100kHz";
    defparam u0.I2C1_CLK_DIVIDER = 1;
    defparam u0.I2C2_CLK_DIVIDER = 1;
    defparam u0.I2C1_GEN_CALL = "DISABLED";
    defparam u0.I2C2_GEN_CALL = "DISABLED";
    defparam u0.I2C1_WAKEUP = "DISABLED";
    defparam u0.I2C2_WAKEUP = "DISABLED";
    defparam u0.SPI_MODE = "SLAVE";
    defparam u0.SPI_CLK_DIVIDER = 1;
    defparam u0.SPI_LSB_FIRST = "DISABLED";
    defparam u0.SPI_CLK_INV = "DISABLED";
    defparam u0.SPI_PHASE_ADJ = "DISABLED";
    defparam u0.SPI_SLAVE_HANDSHAKE = "DISABLED";
    defparam u0.SPI_INTR_TXRDY = "DISABLED";
    defparam u0.SPI_INTR_RXRDY = "DISABLED";
    defparam u0.SPI_INTR_TXOVR = "DISABLED";
    defparam u0.SPI_INTR_RXOVR = "DISABLED";
    defparam u0.SPI_WAKEUP = "DISABLED";
    defparam u0.TC_MODE = "CTCM";
    defparam u0.TC_SCLK_SEL = "PCLOCK";
    defparam u0.TC_CCLK_SEL = 1;
    defparam u0.GSR = "ENABLED";
    defparam u0.TC_TOP_SET = 65535;
    defparam u0.TC_OCR_SET = 32767;
    defparam u0.TC_OC_MODE = "TOGGLE";
    defparam u0.TC_RESETN = "ENABLED";
    defparam u0.TC_TOP_SEL = "ON";
    defparam u0.TC_OV_INT = "OFF";
    defparam u0.TC_OCR_INT = "OFF";
    defparam u0.TC_ICR_INT = "OFF";
    defparam u0.TC_OVERFLOW = "ENABLED";
    defparam u0.TC_ICAPTURE = "DISABLED";
    LUT4 i8_4_lut (.A(n15), .B(o[6]), .C(n14), .D(a), .Z(out0_N_1)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(16[34:40])
    defparam i8_4_lut.init = 16'h6996;
    VLO i1 (.Z(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    TSALL TSALL_INST (.TSALL(GND_net));
    LUT4 i5_3_lut (.A(o[0]), .B(o[4]), .C(o[5]), .Z(n14)) /* synthesis lut_function=(A (B (C)+!B !(C))+!A !(B (C)+!B !(C))) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(16[34:40])
    defparam i5_3_lut.init = 16'h9696;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(1[24:27])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX r_7 (.D(out0_N_1), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_efb_00100_S/fuzz.v(16[16:41])
    defparam r_7.GSR = "ENABLED";
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

