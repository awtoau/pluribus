// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:57:23 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d, q) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_posedge_bank0/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_posedge_bank0/fuzz.v(2[17:20])
    input d;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_posedge_bank0/fuzz.v(3[17:18])
    output q;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_posedge_bank0/fuzz.v(4[17:18])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_posedge_bank0/fuzz.v(2[17:20])
    
    wire GND_net, d_c, q_c, VCC_net;
    
    VHI i14 (.Z(VCC_net));
    TSALL TSALL_INST (.TSALL(GND_net));
    OB q_pad (.I(q_c), .O(q));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_posedge_bank0/fuzz.v(4[17:18])
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_posedge_bank0/fuzz.v(2[17:20])
    IB d_pad (.I(d), .O(d_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_posedge_bank0/fuzz.v(3[17:18])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX q_5 (.D(d_c), .CK(clk_c), .Q(q_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/syn_useioff_posedge_bank0/fuzz.v(7[12:34])
    defparam q_5.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VLO i18 (.Z(GND_net));
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

