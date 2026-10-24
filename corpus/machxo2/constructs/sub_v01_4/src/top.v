module top (
    input [0:0] clk,
    input [3:0] a,
    input [3:0] b,
    output reg [4:0] y
);
  wire signed [4:0] sa = $signed({1'b0, a});
  wire signed [4:0] sb = $signed({1'b0, b});
  always @(posedge clk) y <= sa - sb;
endmodule
