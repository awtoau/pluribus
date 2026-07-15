// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Wed Jul 15 23:37:43 2026
//
// Verilog Description of module fuzz
//

module fuzz (sck, cs_n, miso) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(2[8:12])
    input sck;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(3[17:20])
    input cs_n;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(4[17:21])
    output miso;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(5[17:21])
    
    wire sck_c /* synthesis SET_AS_NETWORK=sck_c, is_clock=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(3[17:20])
    
    wire GND_net, VCC_net, cs_n_c, miso_c_3;
    wire [5:0]cnt;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(8[15:18])
    
    wire n22, n23, n24, n25, n84, n83;
    
    VHI i2 (.Z(VCC_net));
    IB cs_n_pad (.I(cs_n), .O(cs_n_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(4[17:21])
    FD1S3IX cnt_14_51__i4 (.D(n22), .CK(sck_c), .CD(cs_n_c), .Q(cnt[3])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(11[26:36])
    defparam cnt_14_51__i4.GSR = "ENABLED";
    GSR GSR_INST (.GSR(VCC_net));
    TSALL TSALL_INST (.TSALL(GND_net));
    IB sck_pad (.I(sck), .O(sck_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(3[17:20])
    OB miso_pad (.I(miso_c_3), .O(miso));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(5[17:21])
    LUT4 sub_11_inv_0_i4_1_lut (.A(cnt[3]), .Z(miso_c_3)) /* synthesis lut_function=(!(A)) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(13[25:36])
    defparam sub_11_inv_0_i4_1_lut.init = 16'h5555;
    FD1S3IX cnt_14_51__i1 (.D(n25), .CK(sck_c), .CD(cs_n_c), .Q(cnt[0])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(11[26:36])
    defparam cnt_14_51__i1.GSR = "ENABLED";
    FD1S3IX cnt_14_51__i3 (.D(n23), .CK(sck_c), .CD(cs_n_c), .Q(cnt[2])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(11[26:36])
    defparam cnt_14_51__i3.GSR = "ENABLED";
    FD1S3IX cnt_14_51__i2 (.D(n24), .CK(sck_c), .CD(cs_n_c), .Q(cnt[1])) /* synthesis syn_use_carry_chain=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(11[26:36])
    defparam cnt_14_51__i2.GSR = "ENABLED";
    VLO i1 (.Z(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    CCU2D cnt_14_51_add_4_5 (.A0(cnt[3]), .B0(GND_net), .C0(GND_net), 
          .D0(GND_net), .A1(GND_net), .B1(GND_net), .C1(GND_net), .D1(GND_net), 
          .CIN(n84), .S0(n22));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(11[26:36])
    defparam cnt_14_51_add_4_5.INIT0 = 16'hfaaa;
    defparam cnt_14_51_add_4_5.INIT1 = 16'h0000;
    defparam cnt_14_51_add_4_5.INJECT1_0 = "NO";
    defparam cnt_14_51_add_4_5.INJECT1_1 = "NO";
    CCU2D cnt_14_51_add_4_3 (.A0(cnt[1]), .B0(GND_net), .C0(GND_net), 
          .D0(GND_net), .A1(cnt[2]), .B1(GND_net), .C1(GND_net), .D1(GND_net), 
          .CIN(n83), .COUT(n84), .S0(n24), .S1(n23));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(11[26:36])
    defparam cnt_14_51_add_4_3.INIT0 = 16'hfaaa;
    defparam cnt_14_51_add_4_3.INIT1 = 16'hfaaa;
    defparam cnt_14_51_add_4_3.INJECT1_0 = "NO";
    defparam cnt_14_51_add_4_3.INJECT1_1 = "NO";
    CCU2D cnt_14_51_add_4_1 (.A0(GND_net), .B0(GND_net), .C0(GND_net), 
          .D0(GND_net), .A1(cnt[0]), .B1(GND_net), .C1(GND_net), .D1(GND_net), 
          .COUT(n83), .S1(n25));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_cfgspi_ff00/fuzz.v(11[26:36])
    defparam cnt_14_51_add_4_1.INIT0 = 16'hF000;
    defparam cnt_14_51_add_4_1.INIT1 = 16'h0555;
    defparam cnt_14_51_add_4_1.INJECT1_0 = "NO";
    defparam cnt_14_51_add_4_1.INJECT1_1 = "NO";
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

