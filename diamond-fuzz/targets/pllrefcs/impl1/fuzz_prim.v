// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:53:59 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pllrefcs/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pllrefcs/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pllrefcs/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pllrefcs/fuzz.v(2[16:19])
    wire pllref_out /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pllrefcs/fuzz.v(7[6:16])
    wire pll_clkop /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pllrefcs/fuzz.v(7[18:27])
    
    wire GND_net, VCC_net, out0_c, pll_lock;
    
    VHI i2 (.Z(VCC_net));
    EHXPLLJ u_pll (.CLKI(pllref_out), .CLKFB(pll_clkop), .PHASESEL0(GND_net), 
            .PHASESEL1(GND_net), .PHASEDIR(GND_net), .PHASESTEP(GND_net), 
            .LOADREG(GND_net), .STDBY(GND_net), .PLLWAKESYNC(GND_net), 
            .RST(GND_net), .RESETC(GND_net), .RESETD(GND_net), .RESETM(GND_net), 
            .ENCLKOP(VCC_net), .ENCLKOS(GND_net), .ENCLKOS2(GND_net), 
            .ENCLKOS3(GND_net), .PLLCLK(GND_net), .PLLRST(GND_net), .PLLSTB(GND_net), 
            .PLLWE(GND_net), .PLLDATI0(GND_net), .PLLDATI1(GND_net), .PLLDATI2(GND_net), 
            .PLLDATI3(GND_net), .PLLDATI4(GND_net), .PLLDATI5(GND_net), 
            .PLLDATI6(GND_net), .PLLDATI7(GND_net), .PLLADDR0(GND_net), 
            .PLLADDR1(GND_net), .PLLADDR2(GND_net), .PLLADDR3(GND_net), 
            .PLLADDR4(GND_net), .CLKOP(pll_clkop), .LOCK(pll_lock)) /* synthesis syn_instantiated=1 */ ;
    defparam u_pll.CLKI_DIV = 1;
    defparam u_pll.CLKFB_DIV = 1;
    defparam u_pll.CLKOP_DIV = 1;
    defparam u_pll.CLKOS_DIV = 8;
    defparam u_pll.CLKOS2_DIV = 8;
    defparam u_pll.CLKOS3_DIV = 8;
    defparam u_pll.CLKOP_ENABLE = "ENABLED";
    defparam u_pll.CLKOS_ENABLE = "ENABLED";
    defparam u_pll.CLKOS2_ENABLE = "ENABLED";
    defparam u_pll.CLKOS3_ENABLE = "ENABLED";
    defparam u_pll.VCO_BYPASS_A0 = "DISABLED";
    defparam u_pll.VCO_BYPASS_B0 = "DISABLED";
    defparam u_pll.VCO_BYPASS_C0 = "DISABLED";
    defparam u_pll.VCO_BYPASS_D0 = "DISABLED";
    defparam u_pll.CLKOP_CPHASE = 0;
    defparam u_pll.CLKOS_CPHASE = 0;
    defparam u_pll.CLKOS2_CPHASE = 0;
    defparam u_pll.CLKOS3_CPHASE = 0;
    defparam u_pll.CLKOP_FPHASE = 0;
    defparam u_pll.CLKOS_FPHASE = 0;
    defparam u_pll.CLKOS2_FPHASE = 0;
    defparam u_pll.CLKOS3_FPHASE = 0;
    defparam u_pll.FEEDBK_PATH = "CLKOP";
    defparam u_pll.FRACN_ENABLE = "DISABLED";
    defparam u_pll.FRACN_DIV = 0;
    defparam u_pll.CLKOP_TRIM_POL = "RISING";
    defparam u_pll.CLKOP_TRIM_DELAY = 0;
    defparam u_pll.CLKOS_TRIM_POL = "RISING";
    defparam u_pll.CLKOS_TRIM_DELAY = 0;
    defparam u_pll.PLL_USE_WB = "DISABLED";
    defparam u_pll.PREDIVIDER_MUXA1 = 0;
    defparam u_pll.PREDIVIDER_MUXB1 = 0;
    defparam u_pll.PREDIVIDER_MUXC1 = 0;
    defparam u_pll.PREDIVIDER_MUXD1 = 0;
    defparam u_pll.OUTDIVIDER_MUXA2 = "DIVA";
    defparam u_pll.OUTDIVIDER_MUXB2 = "DIVB";
    defparam u_pll.OUTDIVIDER_MUXC2 = "DIVC";
    defparam u_pll.OUTDIVIDER_MUXD2 = "DIVD";
    defparam u_pll.PLL_LOCK_MODE = 0;
    defparam u_pll.STDBY_ENABLE = "DISABLED";
    defparam u_pll.DPHASE_SOURCE = "DISABLED";
    defparam u_pll.PLLRST_ENA = "DISABLED";
    defparam u_pll.MRST_ENA = "DISABLED";
    defparam u_pll.DCRST_ENA = "DISABLED";
    defparam u_pll.DDRST_ENA = "DISABLED";
    defparam u_pll.INTFB_WAKE = "DISABLED";
    VLO i1 (.Z(GND_net));
    FD1S3AX out0_r_5 (.D(pll_lock), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pllrefcs/fuzz.v(24[8:42])
    defparam out0_r_5.GSR = "ENABLED";
    PLLREFCS u_ref (.CLK0(clk_c), .CLK1(GND_net), .SEL(GND_net), .PLLCSOUT(pllref_out)) /* synthesis syn_instantiated=1 */ ;
    GSR GSR_INST (.GSR(VCC_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pllrefcs/fuzz.v(2[16:19])
    TSALL TSALL_INST (.TSALL(GND_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pllrefcs/fuzz.v(3[17:21])
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

