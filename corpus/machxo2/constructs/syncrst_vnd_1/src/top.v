module top (clk, rst, d, q);
  input [0:0] clk;
  input [0:0] rst;
  input [0:0] d;
  output [0:0] q;
  FD1P3IX #(.GSR("DISABLED")) f0 (.D(d[0]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[0]));
endmodule
