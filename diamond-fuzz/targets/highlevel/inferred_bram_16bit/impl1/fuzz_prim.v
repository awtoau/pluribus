// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:57:01 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_bram_16bit/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_bram_16bit/fuzz.v(2[17:20])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_bram_16bit/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_bram_16bit/fuzz.v(2[17:20])
    
    wire GND_net, VCC_net;
    
    VHI i22 (.Z(VCC_net));
    GSR GSR_INST (.GSR(VCC_net));
    OB out0_pad (.I(GND_net), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_bram_16bit/fuzz.v(3[17:21])
    VLO i1 (.Z(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    TSALL TSALL_INST (.TSALL(GND_net));
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_bram_16bit/fuzz.v(2[17:20])
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

