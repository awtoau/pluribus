module top (clk, a, b, y);
  input clk;
  input [3:0] a;
  input [3:0] b;
  output y;
  reg y;
  (* syn_keep = 1 *) wire [3:0] x;
  assign x = ~(a ^ b);
  always @(posedge clk) y <= &x;
endmodule
