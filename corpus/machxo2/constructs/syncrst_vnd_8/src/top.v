module top (clk, rst, d, q);
  input [0:0] clk;
  input [0:0] rst;
  input [7:0] d;
  output [7:0] q;
  FD1P3IX #(.GSR("DISABLED")) f0 (.D(d[0]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[0]));
  FD1P3IX #(.GSR("DISABLED")) f1 (.D(d[1]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[1]));
  FD1P3IX #(.GSR("DISABLED")) f2 (.D(d[2]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[2]));
  FD1P3IX #(.GSR("DISABLED")) f3 (.D(d[3]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[3]));
  FD1P3IX #(.GSR("DISABLED")) f4 (.D(d[4]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[4]));
  FD1P3IX #(.GSR("DISABLED")) f5 (.D(d[5]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[5]));
  FD1P3IX #(.GSR("DISABLED")) f6 (.D(d[6]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[6]));
  FD1P3IX #(.GSR("DISABLED")) f7 (.D(d[7]), .SP(1'b1), .CD(rst), .CK(clk), .Q(q[7]));
endmodule
