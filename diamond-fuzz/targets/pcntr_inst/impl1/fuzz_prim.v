// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 08:40:54 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, stdby_in, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_inst/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_inst/fuzz.v(2[16:19])
    input stdby_in;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_inst/fuzz.v(2[32:40])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_inst/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_inst/fuzz.v(2[16:19])
    
    wire GND_net, stdby_in_c, out0_c, stdby_w, stop_w, sflag_w, 
        out0_N_1, VCC_net;
    
    VHI i17 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_inst/fuzz.v(3[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    PCNTR u0 (.CLK(clk_c), .USERTIMEOUT(GND_net), .USERSTDBY(stdby_in_c), 
          .CLRFLAG(GND_net), .CFGWAKE(GND_net), .CFGSTDBY(GND_net), .STDBY(stdby_w), 
          .STOP(stop_w), .SFLAG(sflag_w)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.STDBYOPT = "USER_CFG";
    defparam u0.TIMEOUT = "BYPASS";
    defparam u0.WAKEUP = "USER";
    defparam u0.POROFF = "FALSE";
    defparam u0.BGOFF = "FALSE";
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_inst/fuzz.v(2[16:19])
    IB stdby_in_pad (.I(stdby_in), .O(stdby_in_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_inst/fuzz.v(2[32:40])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_7 (.D(out0_N_1), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_inst/fuzz.v(14[8:60])
    defparam out0_r_7.GSR = "ENABLED";
    VLO i1 (.Z(GND_net));
    LUT4 i2_3_lut (.A(sflag_w), .B(stop_w), .C(stdby_w), .Z(out0_N_1)) /* synthesis lut_function=(A (B (C)+!B !(C))+!A !(B (C)+!B !(C))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_inst/fuzz.v(14[33:59])
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

