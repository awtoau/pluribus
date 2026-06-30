// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:57:28 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d, rst, q) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(2[17:20])
    input d;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(3[17:18])
    input rst;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(4[17:20])
    output q;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(5[17:18])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(2[17:20])
    
    wire d_c, rst_c, q_c, GND_net, n5, VCC_net;
    
    VLO i22 (.Z(GND_net));
    OB q_pad (.I(q_c), .O(q));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(5[17:18])
    LUT4 i15_1_lut (.A(rst_c), .Z(n5)) /* synthesis lut_function=(!(A)) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(4[17:20])
    defparam i15_1_lut.init = 16'h5555;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(2[17:20])
    IB d_pad (.I(d), .O(d_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(3[17:18])
    IB rst_pad (.I(rst), .O(rst_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(4[17:20])
    GSR GSR_INST (.GSR(n5));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    FD1S3AX q_5 (.D(d_c), .CK(clk_c), .Q(q_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_with_rst_bank0/fuzz.v(10[18:25])
    defparam q_5.GSR = "ENABLED";
    TSALL TSALL_INST (.TSALL(GND_net));
    VHI i25 (.Z(VCC_net));
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

