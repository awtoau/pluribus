module top (
    input [0:0] clk,
    input [0:0] din,
    output reg [0:0] q
);
  always @(posedge clk) q <= din;
endmodule
