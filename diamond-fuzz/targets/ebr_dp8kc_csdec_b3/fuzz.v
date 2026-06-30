module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire [7:0] doa_w;
DP8KC #(
    .DATA_WIDTH_A(9), .DATA_WIDTH_B(9),
    .CSDECODE_A("0b000"), .CSDECODE_B("0b011"),
    .REGMODE_A("NOREG"), .REGMODE_B("NOREG"),
    .WRITEMODE_A("NORMAL"), .WRITEMODE_B("NORMAL"),
    .RESETMODE("SYNC"), .GSR("DISABLED"),
    .ASYNC_RESET_RELEASE("SYNC")
) u0 (
    .CLKA(clk), .CEA(gnd), .OCEA(gnd), .WEA(gnd), .CSA2(gnd), .CSA1(gnd), .CSA0(gnd), .RSTA(gnd),
    .CLKB(clk), .CEB(gnd), .OCEB(gnd), .WEB(gnd), .CSB2(gnd), .CSB1(gnd), .CSB0(gnd), .RSTB(gnd),
    .ADA8(gnd),.ADA7(gnd),.ADA6(gnd),.ADA5(gnd),.ADA4(gnd),.ADA3(gnd),.ADA2(gnd),.ADA1(gnd),.ADA0(gnd),
    .ADB8(gnd),.ADB7(gnd),.ADB6(gnd),.ADB5(gnd),.ADB4(gnd),.ADB3(gnd),.ADB2(gnd),.ADB1(gnd),.ADB0(gnd),
    .DIA8(gnd),.DIA7(gnd),.DIA6(gnd),.DIA5(gnd),.DIA4(gnd),.DIA3(gnd),.DIA2(gnd),.DIA1(gnd),.DIA0(gnd),
    .DIB8(gnd),.DIB7(gnd),.DIB6(gnd),.DIB5(gnd),.DIB4(gnd),.DIB3(gnd),.DIB2(gnd),.DIB1(gnd),.DIB0(gnd),
    .DOA8(),.DOA7(doa_w[7]),.DOA6(doa_w[6]),.DOA5(doa_w[5]),.DOA4(doa_w[4]),
    .DOA3(doa_w[3]),.DOA2(doa_w[2]),.DOA1(doa_w[1]),.DOA0(doa_w[0]),
    .DOB8(),.DOB7(),.DOB6(),.DOB5(),.DOB4(),.DOB3(),.DOB2(),.DOB1(),.DOB0()
);
reg out0_r;
always @(posedge clk) out0_r <= ^doa_w;
assign out0 = out0_r;

endmodule
