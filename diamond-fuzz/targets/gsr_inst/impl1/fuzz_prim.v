// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 08:33:09 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/gsr_inst/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/gsr_inst/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/gsr_inst/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/gsr_inst/fuzz.v(2[16:19])
    
    wire GND_net, out0_c, out0_N_2, VCC_net;
    
    VHI i20 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/gsr_inst/fuzz.v(3[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    GSR GSR_INST (.GSR(GND_net)) /* synthesis syn_instantiated=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/gsr_inst/fuzz.v(7[5:19])
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/gsr_inst/fuzz.v(2[16:19])
    FD1S3AX out0_r_6 (.D(out0_N_2), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/gsr_inst/fuzz.v(9[8:41])
    defparam out0_r_6.GSR = "DISABLED";
    VLO i1 (.Z(GND_net));
    LUT4 out0_I_0_1_lut (.A(out0_c), .Z(out0_N_2)) /* synthesis lut_function=(!(A)) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/gsr_inst/fuzz.v(9[33:40])
    defparam out0_I_0_1_lut.init = 16'h5555;
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

