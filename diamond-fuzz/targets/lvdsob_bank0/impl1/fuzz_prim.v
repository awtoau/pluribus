// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 22:52:37 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d0, pad_out) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lvdsob_bank0/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lvdsob_bank0/fuzz.v(2[16:19])
    input d0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lvdsob_bank0/fuzz.v(2[32:34])
    output pad_out;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lvdsob_bank0/fuzz.v(3[17:24])
    
    
    wire GND_net, d0_c, pad_out_c, VCC_net;
    
    VHI i12 (.Z(VCC_net));
    OB pad_out_pad (.I(pad_out_c), .O(pad_out));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lvdsob_bank0/fuzz.v(3[17:24])
    LVDSOB u0 (.D(d0_c), .E(GND_net), .Q(pad_out_c)) /* synthesis syn_instantiated=1 */ ;
    IB d0_pad (.I(d0), .O(d0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lvdsob_bank0/fuzz.v(2[32:34])
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

