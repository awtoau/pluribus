// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 09:06:14 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pll_fracn_div55168/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pll_fracn_div55168/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pll_fracn_div55168/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pll_fracn_div55168/fuzz.v(2[16:19])
    wire clkop_w /* synthesis is_clock=1, SET_AS_NETWORK=clkop_w */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pll_fracn_div55168/fuzz.v(8[6:13])
    
    wire GND_net, VCC_net, out0_c, lock_w;
    
    VHI i2 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pll_fracn_div55168/fuzz.v(3[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pll_fracn_div55168/fuzz.v(2[16:19])
    EHXPLLJ u0 (.CLKI(clk_c), .CLKFB(GND_net), .PHASESEL0(GND_net), .PHASESEL1(GND_net), 
            .PHASEDIR(GND_net), .PHASESTEP(GND_net), .LOADREG(GND_net), 
            .STDBY(GND_net), .PLLWAKESYNC(GND_net), .RST(GND_net), .RESETC(GND_net), 
            .RESETD(GND_net), .RESETM(GND_net), .ENCLKOP(VCC_net), .ENCLKOS(VCC_net), 
            .ENCLKOS2(VCC_net), .ENCLKOS3(VCC_net), .PLLCLK(GND_net), 
            .PLLRST(GND_net), .PLLSTB(GND_net), .PLLWE(GND_net), .PLLDATI0(GND_net), 
            .PLLDATI1(GND_net), .PLLDATI2(GND_net), .PLLDATI3(GND_net), 
            .PLLDATI4(GND_net), .PLLDATI5(GND_net), .PLLDATI6(GND_net), 
            .PLLDATI7(GND_net), .PLLADDR0(GND_net), .PLLADDR1(GND_net), 
            .PLLADDR2(GND_net), .PLLADDR3(GND_net), .PLLADDR4(GND_net), 
            .CLKOP(clkop_w), .LOCK(lock_w)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.CLKI_DIV = 1;
    defparam u0.CLKFB_DIV = 1;
    defparam u0.CLKOP_DIV = 1;
    defparam u0.CLKOS_DIV = 8;
    defparam u0.CLKOS2_DIV = 8;
    defparam u0.CLKOS3_DIV = 8;
    defparam u0.CLKOP_ENABLE = "ENABLED";
    defparam u0.CLKOS_ENABLE = "ENABLED";
    defparam u0.CLKOS2_ENABLE = "ENABLED";
    defparam u0.CLKOS3_ENABLE = "ENABLED";
    defparam u0.VCO_BYPASS_A0 = "DISABLED";
    defparam u0.VCO_BYPASS_B0 = "DISABLED";
    defparam u0.VCO_BYPASS_C0 = "DISABLED";
    defparam u0.VCO_BYPASS_D0 = "DISABLED";
    defparam u0.CLKOP_CPHASE = 0;
    defparam u0.CLKOS_CPHASE = 0;
    defparam u0.CLKOS2_CPHASE = 0;
    defparam u0.CLKOS3_CPHASE = 0;
    defparam u0.CLKOP_FPHASE = 0;
    defparam u0.CLKOS_FPHASE = 0;
    defparam u0.CLKOS2_FPHASE = 0;
    defparam u0.CLKOS3_FPHASE = 0;
    defparam u0.FEEDBK_PATH = "INT_DIVA";
    defparam u0.FRACN_ENABLE = "ENABLED";
    defparam u0.FRACN_DIV = 55168;
    defparam u0.CLKOP_TRIM_POL = "RISING";
    defparam u0.CLKOP_TRIM_DELAY = 0;
    defparam u0.CLKOS_TRIM_POL = "RISING";
    defparam u0.CLKOS_TRIM_DELAY = 0;
    defparam u0.PLL_USE_WB = "DISABLED";
    defparam u0.PREDIVIDER_MUXA1 = 0;
    defparam u0.PREDIVIDER_MUXB1 = 0;
    defparam u0.PREDIVIDER_MUXC1 = 0;
    defparam u0.PREDIVIDER_MUXD1 = 0;
    defparam u0.OUTDIVIDER_MUXA2 = "DIVA";
    defparam u0.OUTDIVIDER_MUXB2 = "DIVB";
    defparam u0.OUTDIVIDER_MUXC2 = "DIVC";
    defparam u0.OUTDIVIDER_MUXD2 = "DIVD";
    defparam u0.PLL_LOCK_MODE = 0;
    defparam u0.STDBY_ENABLE = "DISABLED";
    defparam u0.DPHASE_SOURCE = "DISABLED";
    defparam u0.PLLRST_ENA = "DISABLED";
    defparam u0.MRST_ENA = "DISABLED";
    defparam u0.DCRST_ENA = "DISABLED";
    defparam u0.DDRST_ENA = "DISABLED";
    defparam u0.INTFB_WAKE = "DISABLED";
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_5 (.D(lock_w), .CK(clkop_w), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pll_fracn_div55168/fuzz.v(26[8:44])
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

