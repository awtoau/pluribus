module top (clk, en, d, q);
  input clk;
  input en;
  input [7:0] d;
  output [7:0] q;
  FD1P3AX #(.GSR("DISABLED")) f0 (.D(d[0]), .SP(en), .CK(clk), .Q(q[0]));
  FD1P3AX #(.GSR("DISABLED")) f1 (.D(d[1]), .SP(en), .CK(clk), .Q(q[1]));
  FD1P3AX #(.GSR("DISABLED")) f2 (.D(d[2]), .SP(en), .CK(clk), .Q(q[2]));
  FD1P3AX #(.GSR("DISABLED")) f3 (.D(d[3]), .SP(en), .CK(clk), .Q(q[3]));
  FD1P3AX #(.GSR("DISABLED")) f4 (.D(d[4]), .SP(en), .CK(clk), .Q(q[4]));
  FD1P3AX #(.GSR("DISABLED")) f5 (.D(d[5]), .SP(en), .CK(clk), .Q(q[5]));
  FD1P3AX #(.GSR("DISABLED")) f6 (.D(d[6]), .SP(en), .CK(clk), .Q(q[6]));
  FD1P3AX #(.GSR("DISABLED")) f7 (.D(d[7]), .SP(en), .CK(clk), .Q(q[7]));
endmodule
