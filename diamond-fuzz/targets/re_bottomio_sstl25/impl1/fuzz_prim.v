// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Wed Jul 15 23:37:39 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_bottomio_sstl25/fuzz.v(2[8:12])
    input clk;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_bottomio_sstl25/fuzz.v(3[17:20])
    output d0;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_bottomio_sstl25/fuzz.v(4[17:19])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_bottomio_sstl25/fuzz.v(3[17:20])
    
    wire GND_net, d0_c, d0_N_2, VCC_net;
    
    VHI i15 (.Z(VCC_net));
    TSALL TSALL_INST (.TSALL(GND_net));
    OB d0_pad (.I(d0_c), .O(d0));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_bottomio_sstl25/fuzz.v(4[17:19])
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_bottomio_sstl25/fuzz.v(3[17:20])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX t_6 (.D(d0_N_2), .CK(clk_c), .Q(d0_c));   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_bottomio_sstl25/fuzz.v(7[12:35])
    defparam t_6.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VLO i19 (.Z(GND_net));
    LUT4 d0_I_0_1_lut (.A(d0_c), .Z(d0_N_2)) /* synthesis lut_function=(!(A)) */ ;   // /mnt/2tb/git/pluribus/diamond-fuzz/targets/re_bottomio_sstl25/fuzz.v(7[32:34])
    defparam d0_I_0_1_lut.init = 16'h5555;
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

