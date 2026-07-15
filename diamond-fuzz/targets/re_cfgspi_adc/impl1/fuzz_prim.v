// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Wed Jul 15 23:37:43 2026
//
// Verilog Description of module fuzz
//

module fuzz (sck, cs_n, miso) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(2[8:12])
    input sck;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(3[17:20])
    input cs_n;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(4[17:21])
    output miso;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(5[17:21])
    
    wire sck_c /* synthesis SET_AS_NETWORK=sck_c, is_clock=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(3[17:20])
    
    wire GND_net, VCC_net, cs_n_c, miso_c;
    wire [5:0]cnt;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(8[15:18])
    wire [5:0]miso_N_13;
    
    wire n32, n15, n154, n30, n148, n140, n31, n141, n155, 
        n125, n35, n34, n33, n61, n139;
    
    VHI i2 (.Z(VCC_net));
    IB sck_pad (.I(sck), .O(sck_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(3[17:20])
    PFUMX i126 (.BLUT(n15), .ALUT(n125), .C0(miso_N_13[4]), .Z(n155));
    GSR GSR_INST (.GSR(VCC_net));
    LUT4 i97_4_lut_4_lut (.A(cnt[3]), .B(cnt[0]), .C(cnt[1]), .D(cnt[2]), 
         .Z(n125)) /* synthesis lut_function=(A (B (C)+!B !((D)+!C))+!A (B (C)+!B (C (D)))) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(13[25:36])
    defparam i97_4_lut_4_lut.init = 16'hd0e0;
    LUT4 i1_4_lut_4_lut (.A(cnt[3]), .B(cnt[0]), .C(cnt[1]), .D(cnt[2]), 
         .Z(n148)) /* synthesis lut_function=(A (B (C (D))+!B !(C+!(D)))+!A (B (C (D)))) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(13[25:36])
    defparam i1_4_lut_4_lut.init = 16'hc200;
    IB cs_n_pad (.I(cs_n), .O(cs_n_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(4[17:21])
    LUT4 i106_4_lut_4_lut (.A(cnt[2]), .B(cnt[3]), .C(cnt[1]), .D(cnt[0]), 
         .Z(n61)) /* synthesis lut_function=(!((B+((D)+!C))+!A)) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(13[25:36])
    defparam i106_4_lut_4_lut.init = 16'h0020;
    CCU2D cnt_23_add_4_3 (.A0(cnt[1]), .B0(GND_net), .C0(GND_net), .D0(GND_net), 
          .A1(cnt[2]), .B1(GND_net), .C1(GND_net), .D1(GND_net), .CIN(n139), 
          .COUT(n140), .S0(n34), .S1(n33));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(11[26:36])
    defparam cnt_23_add_4_3.INIT0 = 16'hfaaa;
    defparam cnt_23_add_4_3.INIT1 = 16'hfaaa;
    defparam cnt_23_add_4_3.INJECT1_0 = "NO";
    defparam cnt_23_add_4_3.INJECT1_1 = "NO";
    FD1S3IX cnt_23__i5 (.D(n30), .CK(sck_c), .CD(cs_n_c), .Q(cnt[5])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(11[26:36])
    defparam cnt_23__i5.GSR = "ENABLED";
    PFUMX i125 (.BLUT(n148), .ALUT(n61), .C0(miso_N_13[4]), .Z(n154));
    LUT4 sub_6_inv_0_i5_1_lut (.A(cnt[4]), .Z(miso_N_13[4])) /* synthesis lut_function=(!(A)) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(13[25:36])
    defparam sub_6_inv_0_i5_1_lut.init = 16'h5555;
    CCU2D cnt_23_add_4_7 (.A0(cnt[5]), .B0(GND_net), .C0(GND_net), .D0(GND_net), 
          .A1(GND_net), .B1(GND_net), .C1(GND_net), .D1(GND_net), .CIN(n141), 
          .S0(n30));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(11[26:36])
    defparam cnt_23_add_4_7.INIT0 = 16'hfaaa;
    defparam cnt_23_add_4_7.INIT1 = 16'h0000;
    defparam cnt_23_add_4_7.INJECT1_0 = "NO";
    defparam cnt_23_add_4_7.INJECT1_1 = "NO";
    LUT4 miso_I_0_i15_4_lut_4_lut_4_lut_4_lut (.A(cnt[0]), .B(cnt[1]), .C(cnt[2]), 
         .D(cnt[3]), .Z(n15)) /* synthesis lut_function=(A (C)+!A !(B ((D)+!C)+!B (C+!(D)))) */ ;
    defparam miso_I_0_i15_4_lut_4_lut_4_lut_4_lut.init = 16'ha1e0;
    FD1S3IX cnt_23__i4 (.D(n31), .CK(sck_c), .CD(cs_n_c), .Q(cnt[4])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(11[26:36])
    defparam cnt_23__i4.GSR = "ENABLED";
    FD1S3IX cnt_23__i3 (.D(n32), .CK(sck_c), .CD(cs_n_c), .Q(cnt[3])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(11[26:36])
    defparam cnt_23__i3.GSR = "ENABLED";
    FD1S3IX cnt_23__i2 (.D(n33), .CK(sck_c), .CD(cs_n_c), .Q(cnt[2])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(11[26:36])
    defparam cnt_23__i2.GSR = "ENABLED";
    OB miso_pad (.I(miso_c), .O(miso));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(5[17:21])
    VLO i1 (.Z(GND_net));
    CCU2D cnt_23_add_4_1 (.A0(GND_net), .B0(GND_net), .C0(GND_net), .D0(GND_net), 
          .A1(cnt[0]), .B1(GND_net), .C1(GND_net), .D1(GND_net), .COUT(n139), 
          .S1(n35));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(11[26:36])
    defparam cnt_23_add_4_1.INIT0 = 16'hF000;
    defparam cnt_23_add_4_1.INIT1 = 16'h0555;
    defparam cnt_23_add_4_1.INJECT1_0 = "NO";
    defparam cnt_23_add_4_1.INJECT1_1 = "NO";
    FD1S3IX cnt_23__i1 (.D(n34), .CK(sck_c), .CD(cs_n_c), .Q(cnt[1])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(11[26:36])
    defparam cnt_23__i1.GSR = "ENABLED";
    L6MUX21 i127 (.D0(n154), .D1(n155), .SD(cnt[5]), .Z(miso_c));
    FD1S3IX cnt_23__i0 (.D(n35), .CK(sck_c), .CD(cs_n_c), .Q(cnt[0])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(11[26:36])
    defparam cnt_23__i0.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    TSALL TSALL_INST (.TSALL(GND_net));
    CCU2D cnt_23_add_4_5 (.A0(cnt[3]), .B0(GND_net), .C0(GND_net), .D0(GND_net), 
          .A1(cnt[4]), .B1(GND_net), .C1(GND_net), .D1(GND_net), .CIN(n140), 
          .COUT(n141), .S0(n32), .S1(n31));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_adc/fuzz.v(11[26:36])
    defparam cnt_23_add_4_5.INIT0 = 16'hfaaa;
    defparam cnt_23_add_4_5.INIT1 = 16'hfaaa;
    defparam cnt_23_add_4_5.INJECT1_0 = "NO";
    defparam cnt_23_add_4_5.INJECT1_1 = "NO";
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

