// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 23:53:49 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d0, d1, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(2[16:19])
    input d0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(2[32:34])
    input d1;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(2[47:49])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(2[16:19])
    wire eclk_w /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(7[6:12])
    wire sclk_w /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(7[14:20])
    
    wire GND_net, d0_c, d1_c, out0_c, VCC_net;
    
    VHI i12 (.Z(VCC_net));
    CLKDIVC u_div (.RST(GND_net), .CLKI(eclk_w), .ALIGNWD(GND_net), .CDIVX(sclk_w)) /* synthesis syn_instantiated=1 */ ;
    defparam u_div.GSR = "ENABLED";
    defparam u_div.DIV = "4.0";
    ODDRX4B u0 (.D0(d0_c), .D1(d1_c), .D2(d0_c), .D3(d1_c), .D4(d0_c), 
            .D5(d1_c), .D6(d0_c), .D7(d1_c), .ECLK(eclk_w), .SCLK(sclk_w), 
            .RST(GND_net), .Q(out0_c)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.GSR = "ENABLED";
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(3[17:21])
    ECLKSYNCA u_eclk (.ECLKI(clk_c), .STOP(GND_net), .ECLKO(eclk_w)) /* synthesis syn_instantiated=1 */ ;
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(2[16:19])
    IB d0_pad (.I(d0), .O(d0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(2[32:34])
    IB d1_pad (.I(d1), .O(d1_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/oddrx4b_bank0/fuzz.v(2[47:49])
    GSR GSR_INST (.GSR(VCC_net));
    TSALL TSALL_INST (.TSALL(GND_net));
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

