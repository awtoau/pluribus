module top (clk, a, b, y);
  input clk;
  input a;
  input b;
  output y;
  reg y;
  (* syn_keep = 1 *) wire x;
  assign x = ~(a ^ b);
  always @(posedge clk) y <= &x;
endmodule
