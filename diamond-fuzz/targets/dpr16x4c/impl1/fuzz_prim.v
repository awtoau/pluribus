// Verilog netlist produced by program LSE :  version Diamond (64-bit) 3.14.0.75.2
// Netlist written on Mon Jun 29 22:48:00 2026
//
// Verilog Description of module fuzz
//

module fuzz (clk, out0) /* synthesis syn_module_defined=1 */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(1[8:12])
    input clk;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(2[16:19])
    output out0;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(3[17:21])
    
    wire clk_c /* synthesis is_clock=1, SET_AS_NETWORK=clk_c */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(2[16:19])
    
    wire GND_net, out0_c;
    wire [3:0]do_w;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(7[12:16])
    wire [3:0]q;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(15[11:12])
    
    wire VCC_net;
    
    VHI i16 (.Z(VCC_net));
    PUR PUR_INST (.PUR(VCC_net));
    defparam PUR_INST.RST_PULSE = 1;
    OB out0_pad (.I(out0_c), .O(out0));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(3[17:21])
    GSR GSR_INST (.GSR(VCC_net));
    DPR16X4C u0 (.DI0(GND_net), .DI1(GND_net), .DI2(GND_net), .DI3(GND_net), 
            .WAD0(GND_net), .WAD1(GND_net), .WAD2(GND_net), .WAD3(GND_net), 
            .WCK(clk_c), .WRE(GND_net), .RAD0(GND_net), .RAD1(GND_net), 
            .RAD2(GND_net), .RAD3(GND_net), .DO0(do_w[0]), .DO1(do_w[1]), 
            .DO2(do_w[2]), .DO3(do_w[3])) /* synthesis syn_instantiated=1 */ ;
    defparam u0.initval = "0x0000000000000000";
    TSALL TSALL_INST (.TSALL(GND_net));
    VLO i1 (.Z(GND_net));
    IB clk_pad (.I(clk), .O(clk_c));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(2[16:19])
    FD1S3AX q_i1 (.D(do_w[1]), .CK(clk_c), .Q(q[1]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(16[8:33])
    defparam q_i1.GSR = "ENABLED";
    FD1S3AX q_i2 (.D(do_w[2]), .CK(clk_c), .Q(q[2]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(16[8:33])
    defparam q_i2.GSR = "ENABLED";
    FD1S3AX q_i3 (.D(do_w[3]), .CK(clk_c), .Q(q[3]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(16[8:33])
    defparam q_i3.GSR = "ENABLED";
    FD1S3AX q_i0 (.D(do_w[0]), .CK(clk_c), .Q(q[0]));   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(16[8:33])
    defparam q_i0.GSR = "ENABLED";
    LUT4 i3_4_lut (.A(q[0]), .B(q[2]), .C(q[1]), .D(q[3]), .Z(out0_c)) /* synthesis lut_function=(!(A (B (C (D)+!C !(D))+!B !(C (D)+!C !(D)))+!A !(B (C (D)+!C !(D))+!B !(C (D)+!C !(D))))) */ ;   // /mnt/2tb/git/awto-2000/fpga/diamond/fuzz/targets/dpr16x4c/fuzz.v(17[15:17])
    defparam i3_4_lut.init = 16'h6996;
    
endmodule
//
// Verilog Description of module PUR
// module not written out since it is a black-box. 
//

//
// Verilog Description of module TSALL
// module not written out since it is a black-box. 
//

