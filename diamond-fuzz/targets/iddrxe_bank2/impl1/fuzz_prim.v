// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 22:51:05 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d0, d1, out0, out1, out2, out3) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(2[16:19])
    input d0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(2[32:34])
    input d1;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(2[47:49])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(3[17:21])
    output out1;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(3[23:27])
    output out2;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(3[29:33])
    output out3;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(3[35:39])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(2[16:19])
    
    wire GND_net, d0_c, d1_c, out0_c, out1_c, out2_c, out3_c, 
        q0a, q1a, q0b, q1b, VCC_net;
    
    VHI i14 (.Z(VCC_net));
    IDDRXE u1 (.D(d1_c), .SCLK(clk_c), .RST(GND_net), .Q0(q0b), .Q1(q1b)) /* synthesis syn_instantiated=1 */ ;
    defparam u1.GSR = "ENABLED";
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(3[17:21])
    GSR GSR_INST (.GSR(VCC_net));
    IDDRXE u0 (.D(d0_c), .SCLK(clk_c), .RST(GND_net), .Q0(q0a), .Q1(q1a)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.GSR = "ENABLED";
    OB out1_pad (.I(out1_c), .O(out1));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(3[23:27])
    OB out2_pad (.I(out2_c), .O(out2));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(3[29:33])
    OB out3_pad (.I(out3_c), .O(out3));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(3[35:39])
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(2[16:19])
    IB d0_pad (.I(d0), .O(d0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(2[32:34])
    IB d1_pad (.I(d1), .O(d1_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(2[47:49])
    FD1S3AX q_i2 (.D(q1a), .CK(clk_c), .Q(out1_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(11[8:49])
    defparam q_i2.GSR = "ENABLED";
    FD1S3AX q_i3 (.D(q0b), .CK(clk_c), .Q(out2_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(11[8:49])
    defparam q_i3.GSR = "ENABLED";
    FD1S3AX q_i4 (.D(q1b), .CK(clk_c), .Q(out3_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(11[8:49])
    defparam q_i4.GSR = "ENABLED";
    TSALL TSALL_INST (.TSALL(GND_net));
    FD1S3AX q_i1 (.D(q0a), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/iddrxe_bank2/fuzz.v(11[8:49])
    defparam q_i1.GSR = "ENABLED";
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

