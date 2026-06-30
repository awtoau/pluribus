// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:57:14 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(2[17:20])
    input d;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(3[17:18])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(4[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(2[17:20])
    
    wire GND_net, d_c, out0_c;
    wire [15:0]shreg;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(6[16:21])
    
    wire VCC_net;
    
    VHI i14 (.Z(VCC_net));
    GSR GSR_INST (.GSR(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(4[17:21])
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(2[17:20])
    IB d_pad (.I(d), .O(d_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(3[17:18])
    FD1S3AX shreg_i1 (.D(shreg[0]), .CK(clk_c), .Q(shreg[1]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i1.GSR = "ENABLED";
    FD1S3AX shreg_i2 (.D(shreg[1]), .CK(clk_c), .Q(shreg[2]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i2.GSR = "ENABLED";
    FD1S3AX shreg_i3 (.D(shreg[2]), .CK(clk_c), .Q(shreg[3]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i3.GSR = "ENABLED";
    FD1S3AX shreg_i4 (.D(shreg[3]), .CK(clk_c), .Q(shreg[4]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i4.GSR = "ENABLED";
    FD1S3AX shreg_i5 (.D(shreg[4]), .CK(clk_c), .Q(shreg[5]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i5.GSR = "ENABLED";
    FD1S3AX shreg_i6 (.D(shreg[5]), .CK(clk_c), .Q(shreg[6]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i6.GSR = "ENABLED";
    FD1S3AX shreg_i7 (.D(shreg[6]), .CK(clk_c), .Q(shreg[7]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i7.GSR = "ENABLED";
    FD1S3AX shreg_i8 (.D(shreg[7]), .CK(clk_c), .Q(shreg[8]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i8.GSR = "ENABLED";
    FD1S3AX shreg_i9 (.D(shreg[8]), .CK(clk_c), .Q(shreg[9]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i9.GSR = "ENABLED";
    FD1S3AX shreg_i10 (.D(shreg[9]), .CK(clk_c), .Q(shreg[10]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i10.GSR = "ENABLED";
    FD1S3AX shreg_i11 (.D(shreg[10]), .CK(clk_c), .Q(shreg[11]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i11.GSR = "ENABLED";
    FD1S3AX shreg_i12 (.D(shreg[11]), .CK(clk_c), .Q(shreg[12]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i12.GSR = "ENABLED";
    FD1S3AX shreg_i13 (.D(shreg[12]), .CK(clk_c), .Q(shreg[13]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i13.GSR = "ENABLED";
    FD1S3AX shreg_i14 (.D(shreg[13]), .CK(clk_c), .Q(shreg[14]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i14.GSR = "ENABLED";
    FD1S3AX shreg_i15 (.D(shreg[14]), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i15.GSR = "ENABLED";
    TSALL TSALL_INST (.TSALL(GND_net));
    FD1S3AX shreg_i0 (.D(d_c), .CK(clk_c), .Q(shreg[0]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_shreg_16/fuzz.v(7[12:53])
    defparam shreg_i0.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VLO i18 (.Z(GND_net));
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

