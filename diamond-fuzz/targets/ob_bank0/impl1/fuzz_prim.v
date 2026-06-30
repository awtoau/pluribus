// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 22:52:42 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d0, pad_out) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ob_bank0/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ob_bank0/fuzz.v(2[16:19])
    input d0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ob_bank0/fuzz.v(2[32:34])
    output pad_out /* synthesis black_box_pad_pin=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ob_bank0/fuzz.v(3[17:24])
    
    
    wire d0_c, GND_net, VCC_net;
    
    IB d0_pad (.I(d0), .O(d0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ob_bank0/fuzz.v(2[32:34])
    VLO i23 (.Z(GND_net));
    OB u0 (.I(d0_c), .O(pad_out)) /* synthesis syn_instantiated=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ob_bank0/fuzz.v(6[4:28])
    GSR GSR_INST (.GSR(VCC_net));
    TSALL TSALL_INST (.TSALL(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VHI i24 (.Z(VCC_net));
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

