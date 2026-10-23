module top (clk, din, q);
  input clk;
  input din;
  output [7:0] q;
  FD1S3AX #(.GSR("DISABLED")) f0 (.D(din), .CK(clk), .Q(q[0]));
  FD1S3AX #(.GSR("DISABLED")) f1 (.D(q[0]), .CK(clk), .Q(q[1]));
  FD1S3AX #(.GSR("DISABLED")) f2 (.D(q[1]), .CK(clk), .Q(q[2]));
  FD1S3AX #(.GSR("DISABLED")) f3 (.D(q[2]), .CK(clk), .Q(q[3]));
  FD1S3AX #(.GSR("DISABLED")) f4 (.D(q[3]), .CK(clk), .Q(q[4]));
  FD1S3AX #(.GSR("DISABLED")) f5 (.D(q[4]), .CK(clk), .Q(q[5]));
  FD1S3AX #(.GSR("DISABLED")) f6 (.D(q[5]), .CK(clk), .Q(q[6]));
  FD1S3AX #(.GSR("DISABLED")) f7 (.D(q[6]), .CK(clk), .Q(q[7]));
endmodule
