module top (
    input [0:0] clk,
    input [15:0] a,
    input [15:0] b,
    output reg [16:0] y
);
  wire signed [16:0] sa = $signed({1'b0, a});
  wire signed [16:0] sb = $signed({1'b0, b});
  always @(posedge clk) y <= sa - sb;
endmodule
