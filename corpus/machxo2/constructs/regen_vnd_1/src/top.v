module top (clk, en, d, q);
  input [0:0] clk;
  input [0:0] en;
  input [0:0] d;
  output [0:0] q;
  FD1P3AX #(.GSR("DISABLED")) f0 (.D(d[0]), .SP(en), .CK(clk), .Q(q[0]));
endmodule
