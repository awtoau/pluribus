module top (clk, rst, d, q);
  input [0:0] clk;
  input [0:0] rst;
  input [0:0] d;
  output [0:0] q;
  FD1S3DX #(.GSR("DISABLED")) f0 (.D(d[0]), .CK(clk), .CD(rst), .Q(q[0]));
endmodule
