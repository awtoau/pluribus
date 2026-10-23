module top (clk, a, b, y);
  input clk;
  input a;
  input b;
  output y;
  reg y;
  (* syn_keep = 1 *) wire [1:0] d;
  assign d = {1'b0, a} - {1'b0, b};
  always @(posedge clk) y <= d[1];
endmodule
