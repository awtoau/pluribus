module top (
    input [0:0] clk,
    input [0:0] din,
    output reg [15:0] q
);
  genvar i;
  generate for (i = 1; i < 16; i = i + 1) begin : st
    always @(posedge clk) q[i] <= q[i-1];
  end endgenerate
  always @(posedge clk) q[0] <= din;
endmodule
