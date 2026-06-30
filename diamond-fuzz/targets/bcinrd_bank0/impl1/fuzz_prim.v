// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 22:47:24 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bcinrd_bank0/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bcinrd_bank0/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bcinrd_bank0/fuzz.v(3[17:21])
    
    
    wire GND_net, VCC_net;
    
    VHI i14 (.Z(VCC_net));
    OB out0_pad (.I(GND_net), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bcinrd_bank0/fuzz.v(3[17:21])
    BCINRD u0 (.INRDENI(GND_net)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.BANKID = 0;
    GSR GSR_INST (.GSR(VCC_net));
    TSALL TSALL_INST (.TSALL(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VLO i1 (.Z(GND_net));
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

