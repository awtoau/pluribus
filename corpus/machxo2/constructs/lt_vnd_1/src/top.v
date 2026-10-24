module top (clk, a, b, y);
  input [0:0] clk;
  input [0:0] a;
  input [0:0] b;
  output [0:0] y;
  reg [0:0] y;
  (* syn_keep = 1 *) wire [1:0] d;
  assign d = {1'b0, a} - {1'b0, b};
  always @(posedge clk) y <= d[1];
endmodule
