module top (clk, we, wa, ra, din, dout);
  input clk;
  input we;
  input [8:0] wa;
  input [8:0] ra;
  input [17:0] din;
  output [17:0] dout;
  DP8KC #(.DATA_WIDTH_A(18), .DATA_WIDTH_B(18), .REGMODE_A("NOREG"), .REGMODE_B("NOREG"), .CSDECODE_A("0b000"), .CSDECODE_B("0b000"), .WRITEMODE_A("NORMAL"), .WRITEMODE_B("NORMAL"), .GSR("DISABLED")) u0 (.CEA(1'b1), .CLKA(clk), .WEA(we), .CSA0(1'b0), .CSA1(1'b0), .CSA2(1'b0), .RSTA(1'b0), .CEB(1'b1), .CLKB(clk), .WEB(1'b0), .CSB0(1'b0), .CSB1(1'b0), .CSB2(1'b0), .RSTB(1'b0), .DIA0(din[0]), .DIA1(din[1]), .DIA2(din[2]), .DIA3(din[3]), .DIA4(din[4]), .DIA5(din[5]), .DIA6(din[6]), .DIA7(din[7]), .DIA8(din[8]), .DIA9(din[9]), .DIA10(din[10]), .DIA11(din[11]), .DIA12(din[12]), .DIA13(din[13]), .DIA14(din[14]), .DIA15(din[15]), .DIA16(din[16]), .DIA17(din[17]), .DIB0(1'b0), .DIB1(1'b0), .DIB2(1'b0), .DIB3(1'b0), .DIB4(1'b0), .DIB5(1'b0), .DIB6(1'b0), .DIB7(1'b0), .DIB8(1'b0), .DIB9(1'b0), .DIB10(1'b0), .DIB11(1'b0), .DIB12(1'b0), .DIB13(1'b0), .DIB14(1'b0), .DIB15(1'b0), .DIB16(1'b0), .DIB17(1'b0), .ADA0(wa[0]), .ADA1(wa[1]), .ADA2(wa[2]), .ADA3(wa[3]), .ADA4(wa[4]), .ADA5(wa[5]), .ADA6(wa[6]), .ADA7(wa[7]), .ADA8(wa[8]), .ADA9(1'b0), .ADA10(1'b0), .ADA11(1'b0), .ADA12(1'b0), .ADB0(ra[0]), .ADB1(ra[1]), .ADB2(ra[2]), .ADB3(ra[3]), .ADB4(ra[4]), .ADB5(ra[5]), .ADB6(ra[6]), .ADB7(ra[7]), .ADB8(ra[8]), .ADB9(1'b0), .ADB10(1'b0), .ADB11(1'b0), .ADB12(1'b0), .DOB0(dout[0]), .DOB1(dout[1]), .DOB2(dout[2]), .DOB3(dout[3]), .DOB4(dout[4]), .DOB5(dout[5]), .DOB6(dout[6]), .DOB7(dout[7]), .DOB8(dout[8]), .DOB9(dout[9]), .DOB10(dout[10]), .DOB11(dout[11]), .DOB12(dout[12]), .DOB13(dout[13]), .DOB14(dout[14]), .DOB15(dout[15]), .DOB16(dout[16]), .DOB17(dout[17]));
endmodule
