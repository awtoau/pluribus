// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 08:33:08 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(2[16:19])
    
    wire GND_net, out0_c;
    wire [17:0]dout_w;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(7[13:19])
    
    wire out0_N_1, n34, VCC_net, n31, n30, n28, n22, n21;
    
    VHI i16 (.Z(VCC_net));
    LUT4 i10_4_lut (.A(dout_w[1]), .B(dout_w[6]), .C(dout_w[14]), .D(dout_w[11]), 
         .Z(n28)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(25[33:40])
    defparam i10_4_lut.init = 16'h6996;
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(3[17:21])
    PDPW8KC u0 (.DI0(GND_net), .DI1(GND_net), .DI2(GND_net), .DI3(GND_net), 
            .DI4(GND_net), .DI5(GND_net), .DI6(GND_net), .DI7(GND_net), 
            .DI8(GND_net), .DI9(GND_net), .DI10(GND_net), .DI11(GND_net), 
            .DI12(GND_net), .DI13(GND_net), .DI14(GND_net), .DI15(GND_net), 
            .DI16(GND_net), .DI17(GND_net), .ADW0(GND_net), .ADW1(GND_net), 
            .ADW2(GND_net), .ADW3(GND_net), .ADW4(GND_net), .ADW5(GND_net), 
            .ADW6(GND_net), .ADW7(GND_net), .ADW8(GND_net), .BE0(GND_net), 
            .BE1(GND_net), .CEW(GND_net), .CLKW(clk_c), .CSW0(GND_net), 
            .CSW1(GND_net), .CSW2(GND_net), .ADR0(GND_net), .ADR1(GND_net), 
            .ADR2(GND_net), .ADR3(GND_net), .ADR4(GND_net), .ADR5(GND_net), 
            .ADR6(GND_net), .ADR7(GND_net), .ADR8(GND_net), .ADR9(GND_net), 
            .ADR10(GND_net), .ADR11(GND_net), .ADR12(GND_net), .CER(GND_net), 
            .OCER(GND_net), .CLKR(clk_c), .CSR0(GND_net), .CSR1(GND_net), 
            .CSR2(GND_net), .RST(GND_net), .DO0(dout_w[0]), .DO1(dout_w[1]), 
            .DO2(dout_w[2]), .DO3(dout_w[3]), .DO4(dout_w[4]), .DO5(dout_w[5]), 
            .DO6(dout_w[6]), .DO7(dout_w[7]), .DO8(dout_w[8]), .DO9(dout_w[9]), 
            .DO10(dout_w[10]), .DO11(dout_w[11]), .DO12(dout_w[12]), .DO13(dout_w[13]), 
            .DO14(dout_w[14]), .DO15(dout_w[15]), .DO16(dout_w[16]), .DO17(dout_w[17])) /* synthesis syn_instantiated=1 */ ;
    defparam u0.DATA_WIDTH_W = 18;
    defparam u0.DATA_WIDTH_R = 1;
    defparam u0.REGMODE = "NOREG";
    defparam u0.CSDECODE_W = "0b111";
    defparam u0.CSDECODE_R = "0b111";
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
    LUT4 i13_4_lut (.A(dout_w[17]), .B(dout_w[15]), .C(dout_w[16]), .D(dout_w[4]), 
         .Z(n31)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(25[33:40])
    defparam i13_4_lut.init = 16'h6996;
    LUT4 i4_2_lut (.A(dout_w[7]), .B(dout_w[12]), .Z(n22)) /* synthesis lut_function=(!(A (B)+!A !(B))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(25[33:40])
    defparam i4_2_lut.init = 16'h6666;
    LUT4 i12_4_lut (.A(dout_w[3]), .B(dout_w[10]), .C(dout_w[5]), .D(dout_w[0]), 
         .Z(n30)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(25[33:40])
    defparam i12_4_lut.init = 16'h6996;
    LUT4 i16_4_lut (.A(n31), .B(dout_w[9]), .C(n28), .D(dout_w[2]), 
         .Z(n34)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(25[33:40])
    defparam i16_4_lut.init = 16'h6996;
    LUT4 i3_2_lut (.A(dout_w[13]), .B(dout_w[8]), .Z(n21)) /* synthesis lut_function=(!(A (B)+!A !(B))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(25[33:40])
    defparam i3_2_lut.init = 16'h6666;
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    LUT4 i17_4_lut (.A(n21), .B(n34), .C(n30), .D(n22), .Z(out0_N_1)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(25[33:40])
    defparam i17_4_lut.init = 16'h6996;
    VLO i1 (.Z(GND_net));
    TSALL TSALL_INST (.TSALL(GND_net));
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(2[16:19])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_6 (.D(out0_N_1), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ebr_pdpw8kc_wr1_ww18/fuzz.v(25[8:41])
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

