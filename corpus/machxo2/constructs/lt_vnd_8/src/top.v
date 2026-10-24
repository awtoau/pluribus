module top (clk, a, b, y);
  input [0:0] clk;
  input [7:0] a;
  input [7:0] b;
  output [0:0] y;
  reg [0:0] y;
  (* syn_keep = 1 *) wire [8:0] d;
  assign d = {1'b0, a} - {1'b0, b};
  always @(posedge clk) y <= d[8];
endmodule
