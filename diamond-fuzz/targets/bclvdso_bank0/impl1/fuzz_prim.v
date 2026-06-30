// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:35:18 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, lvds_en, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bclvdso_bank0/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bclvdso_bank0/fuzz.v(2[16:19])
    input lvds_en;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bclvdso_bank0/fuzz.v(2[32:39])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bclvdso_bank0/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bclvdso_bank0/fuzz.v(2[16:19])
    
    wire GND_net, lvds_en_c, out0_c, VCC_net;
    
    VHI i14 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bclvdso_bank0/fuzz.v(3[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    BCLVDSO u0 (.LVDSENI(lvds_en_c)) /* synthesis syn_instantiated=1 */ ;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bclvdso_bank0/fuzz.v(2[16:19])
    IB lvds_en_pad (.I(lvds_en), .O(lvds_en_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bclvdso_bank0/fuzz.v(2[32:39])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_5 (.D(lvds_en_c), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/bclvdso_bank0/fuzz.v(9[8:41])
    defparam out0_r_5.GSR = "ENABLED";
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

