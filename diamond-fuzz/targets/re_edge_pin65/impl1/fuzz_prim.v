// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Thu Jul 16 00:11:37 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_edge_pin65/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_edge_pin65/fuzz.v(1[24:27])
    output d;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_edge_pin65/fuzz.v(1[40:41])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_edge_pin65/fuzz.v(1[24:27])
    
    wire GND_net, d_c, d_N_2, VCC_net;
    
    VHI i15 (.Z(VCC_net));
    TSALL TSALL_INST (.TSALL(GND_net));
    OB d_pad (.I(d_c), .O(d));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_edge_pin65/fuzz.v(1[40:41])
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_edge_pin65/fuzz.v(1[24:27])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX t_6 (.D(d_N_2), .CK(clk_c), .Q(d_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_edge_pin65/fuzz.v(2[16:37])
    defparam t_6.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VLO i19 (.Z(GND_net));
    LUT4 d_I_0_1_lut (.A(d_c), .Z(d_N_2)) /* synthesis lut_function=(!(A)) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_edge_pin65/fuzz.v(2[34:36])
    defparam d_I_0_1_lut.init = 16'h5555;
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

