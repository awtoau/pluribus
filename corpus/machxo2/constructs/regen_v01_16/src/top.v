module top (
    input [0:0] clk,
    input [0:0] en,
    input [15:0] d,
    output reg [15:0] q
);
  always @(posedge clk) if (en) q <= d;
endmodule
