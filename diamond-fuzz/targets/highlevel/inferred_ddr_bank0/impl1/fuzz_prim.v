// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:57:09 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d, q_rise, q_fall) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(2[17:20])
    input d;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(3[17:18])
    output q_rise;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(4[17:23])
    output q_fall;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(5[17:23])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(2[17:20])
    wire clk_N_2 /* synthesis is_inv_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(5[17:23])
    
    wire GND_net, d_c, q_rise_c, q_fall_c, VCC_net;
    
    VHI i17 (.Z(VCC_net));
    FD1S3AX q_rise_7 (.D(d_c), .CK(clk_c), .Q(q_rise_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(7[12:39])
    defparam q_rise_7.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    OB q_rise_pad (.I(q_rise_c), .O(q_rise));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(4[17:23])
    INV i22 (.A(clk_c), .Z(clk_N_2));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(2[17:20])
    OB q_fall_pad (.I(q_fall_c), .O(q_fall));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(5[17:23])
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(2[17:20])
    IB d_pad (.I(d), .O(d_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(3[17:18])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX q_fall_8 (.D(d_c), .CK(clk_N_2), .Q(q_fall_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/highlevel/inferred_ddr_bank0/fuzz.v(8[12:39])
    defparam q_fall_8.GSR = "ENABLED";
    TSALL TSALL_INST (.TSALL(GND_net));
    VLO i21 (.Z(GND_net));
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

