module top (clk, din, q);
  input clk;
  input din;
  output q;
  FD1S3AX #(.GSR("DISABLED")) f0 (.D(din), .CK(clk), .Q(q[0]));
endmodule
