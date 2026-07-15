// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Wed Jul 15 23:25:58 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/sedfa_freq_11p57_caen/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/sedfa_freq_11p57_caen/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/sedfa_freq_11p57_caen/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/sedfa_freq_11p57_caen/fuzz.v(2[16:19])
    
    wire GND_net, VCC_net, out0_c, sedout_w;
    
    VHI i2 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/sedfa_freq_11p57_caen/fuzz.v(3[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/sedfa_freq_11p57_caen/fuzz.v(2[16:19])
    SEDFA u0 (.SEDENABLE(VCC_net), .SEDSTART(GND_net), .SEDFRCERR(GND_net), 
          .SEDSTDBY(GND_net), .SEDDONE(sedout_w)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.SED_CLK_FREQ = "11.57";
    defparam u0.CHECKALWAYS = "ENABLED";
    defparam u0.DEV_DENSITY = "1200L";
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_5 (.D(sedout_w), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/sedfa_freq_11p57_caen/fuzz.v(17[8:42])
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

