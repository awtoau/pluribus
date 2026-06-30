// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 08:34:47 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d, d2, d3, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(2[16:19])
    input d;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(3[16:17])
    input d2;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(4[16:18])
    input d3;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(5[16:18])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(6[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(2[16:19])
    
    wire GND_net, d_c, d2_c, d3_c, out0_c, out_w, VCC_net;
    
    VHI i14 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(6[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    LUT4 u0 (.A(d_c), .B(d2_c), .C(d3_c), .D(GND_net), .Z(out_w)) /* synthesis syn_instantiated=1, lut_function=((!D !C !B !A)+(!D !C B A)+(!D C !B A)+(!D C B !A)+(D !C !B A)+(D !C B !A)+(D C !B !A)+(D C B A)) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(10[25:72])
    defparam u0.init = 16'b1001011001101001;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(2[16:19])
    IB d_pad (.I(d), .O(d_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(3[16:17])
    IB d2_pad (.I(d2), .O(d2_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(4[16:18])
    IB d3_pad (.I(d3), .O(d3_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(5[16:18])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_5 (.D(out_w), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/lut4_xnor4/fuzz.v(12[8:39])
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

