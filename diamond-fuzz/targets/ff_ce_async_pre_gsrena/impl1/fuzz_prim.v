// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 08:28:17 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ff_ce_async_pre_gsrena/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ff_ce_async_pre_gsrena/fuzz.v(2[16:19])
    input d;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ff_ce_async_pre_gsrena/fuzz.v(3[16:17])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ff_ce_async_pre_gsrena/fuzz.v(4[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ff_ce_async_pre_gsrena/fuzz.v(2[16:19])
    
    wire GND_net, VCC_net, d_c, out0_c, q_w;
    
    VHI i2 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ff_ce_async_pre_gsrena/fuzz.v(4[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ff_ce_async_pre_gsrena/fuzz.v(2[16:19])
    FD1P3JX u0 (.D(d_c), .SP(VCC_net), .PD(GND_net), .CK(clk_c), .Q(q_w)) /* synthesis GSR="ENABLED", syn_instantiated=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ff_ce_async_pre_gsrena/fuzz.v(9[9:60])
    defparam u0.GSR = "ENABLED";
    IB d_pad (.I(d), .O(d_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ff_ce_async_pre_gsrena/fuzz.v(3[16:17])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_5 (.D(q_w), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ff_ce_async_pre_gsrena/fuzz.v(11[8:37])
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

