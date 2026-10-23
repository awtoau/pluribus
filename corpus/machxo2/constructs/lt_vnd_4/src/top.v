module top (clk, a, b, y);
  input clk;
  input [3:0] a;
  input [3:0] b;
  output y;
  reg y;
  (* syn_keep = 1 *) wire [4:0] d;
  assign d = {1'b0, a} - {1'b0, b};
  always @(posedge clk) y <= d[4];
endmodule
