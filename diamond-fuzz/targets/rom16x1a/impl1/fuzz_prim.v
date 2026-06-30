// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:27:24 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/rom16x1a/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/rom16x1a/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/rom16x1a/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/rom16x1a/fuzz.v(2[16:19])
    
    wire GND_net, out0_c, do_w, VCC_net;
    
    VHI i14 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/rom16x1a/fuzz.v(3[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    ROM16X1A u0 (.AD0(GND_net), .AD1(GND_net), .AD2(GND_net), .AD3(GND_net), 
            .DO0(do_w)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.initval = 2'b00;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/rom16x1a/fuzz.v(2[16:19])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_5 (.D(do_w), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/rom16x1a/fuzz.v(16[8:38])
    defparam out0_r_5.GSR = "ENABLED";
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

