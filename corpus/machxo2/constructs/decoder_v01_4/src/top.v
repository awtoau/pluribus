module top (
    input [0:0] clk,
    input [0:0] en,
    input [3:0] s,
    output reg [15:0] y
);
  localparam M = 16;
  always @(posedge clk) y <= en ? (16'd1 << s) : 16'd0;
endmodule
