// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Wed Jul 15 23:37:43 2026
//
// Verilog Description of module fuzz
//

module fuzz (sck, cs_n, miso) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(2[8:12])
    input sck;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(3[17:20])
    input cs_n;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(4[17:21])
    output miso;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(5[17:21])
    
    wire sck_c /* synthesis SET_AS_NETWORK=sck_c, is_clock=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(3[17:20])
    
    wire GND_net, VCC_net, cs_n_c, miso_c;
    wire [5:0]cnt;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(8[15:18])
    
    wire n18, n19, n20, n75;
    
    VHI i2 (.Z(VCC_net));
    IB sck_pad (.I(sck), .O(sck_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(3[17:20])
    IB cs_n_pad (.I(cs_n), .O(cs_n_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(4[17:21])
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    FD1S3IX cnt_14_42__i3 (.D(n18), .CK(sck_c), .CD(cs_n_c), .Q(cnt[2])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(11[26:36])
    defparam cnt_14_42__i3.GSR = "ENABLED";
    FD1S3IX cnt_14_42__i1 (.D(n20), .CK(sck_c), .CD(cs_n_c), .Q(cnt[0])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(11[26:36])
    defparam cnt_14_42__i1.GSR = "ENABLED";
    GSR GSR_INST (.GSR(VCC_net));
    OB miso_pad (.I(miso_c), .O(miso));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(5[17:21])
    VLO i1 (.Z(GND_net));
    LUT4 i45_2_lut (.A(cnt[0]), .B(cnt[2]), .Z(miso_c)) /* synthesis lut_function=(A (B)+!A !(B)) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(13[25:36])
    defparam i45_2_lut.init = 16'h9999;
    FD1S3IX cnt_14_42__i2 (.D(n19), .CK(sck_c), .CD(cs_n_c), .Q(cnt[1])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(11[26:36])
    defparam cnt_14_42__i2.GSR = "ENABLED";
    CCU2D cnt_14_42_add_4_3 (.A0(cnt[1]), .B0(GND_net), .C0(GND_net), 
          .D0(GND_net), .A1(cnt[2]), .B1(GND_net), .C1(GND_net), .D1(GND_net), 
          .CIN(n75), .S0(n19), .S1(n18));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(11[26:36])
    defparam cnt_14_42_add_4_3.INIT0 = 16'hfaaa;
    defparam cnt_14_42_add_4_3.INIT1 = 16'hfaaa;
    defparam cnt_14_42_add_4_3.INJECT1_0 = "NO";
    defparam cnt_14_42_add_4_3.INJECT1_1 = "NO";
    CCU2D cnt_14_42_add_4_1 (.A0(GND_net), .B0(GND_net), .C0(GND_net), 
          .D0(GND_net), .A1(cnt[0]), .B1(GND_net), .C1(GND_net), .D1(GND_net), 
          .COUT(n75), .S1(n20));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_ident_a5/fuzz.v(11[26:36])
    defparam cnt_14_42_add_4_1.INIT0 = 16'hF000;
    defparam cnt_14_42_add_4_1.INIT1 = 16'h0555;
    defparam cnt_14_42_add_4_1.INJECT1_0 = "NO";
    defparam cnt_14_42_add_4_1.INJECT1_1 = "NO";
    TSALL TSALL_INST (.TSALL(GND_net));
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

