// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 08:19:43 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(2[16:19])
    
    wire GND_net, out0_c;
    wire [7:0]doa_w;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(7[12:17])
    
    wire out0_N_1, VCC_net, n14, n10;
    
    VHI i16 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(3[17:21])
    DP8KC u0 (.DIA0(GND_net), .DIA1(GND_net), .DIA2(GND_net), .DIA3(GND_net), 
          .DIA4(GND_net), .DIA5(GND_net), .DIA6(GND_net), .DIA7(GND_net), 
          .DIA8(GND_net), .ADA0(GND_net), .ADA1(GND_net), .ADA2(GND_net), 
          .ADA3(GND_net), .ADA4(GND_net), .ADA5(GND_net), .ADA6(GND_net), 
          .ADA7(GND_net), .ADA8(GND_net), .ADA9(GND_net), .ADA10(GND_net), 
          .ADA11(GND_net), .ADA12(GND_net), .CEA(GND_net), .OCEA(GND_net), 
          .CLKA(clk_c), .WEA(GND_net), .CSA0(GND_net), .CSA1(GND_net), 
          .CSA2(GND_net), .RSTA(GND_net), .DIB0(GND_net), .DIB1(GND_net), 
          .DIB2(GND_net), .DIB3(GND_net), .DIB4(GND_net), .DIB5(GND_net), 
          .DIB6(GND_net), .DIB7(GND_net), .DIB8(GND_net), .ADB0(GND_net), 
          .ADB1(GND_net), .ADB2(GND_net), .ADB3(GND_net), .ADB4(GND_net), 
          .ADB5(GND_net), .ADB6(GND_net), .ADB7(GND_net), .ADB8(GND_net), 
          .ADB9(GND_net), .ADB10(GND_net), .ADB11(GND_net), .ADB12(GND_net), 
          .CEB(GND_net), .OCEB(GND_net), .CLKB(clk_c), .WEB(GND_net), 
          .CSB0(GND_net), .CSB1(GND_net), .CSB2(GND_net), .RSTB(GND_net), 
          .DOA0(doa_w[0]), .DOA1(doa_w[1]), .DOA2(doa_w[2]), .DOA3(doa_w[3]), 
          .DOA4(doa_w[4]), .DOA5(doa_w[5]), .DOA6(doa_w[6]), .DOA7(doa_w[7])) /* synthesis syn_instantiated=1 */ ;
    defparam u0.DATA_WIDTH_A = 9;
    defparam u0.DATA_WIDTH_B = 9;
    defparam u0.REGMODE_A = "NOREG";
    defparam u0.REGMODE_B = "NOREG";
    defparam u0.CSDECODE_A = "0b111";
    defparam u0.CSDECODE_B = "0b111";
    defparam u0.WRITEMODE_A = "NORMAL";
    defparam u0.WRITEMODE_B = "NORMAL";
    defparam u0.GSR = "DISABLED";
    defparam u0.RESETMODE = "SYNC";
    defparam u0.ASYNC_RESET_RELEASE = "SYNC";
    defparam u0.INIT_DATA = "STATIC";
    defparam u0.INITVAL_00 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_01 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_02 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_03 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_04 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_05 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_06 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_07 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_08 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_09 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_0A = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_0B = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_0C = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_0D = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_0E = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_0F = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_10 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_11 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_12 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_13 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_14 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_15 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_16 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_17 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_18 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_19 = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_1A = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_1B = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_1C = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_1D = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_1E = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    defparam u0.INITVAL_1F = "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000";
    LUT4 i2_2_lut (.A(doa_w[2]), .B(doa_w[4]), .Z(n10)) /* synthesis lut_function=(!(A (B)+!A !(B))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(32[33:39])
    defparam i2_2_lut.init = 16'h6666;
    LUT4 i7_4_lut (.A(doa_w[0]), .B(n14), .C(n10), .D(doa_w[6]), .Z(out0_N_1)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(32[33:39])
    defparam i7_4_lut.init = 16'h6996;
    VLO i1 (.Z(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    TSALL TSALL_INST (.TSALL(GND_net));
    LUT4 i6_4_lut (.A(doa_w[3]), .B(doa_w[1]), .C(doa_w[5]), .D(doa_w[7]), 
         .Z(n14)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(32[33:39])
    defparam i6_4_lut.init = 16'h6996;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(2[16:19])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_6 (.D(out0_N_1), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_dp8kc_dwa1/fuzz.v(32[8:40])
    defparam out0_r_6.GSR = "ENABLED";
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

