// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:57:20 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, a, b, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(2[17:20])
    input a;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(3[17:18])
    input b;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(4[17:18])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(5[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(2[17:20])
    
    wire GND_net, a_c, b_c, out0_c, w, VCC_net;
    
    VHI i15 (.Z(VCC_net));
    TSALL TSALL_INST (.TSALL(GND_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(5[17:21])
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(2[17:20])
    IB a_pad (.I(a), .O(a_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(3[17:18])
    IB b_pad (.I(b), .O(b_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(4[17:18])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_6 (.D(w), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(9[12:37])
    defparam out0_6.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VLO i19 (.Z(GND_net));
    LUT4 a_I_0_2_lut (.A(a_c), .B(b_c), .Z(w)) /* synthesis lut_function=(!(A (B)+!A !(B))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_keep_wire/fuzz.v(8[16:21])
    defparam a_I_0_2_lut.init = 16'h6666;
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

