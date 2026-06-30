// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:35:44 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(2[16:19])
    
    wire GND_net, out0_c;
    wire [17:0]q_w;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(7[13:16])
    
    wire ef_w, ff_w, out0_N_1, n36, VCC_net, n35, n34, n33, 
        n32, n22;
    
    VHI i18 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(3[17:21])
    FIFO8KB u0 (.DI0(GND_net), .DI1(GND_net), .DI2(GND_net), .DI3(GND_net), 
            .DI4(GND_net), .DI5(GND_net), .DI6(GND_net), .DI7(GND_net), 
            .DI8(GND_net), .DI9(GND_net), .DI10(GND_net), .DI11(GND_net), 
            .DI12(GND_net), .DI13(GND_net), .DI14(GND_net), .DI15(GND_net), 
            .DI16(GND_net), .DI17(GND_net), .FULLI(GND_net), .EMPTYI(GND_net), 
            .CSW1(GND_net), .CSW0(GND_net), .CSR1(GND_net), .CSR0(GND_net), 
            .WE(GND_net), .RE(GND_net), .ORE(GND_net), .CLKW(clk_c), 
            .CLKR(clk_c), .RST(GND_net), .RPRST(GND_net), .DO0(q_w[0]), 
            .DO1(q_w[1]), .DO2(q_w[2]), .DO3(q_w[3]), .DO4(q_w[4]), 
            .DO5(q_w[5]), .DO6(q_w[6]), .DO7(q_w[7]), .DO8(q_w[8]), 
            .DO9(q_w[9]), .DO10(q_w[10]), .DO11(q_w[11]), .DO12(q_w[12]), 
            .DO13(q_w[13]), .DO14(q_w[14]), .DO15(q_w[15]), .DO16(q_w[16]), 
            .DO17(q_w[17]), .EF(ef_w), .FF(ff_w)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.DATA_WIDTH_W = 18;
    defparam u0.DATA_WIDTH_R = 18;
    defparam u0.REGMODE = "NOREG";
    defparam u0.RESETMODE = "ASYNC";
    defparam u0.ASYNC_RESET_RELEASE = "SYNC";
    defparam u0.CSDECODE_W = "0b00";
    defparam u0.CSDECODE_R = "0b00";
    defparam u0.AEPOINTER = "0b00000000000000";
    defparam u0.AEPOINTER1 = "0b00000000000000";
    defparam u0.AFPOINTER = "0b00000000000000";
    defparam u0.AFPOINTER1 = "0b00000000000000";
    defparam u0.FULLPOINTER = "0b00000000000000";
    defparam u0.FULLPOINTER1 = "0b00000000000000";
    defparam u0.GSR = "DISABLED";
    TSALL TSALL_INST (.TSALL(GND_net));
    LUT4 i2_2_lut (.A(q_w[3]), .B(q_w[6]), .Z(n22)) /* synthesis lut_function=(!(A (B)+!A !(B))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(33[33:51])
    defparam i2_2_lut.init = 16'h6666;
    LUT4 i12_4_lut (.A(q_w[10]), .B(q_w[8]), .C(ef_w), .D(q_w[16]), 
         .Z(n32)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(33[33:51])
    defparam i12_4_lut.init = 16'h6996;
    LUT4 i16_4_lut (.A(q_w[11]), .B(n32), .C(n22), .D(q_w[7]), .Z(n36)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(33[33:51])
    defparam i16_4_lut.init = 16'h6996;
    LUT4 i14_4_lut (.A(ff_w), .B(q_w[17]), .C(q_w[0]), .D(q_w[12]), 
         .Z(n34)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(33[33:51])
    defparam i14_4_lut.init = 16'h6996;
    LUT4 i15_4_lut (.A(q_w[1]), .B(q_w[9]), .C(q_w[2]), .D(q_w[13]), 
         .Z(n35)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(33[33:51])
    defparam i15_4_lut.init = 16'h6996;
    LUT4 i13_4_lut (.A(q_w[14]), .B(q_w[5]), .C(q_w[15]), .D(q_w[4]), 
         .Z(n33)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(33[33:51])
    defparam i13_4_lut.init = 16'h6996;
    LUT4 i19_4_lut (.A(n33), .B(n35), .C(n34), .D(n36), .Z(out0_N_1)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(33[33:51])
    defparam i19_4_lut.init = 16'h6996;
    VLO i1 (.Z(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(2[16:19])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_8 (.D(out0_N_1), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/fifo8kb_x18/fuzz.v(33[8:52])
    defparam out0_r_8.GSR = "ENABLED";
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

