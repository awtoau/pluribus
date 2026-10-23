module top (clk, din, q);
  input [0:0] clk;
  input [0:0] din;
  output [3:0] q;
  FD1S3AX #(.GSR("DISABLED")) f0 (.D(din), .CK(clk), .Q(q[0]));
  FD1S3AX #(.GSR("DISABLED")) f1 (.D(q[0]), .CK(clk), .Q(q[1]));
  FD1S3AX #(.GSR("DISABLED")) f2 (.D(q[1]), .CK(clk), .Q(q[2]));
  FD1S3AX #(.GSR("DISABLED")) f3 (.D(q[2]), .CK(clk), .Q(q[3]));
endmodule
