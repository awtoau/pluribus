module top (clk, en, d, q);
  input clk;
  input en;
  input [3:0] d;
  output [3:0] q;
  FD1P3AX #(.GSR("DISABLED")) f0 (.D(d[0]), .SP(en), .CK(clk), .Q(q[0]));
  FD1P3AX #(.GSR("DISABLED")) f1 (.D(d[1]), .SP(en), .CK(clk), .Q(q[1]));
  FD1P3AX #(.GSR("DISABLED")) f2 (.D(d[2]), .SP(en), .CK(clk), .Q(q[2]));
  FD1P3AX #(.GSR("DISABLED")) f3 (.D(d[3]), .SP(en), .CK(clk), .Q(q[3]));
endmodule
