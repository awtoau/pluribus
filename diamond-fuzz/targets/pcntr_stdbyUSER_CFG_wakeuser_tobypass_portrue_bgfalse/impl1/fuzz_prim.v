// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 08:41:06 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_stdbyUSER_CFG_wakeuser_tobypass_portrue_bgfalse/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_stdbyUSER_CFG_wakeuser_tobypass_portrue_bgfalse/fuzz.v(2[16:19])
    input d;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_stdbyUSER_CFG_wakeuser_tobypass_portrue_bgfalse/fuzz.v(3[16:17])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_stdbyUSER_CFG_wakeuser_tobypass_portrue_bgfalse/fuzz.v(4[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_stdbyUSER_CFG_wakeuser_tobypass_portrue_bgfalse/fuzz.v(2[16:19])
    
    wire GND_net, d_c, out0_c, stdby_w, stop_w, out0_N_1, VCC_net;
    
    VHI i15 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_stdbyUSER_CFG_wakeuser_tobypass_portrue_bgfalse/fuzz.v(4[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    PCNTR u0 (.CLK(clk_c), .USERTIMEOUT(d_c), .USERSTDBY(d_c), .CLRFLAG(d_c), 
          .CFGWAKE(GND_net), .CFGSTDBY(GND_net), .STDBY(stdby_w), .STOP(stop_w)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.STDBYOPT = "USER_CFG";
    defparam u0.TIMEOUT = "BYPASS";
    defparam u0.WAKEUP = "USER";
    defparam u0.POROFF = "TRUE";
    defparam u0.BGOFF = "FALSE";
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_stdbyUSER_CFG_wakeuser_tobypass_portrue_bgfalse/fuzz.v(2[16:19])
    IB d_pad (.I(d), .O(d_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_stdbyUSER_CFG_wakeuser_tobypass_portrue_bgfalse/fuzz.v(3[16:17])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_6 (.D(out0_N_1), .CK(clk_c), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_stdbyUSER_CFG_wakeuser_tobypass_portrue_bgfalse/fuzz.v(21[8:50])
    defparam out0_r_6.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VLO i1 (.Z(GND_net));
    LUT4 stdby_w_I_0_2_lut (.A(stdby_w), .B(stop_w), .Z(out0_N_1)) /* synthesis lut_function=(!(A (B)+!A !(B))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pcntr_stdbyUSER_CFG_wakeuser_tobypass_portrue_bgfalse/fuzz.v(21[33:49])
    defparam stdby_w_I_0_2_lut.init = 16'h6666;
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

