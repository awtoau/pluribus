module top (clk, rst, d, q);
  input clk;
  input rst;
  input [7:0] d;
  output [7:0] q;
  FD1S3DX #(.GSR("DISABLED")) f0 (.D(d[0]), .CK(clk), .CD(rst), .Q(q[0]));
  FD1S3DX #(.GSR("DISABLED")) f1 (.D(d[1]), .CK(clk), .CD(rst), .Q(q[1]));
  FD1S3DX #(.GSR("DISABLED")) f2 (.D(d[2]), .CK(clk), .CD(rst), .Q(q[2]));
  FD1S3DX #(.GSR("DISABLED")) f3 (.D(d[3]), .CK(clk), .CD(rst), .Q(q[3]));
  FD1S3DX #(.GSR("DISABLED")) f4 (.D(d[4]), .CK(clk), .CD(rst), .Q(q[4]));
  FD1S3DX #(.GSR("DISABLED")) f5 (.D(d[5]), .CK(clk), .CD(rst), .Q(q[5]));
  FD1S3DX #(.GSR("DISABLED")) f6 (.D(d[6]), .CK(clk), .CD(rst), .Q(q[6]));
  FD1S3DX #(.GSR("DISABLED")) f7 (.D(d[7]), .CK(clk), .CD(rst), .Q(q[7]));
endmodule
