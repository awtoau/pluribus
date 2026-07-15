// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Wed Jul 15 23:37:53 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_jtag_er1er2/fuzz.v(2[8:12])
    input clk;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_jtag_er1er2/fuzz.v(3[17:20])
    output out0;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_jtag_er1er2/fuzz.v(4[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_jtag_er1er2/fuzz.v(3[17:20])
    
    wire GND_net, out0_c, jce1_w, jshift_w, jupdate_w, jrstn_w, 
        jtck_w, jtdi_w, n10, out0_N_1, VCC_net;
    
    VHI i20 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_jtag_er1er2/fuzz.v(4[17:21])
    VLO i1 (.Z(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    LUT4 i4_4_lut (.A(jupdate_w), .B(jshift_w), .C(jce1_w), .D(jtck_w), 
         .Z(n10)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_jtag_er1er2/fuzz.v(16[19:76])
    defparam i4_4_lut.init = 16'h6996;
    TSALL TSALL_INST (.TSALL(GND_net));
    LUT4 i5_3_lut (.A(jtdi_w), .B(n10), .C(jrstn_w), .Z(out0_N_1)) /* synthesis lut_function=(A (B (C)+!B !(C))+!A !(B (C)+!B !(C))) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_jtag_er1er2/fuzz.v(16[19:76])
    defparam i5_3_lut.init = 16'h9696;
    JTAGF u0 (.TCK(GND_net), .TMS(GND_net), .TDI(GND_net), .JTDO1(GND_net), 
          .JTDO2(GND_net), .JTDI(jtdi_w), .JTCK(jtck_w), .JSHIFT(jshift_w), 
          .JUPDATE(jupdate_w), .JRSTN(jrstn_w), .JCE1(jce1_w)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.ER1 = "ENABLED";
    defparam u0.ER2 = "ENABLED";
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_jtag_er1er2/fuzz.v(3[17:20])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_10 (.D(out0_N_1), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_jtag_er1er2/fuzz.v(15[12] 16[77])
    defparam out0_r_10.GSR = "ENABLED";
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

