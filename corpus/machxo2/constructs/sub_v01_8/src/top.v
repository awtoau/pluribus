module top (
    input [0:0] clk,
    input [7:0] a,
    input [7:0] b,
    output reg [8:0] y
);
  wire signed [8:0] sa = $signed({1'b0, a});
  wire signed [8:0] sb = $signed({1'b0, b});
  always @(posedge clk) y <= sa - sb;
endmodule
