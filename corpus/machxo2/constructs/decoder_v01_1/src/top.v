module top (
    input [0:0] clk,
    input [0:0] en,
    input [0:0] s,
    output reg [1:0] y
);
  localparam M = 2;
  always @(posedge clk) y <= en ? (2'd1 << s) : 2'd0;
endmodule
