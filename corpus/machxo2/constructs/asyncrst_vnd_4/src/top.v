module top (clk, rst, d, q);
  input [0:0] clk;
  input [0:0] rst;
  input [3:0] d;
  output [3:0] q;
  FD1S3DX #(.GSR("DISABLED")) f0 (.D(d[0]), .CK(clk), .CD(rst), .Q(q[0]));
  FD1S3DX #(.GSR("DISABLED")) f1 (.D(d[1]), .CK(clk), .CD(rst), .Q(q[1]));
  FD1S3DX #(.GSR("DISABLED")) f2 (.D(d[2]), .CK(clk), .CD(rst), .Q(q[2]));
  FD1S3DX #(.GSR("DISABLED")) f3 (.D(d[3]), .CK(clk), .CD(rst), .Q(q[3]));
endmodule
