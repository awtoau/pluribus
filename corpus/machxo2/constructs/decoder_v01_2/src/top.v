module top (
    input [0:0] clk,
    input [0:0] en,
    input [1:0] s,
    output reg [3:0] y
);
  localparam M = 4;
  always @(posedge clk) y <= en ? (4'd1 << s) : 4'd0;
endmodule
