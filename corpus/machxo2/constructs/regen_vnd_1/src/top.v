module top (clk, en, d, q);
  input clk;
  input en;
  input d;
  output q;
  FD1P3AX #(.GSR("DISABLED")) f0 (.D(d[0]), .SP(en), .CK(clk), .Q(q[0]));
endmodule
