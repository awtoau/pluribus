// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 22:54:26 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/sedfb_inst/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/sedfb_inst/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/sedfb_inst/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/sedfb_inst/fuzz.v(2[16:19])
    
    wire GND_net, out0_c, sederr_w, seddone_w, sedinprog_w, out0_N_1, 
        VCC_net;
    
    VHI i17 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/sedfb_inst/fuzz.v(3[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    SEDFB u0 (.SEDERR(sederr_w), .SEDDONE(seddone_w), .SEDINPROG(sedinprog_w)) /* synthesis syn_instantiated=1 */ ;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/sedfb_inst/fuzz.v(2[16:19])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_7 (.D(out0_N_1), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/sedfb_inst/fuzz.v(11[8:68])
    defparam out0_r_7.GSR = "ENABLED";
    VLO i22 (.Z(GND_net));
    LUT4 i2_3_lut (.A(sedinprog_w), .B(seddone_w), .C(sederr_w), .Z(out0_N_1)) /* synthesis lut_function=(A (B (C)+!B !(C))+!A !(B (C)+!B !(C))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/sedfb_inst/fuzz.v(11[33:67])
    defparam i2_3_lut.init = 16'h9696;
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

