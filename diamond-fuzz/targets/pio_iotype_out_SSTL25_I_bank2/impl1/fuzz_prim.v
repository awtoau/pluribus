// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Tue Jun 30 08:25:31 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, d, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pio_iotype_out_SSTL25_I_bank2/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pio_iotype_out_SSTL25_I_bank2/fuzz.v(2[16:19])
    input d;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pio_iotype_out_SSTL25_I_bank2/fuzz.v(3[16:17])
    output out0 /* synthesis black_box_pad_pin=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pio_iotype_out_SSTL25_I_bank2/fuzz.v(4[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pio_iotype_out_SSTL25_I_bank2/fuzz.v(2[16:19])
    
    wire GND_net, d_c, out0_r, VCC_net;
    
    VHI i14 (.Z(VCC_net));
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pio_iotype_out_SSTL25_I_bank2/fuzz.v(2[16:19])
    TSALL TSALL_INST (.TSALL(GND_net));
    OB u0 (.I(out0_r), .O(out0)) /* synthesis LOC="38", IO_TYPE="SSTL25_I", syn_instantiated=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pio_iotype_out_SSTL25_I_bank2/fuzz.v(10[4:29])
    IB d_pad (.I(d), .O(d_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pio_iotype_out_SSTL25_I_bank2/fuzz.v(3[16:17])
    GSR GSR_INST (.GSR(VCC_net));
    FD1S3AX out0_r_5 (.D(d_c), .CK(clk_c), .Q(out0_r));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/pio_iotype_out_SSTL25_I_bank2/fuzz.v(11[8:35])
    defparam out0_r_5.GSR = "ENABLED";
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    VLO i18 (.Z(GND_net));
    
endmodule
//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

