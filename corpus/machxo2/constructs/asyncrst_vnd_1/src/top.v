module top (clk, rst, d, q);
  input clk;
  input rst;
  input d;
  output q;
  FD1S3DX #(.GSR("DISABLED")) f0 (.D(d[0]), .CK(clk), .CD(rst), .Q(q[0]));
endmodule
