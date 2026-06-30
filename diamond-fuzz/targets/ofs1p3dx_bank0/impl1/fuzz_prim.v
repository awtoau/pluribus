// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 08:36:00 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ofs1p3dx_bank0/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ofs1p3dx_bank0/fuzz.v(2[16:19])
    input d;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ofs1p3dx_bank0/fuzz.v(3[16:17])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ofs1p3dx_bank0/fuzz.v(4[17:21])
    
    wire clk_c /* synthesis is_clock=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ofs1p3dx_bank0/fuzz.v(2[16:19])
    
    wire GND_net, VCC_net, d_c, out0_c, d_r;
    
    VHI i2 (.Z(VCC_net));
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ofs1p3dx_bank0/fuzz.v(4[17:21])
    TSALL TSALL_INST (.TSALL(GND_net));
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ofs1p3dx_bank0/fuzz.v(2[16:19])
    OFS1P3DX u0 (.D(d_r), .SP(VCC_net), .SCLK(clk_c), .CD(GND_net), 
            .Q(out0_c)) /* synthesis syn_instantiated=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ofs1p3dx_bank0/fuzz.v(10[10:66])
    defparam u0.GSR = "ENABLED";
    IB d_pad (.I(d), .O(d_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ofs1p3dx_bank0/fuzz.v(3[16:17])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX d_r_5 (.D(d_c), .CK(clk_c), .Q(d_r));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/ofs1p3dx_bank0/fuzz.v(9[8:32])
    defparam d_r_5.GSR = "ENABLED";
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

