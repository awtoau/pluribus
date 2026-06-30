// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 22:48:13 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/eclkbridgecs/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/eclkbridgecs/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/eclkbridgecs/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/eclkbridgecs/fuzz.v(2[16:19])
    wire ecsout_w /* synthesis is_clock=1, SET_AS_NETWORK=ecsout_w */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/eclkbridgecs/fuzz.v(7[6:14])
    
    wire GND_net, out0_c, out0_N_2, VCC_net;
    
    VHI i15 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/eclkbridgecs/fuzz.v(3[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    ECLKBRIDGECS u0 (.CLK0(clk_c), .CLK1(clk_c), .SEL(GND_net), .ECSOUT(ecsout_w)) /* synthesis syn_instantiated=1 */ ;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/eclkbridgecs/fuzz.v(2[16:19])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_6 (.D(out0_N_2), .CK(ecsout_w), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/eclkbridgecs/fuzz.v(10[8:46])
    defparam out0_r_6.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VLO i1 (.Z(GND_net));
    LUT4 out0_I_0_1_lut (.A(out0_c), .Z(out0_N_2)) /* synthesis lut_function=(!(A)) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/eclkbridgecs/fuzz.v(10[38:45])
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

