module top (clk, we, wa, ra, din, dout);
  input [0:0] clk;
  input [0:0] we;
  input [9:0] wa;
  input [9:0] ra;
  input [8:0] din;
  output [8:0] dout;
  wire nca0;
  wire nca1;
  wire nca2;
  wire nca3;
  wire nca4;
  wire nca5;
  wire nca6;
  wire nca7;
  wire nca8;
  DP8KC #(.DATA_WIDTH_A(9), .DATA_WIDTH_B(9), .REGMODE_A("NOREG"), .REGMODE_B("NOREG"), .CSDECODE_A("0b000"), .CSDECODE_B("0b000"), .WRITEMODE_A("NORMAL"), .WRITEMODE_B("NORMAL"), .GSR("DISABLED")) u0 (.CEA(1'b1), .OCEA(1'b1), .CLKA(clk), .WEA(we), .CSA0(1'b0), .CSA1(1'b0), .CSA2(1'b0), .RSTA(1'b0), .CEB(1'b1), .OCEB(1'b1), .CLKB(clk), .WEB(1'b0), .CSB0(1'b0), .CSB1(1'b0), .CSB2(1'b0), .RSTB(1'b0), .DIA0(din[0]), .DIA1(din[1]), .DIA2(din[2]), .DIA3(din[3]), .DIA4(din[4]), .DIA5(din[5]), .DIA6(din[6]), .DIA7(din[7]), .DIA8(din[8]), .DIB0(1'b0), .DIB1(1'b0), .DIB2(1'b0), .DIB3(1'b0), .DIB4(1'b0), .DIB5(1'b0), .DIB6(1'b0), .DIB7(1'b0), .DIB8(1'b0), .ADA0(1'b0), .ADA1(1'b0), .ADA2(1'b0), .ADA3(wa[0]), .ADA4(wa[1]), .ADA5(wa[2]), .ADA6(wa[3]), .ADA7(wa[4]), .ADA8(wa[5]), .ADA9(wa[6]), .ADA10(wa[7]), .ADA11(wa[8]), .ADA12(wa[9]), .ADB0(1'b0), .ADB1(1'b0), .ADB2(1'b0), .ADB3(ra[0]), .ADB4(ra[1]), .ADB5(ra[2]), .ADB6(ra[3]), .ADB7(ra[4]), .ADB8(ra[5]), .ADB9(ra[6]), .ADB10(ra[7]), .ADB11(ra[8]), .ADB12(ra[9]), .DOA0(nca0), .DOA1(nca1), .DOA2(nca2), .DOA3(nca3), .DOA4(nca4), .DOA5(nca5), .DOA6(nca6), .DOA7(nca7), .DOA8(nca8), .DOB0(dout[0]), .DOB1(dout[1]), .DOB2(dout[2]), .DOB3(dout[3]), .DOB4(dout[4]), .DOB5(dout[5]), .DOB6(dout[6]), .DOB7(dout[7]), .DOB8(dout[8]));
endmodule
