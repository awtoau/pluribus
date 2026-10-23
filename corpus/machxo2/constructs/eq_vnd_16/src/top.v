module top (clk, a, b, y);
  input clk;
  input [15:0] a;
  input [15:0] b;
  output y;
  reg y;
  (* syn_keep = 1 *) wire [15:0] x;
  assign x = ~(a ^ b);
  always @(posedge clk) y <= &x;
endmodule
