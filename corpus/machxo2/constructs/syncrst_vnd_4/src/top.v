module top (clk, rst, d, q);
  input [0:0] clk;
  input [0:0] rst;
  input [3:0] d;
  output [3:0] q;
  FD1P3IX #(.GSR("DISABLED")) f0 (.D(d[0]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[0]));
  FD1P3IX #(.GSR("DISABLED")) f1 (.D(d[1]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[1]));
  FD1P3IX #(.GSR("DISABLED")) f2 (.D(d[2]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[2]));
  FD1P3IX #(.GSR("DISABLED")) f3 (.D(d[3]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[3]));
endmodule
