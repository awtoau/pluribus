// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 22:58:17 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, a, b, out_s, out_co) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(2[16:19])
    input a;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(2[32:33])
    input b;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(2[46:47])
    output out_s;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(3[17:22])
    output out_co;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(3[24:30])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(2[16:19])
    
    wire GND_net, a_c, b_c, out_s_c, out_co_c, s0_w, s1_w, cout_w, 
        s2_w, s3_w, out_s_N_1, out_s_N_2, VCC_net;
    
    VHI i18 (.Z(VCC_net));
    CCU2D u1 (.A0(a_c), .B0(b_c), .C0(GND_net), .D0(GND_net), .A1(a_c), 
          .B1(b_c), .C1(GND_net), .D1(GND_net), .CIN(cout_w), .S0(s2_w), 
          .S1(s3_w)) /* synthesis syn_instantiated=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(24[3] 29[2])
    defparam u1.INIT0 = 16'b0000100110011001;
    defparam u1.INIT1 = 16'b0000100110011001;
    defparam u1.INJECT1_0 = "YES";
    defparam u1.INJECT1_1 = "YES";
    OB out_s_pad (.I(out_s_c), .O(out_s));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(3[17:22])
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    TSALL TSALL_INST (.TSALL(GND_net));
    GSR GSR_INST (.GSR(VCC_net));
    CCU2D u0 (.A0(a_c), .B0(b_c), .C0(GND_net), .D0(GND_net), .A1(a_c), 
          .B1(b_c), .C1(GND_net), .D1(GND_net), .COUT(cout_w), .S0(s0_w), 
          .S1(s1_w)) /* synthesis syn_instantiated=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(13[3] 18[2])
    defparam u0.INIT0 = 16'b0000100110011001;
    defparam u0.INIT1 = 16'b0000100110011001;
    defparam u0.INJECT1_0 = "YES";
    defparam u0.INJECT1_1 = "YES";
    OB out_co_pad (.I(out_co_c), .O(out_co));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(3[24:30])
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(2[16:19])
    IB a_pad (.I(a), .O(a_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(2[32:33])
    IB b_pad (.I(b), .O(b_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(2[46:47])
    FD1S3AX q_i2 (.D(out_s_N_1), .CK(clk_c), .Q(out_co_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(31[8:55])
    defparam q_i2.GSR = "ENABLED";
    FD1S3AX q_i1 (.D(out_s_N_2), .CK(clk_c), .Q(out_s_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(31[8:55])
    defparam q_i1.GSR = "ENABLED";
    VLO i1 (.Z(GND_net));
    LUT4 s3_w_I_0_2_lut (.A(s3_w), .B(s2_w), .Z(out_s_N_1)) /* synthesis lut_function=(!(A (B)+!A !(B))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(31[29:40])
    defparam s3_w_I_0_2_lut.init = 16'h6666;
    LUT4 s1_w_I_0_2_lut (.A(s1_w), .B(s0_w), .Z(out_s_N_2)) /* synthesis lut_function=(!(A (B)+!A !(B))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ccu2d_sub/fuzz.v(31[42:53])
    defparam s1_w_I_0_2_lut.init = 16'h6666;
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

