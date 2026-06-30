// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 08:20:47 2026
//
// Verilog Description of module fuzz
//

module fuzz (out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/osch_freq_7p00/fuzz.v(1[8:12])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/osch_freq_7p00/fuzz.v(2[17:21])
    
    wire osc_w /* synthesis is_clock=1, SET_AS_NETWORK=osc_w */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/osch_freq_7p00/fuzz.v(6[6:11])
    
    wire GND_net, out0_c, out0_N_2, VCC_net;
    
    VHI i15 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/osch_freq_7p00/fuzz.v(2[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    OSCH u0 (.STDBY(GND_net), .OSC(osc_w)) /* synthesis syn_instantiated=1 */ ;
    defparam u0.NOM_FREQ = "7.00";
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_6 (.D(out0_N_2), .CK(osc_w), .Q(out0_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/osch_freq_7p00/fuzz.v(9[8:43])
    defparam out0_r_6.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VLO i1 (.Z(GND_net));
    LUT4 out0_I_0_1_lut (.A(out0_c), .Z(out0_N_2)) /* synthesis lut_function=(!(A)) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/osch_freq_7p00/fuzz.v(9[35:42])
    defparam out0_I_0_1_lut.init = 16'h5555;
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

