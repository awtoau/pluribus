// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Wed Jul 15 23:03:22 2026
//
// Verilog Description of module fuzz
//

module fuzz (sck, cs_n, miso) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(9[8:12])
    input sck;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(10[17:20])
    input cs_n;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(11[17:21])
    output miso;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(12[17:21])
    
    wire sck_c /* synthesis SET_AS_NETWORK=sck_c, is_clock=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(10[17:20])
    
    wire GND_net, VCC_net, cs_n_c, miso_c;
    wire [5:0]cnt;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(15[15:18])
    
    wire n163, n142, n162, n141, n35, n34, n33, n32, n31, 
        n30, n140;
    
    VHI i2 (.Z(VCC_net));
    IB cs_n_pad (.I(cs_n), .O(cs_n_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(11[17:21])
    CCU2D cnt_24_add_4_7 (.A0(cnt[5]), .B0(GND_net), .C0(GND_net), .D0(GND_net), 
          .A1(GND_net), .B1(GND_net), .C1(GND_net), .D1(GND_net), .CIN(n142), 
          .S0(n30));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(18[26:36])
    defparam cnt_24_add_4_7.INIT0 = 16'hfaaa;
    defparam cnt_24_add_4_7.INIT1 = 16'h0000;
    defparam cnt_24_add_4_7.INJECT1_0 = "NO";
    defparam cnt_24_add_4_7.INJECT1_1 = "NO";
    FD1S3IX cnt_24__i5 (.D(n30), .CK(sck_c), .CD(cs_n_c), .Q(cnt[5])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(18[26:36])
    defparam cnt_24__i5.GSR = "ENABLED";
    FD1S3IX cnt_24__i0 (.D(n35), .CK(sck_c), .CD(cs_n_c), .Q(cnt[0])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(18[26:36])
    defparam cnt_24__i0.GSR = "ENABLED";
    CCU2D cnt_24_add_4_5 (.A0(cnt[3]), .B0(GND_net), .C0(GND_net), .D0(GND_net), 
          .A1(cnt[4]), .B1(GND_net), .C1(GND_net), .D1(GND_net), .CIN(n141), 
          .COUT(n142), .S0(n32), .S1(n31));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(18[26:36])
    defparam cnt_24_add_4_5.INIT0 = 16'hfaaa;
    defparam cnt_24_add_4_5.INIT1 = 16'hfaaa;
    defparam cnt_24_add_4_5.INJECT1_0 = "NO";
    defparam cnt_24_add_4_5.INJECT1_1 = "NO";
    LUT4 i123_then_3_lut (.A(cnt[4]), .B(cnt[1]), .C(cnt[2]), .Z(n163)) /* synthesis lut_function=(A ((C)+!B)+!A (B (C))) */ ;
    defparam i123_then_3_lut.init = 16'he2e2;
    LUT4 i123_else_3_lut (.A(cnt[5]), .B(cnt[3]), .C(cnt[1]), .Z(n162)) /* synthesis lut_function=(A (B+!(C))+!A (B (C))) */ ;
    defparam i123_else_3_lut.init = 16'hcaca;
    CCU2D cnt_24_add_4_1 (.A0(GND_net), .B0(GND_net), .C0(GND_net), .D0(GND_net), 
          .A1(cnt[0]), .B1(GND_net), .C1(GND_net), .D1(GND_net), .COUT(n140), 
          .S1(n35));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(18[26:36])
    defparam cnt_24_add_4_1.INIT0 = 16'hF000;
    defparam cnt_24_add_4_1.INIT1 = 16'h0555;
    defparam cnt_24_add_4_1.INJECT1_0 = "NO";
    defparam cnt_24_add_4_1.INJECT1_1 = "NO";
    FD1S3IX cnt_24__i4 (.D(n31), .CK(sck_c), .CD(cs_n_c), .Q(cnt[4])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(18[26:36])
    defparam cnt_24__i4.GSR = "ENABLED";
    IB sck_pad (.I(sck), .O(sck_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(10[17:20])
    CCU2D cnt_24_add_4_3 (.A0(cnt[1]), .B0(GND_net), .C0(GND_net), .D0(GND_net), 
          .A1(cnt[2]), .B1(GND_net), .C1(GND_net), .D1(GND_net), .CIN(n140), 
          .COUT(n141), .S0(n34), .S1(n33));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(18[26:36])
    defparam cnt_24_add_4_3.INIT0 = 16'hfaaa;
    defparam cnt_24_add_4_3.INIT1 = 16'hfaaa;
    defparam cnt_24_add_4_3.INJECT1_0 = "NO";
    defparam cnt_24_add_4_3.INJECT1_1 = "NO";
    VLO i1 (.Z(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    OB miso_pad (.I(miso_c), .O(miso));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(12[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    FD1S3IX cnt_24__i3 (.D(n32), .CK(sck_c), .CD(cs_n_c), .Q(cnt[3])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(18[26:36])
    defparam cnt_24__i3.GSR = "ENABLED";
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3IX cnt_24__i2 (.D(n33), .CK(sck_c), .CD(cs_n_c), .Q(cnt[2])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(18[26:36])
    defparam cnt_24__i2.GSR = "ENABLED";
    FD1S3IX cnt_24__i1 (.D(n34), .CK(sck_c), .CD(cs_n_c), .Q(cnt[1])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/soft_spi_ident/fuzz.v(18[26:36])
    defparam cnt_24__i1.GSR = "ENABLED";
    PFUMX i134 (.BLUT(n162), .ALUT(n163), .C0(cnt[0]), .Z(miso_c));
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

