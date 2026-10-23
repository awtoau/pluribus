module top (clk, rst, d, q);
  input clk;
  input rst;
  input d;
  output q;
  FD1P3IX #(.GSR("DISABLED")) f0 (.D(d[0]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[0]));
endmodule
