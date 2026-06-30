// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:53:54 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d0, d1, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrxe_bank0/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrxe_bank0/fuzz.v(2[16:19])
    input d0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrxe_bank0/fuzz.v(2[32:34])
    input d1;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrxe_bank0/fuzz.v(2[47:49])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrxe_bank0/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrxe_bank0/fuzz.v(2[16:19])
    
    wire GND_net, d0_c, d1_c, out0_c, VCC_net;
    
    VHI i12 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrxe_bank0/fuzz.v(3[17:21])
    ODDRXE u0 (.D0(d0_c), .D1(d1_c), .SCLK(clk_c), .RST(GND_net), .Q(out0_c)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.GSR = "ENABLED";
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrxe_bank0/fuzz.v(2[16:19])
    IB d0_pad (.I(d0), .O(d0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrxe_bank0/fuzz.v(2[32:34])
    IB d1_pad (.I(d1), .O(d1_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrxe_bank0/fuzz.v(2[47:49])
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

