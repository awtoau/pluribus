module fuzz(input wire clk,output wire out0);
 wire g=1'b0; wire [7:0] o;
 DP8KC #(.DATA_WIDTH_A(18),.DATA_WIDTH_B(18),.REGMODE_A("OUTREG"),.REGMODE_B("NOREG"),.WRITEMODE_A("READBEFOREWRITE"),.WRITEMODE_B("READBEFOREWRITE"))
) u0 (
    .CLKA(clk),.CEA(g),.OCEA(g),.WEA(g),.CSA2(g),.CSA1(g),.CSA0(g),.RSTA(g),
    .ADA9(g),.ADA8(g),.ADA7(g),.ADA6(g),.ADA5(g),.ADA4(g),.ADA3(g),.ADA2(g),.ADA1(g),.ADA0(g),
    .DIA7(g),.DIA6(g),.DIA5(g),.DIA4(g),.DIA3(g),.DIA2(g),.DIA1(g),.DIA0(g),
    .DOA7(o[7]),.DOA6(o[6]),.DOA5(o[5]),.DOA4(o[4]),.DOA3(o[3]),.DOA2(o[2]),.DOA1(o[1]),.DOA0(o[0]),
    .CLKB(clk),.CEB(g),.OCEB(g),.WEB(g),.CSB2(g),.CSB1(g),.CSB0(g),.RSTB(g),
    .ADB9(g),.ADB8(g),.ADB7(g),.ADB6(g),.ADB5(g),.ADB4(g),.ADB3(g),.ADB2(g),.ADB1(g),.ADB0(g),
    .DIB7(g),.DIB6(g),.DIB5(g),.DIB4(g),.DIB3(g),.DIB2(g),.DIB1(g),.DIB0(g)
);
 reg r; always @(posedge clk) r<=^o; assign out0=r;
endmodule
