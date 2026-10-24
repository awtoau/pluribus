module top (
    input [0:0] clk,
    input [0:0] en,
    output reg [15:0] q
);
  always @(posedge clk) if (en) q <= q + 1'b1;
endmodule
