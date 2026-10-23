module top (clk, din, q);
  input [0:0] clk;
  input [0:0] din;
  output [0:0] q;
  FD1S3AX #(.GSR("DISABLED")) f0 (.D(din), .CK(clk), .Q(q[0]));
endmodule
