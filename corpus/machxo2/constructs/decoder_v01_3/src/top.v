module top (
    input [0:0] clk,
    input [0:0] en,
    input [2:0] s,
    output reg [7:0] y
);
  localparam M = 8;
  always @(posedge clk) y <= en ? (8'd1 << s) : 8'd0;
endmodule
