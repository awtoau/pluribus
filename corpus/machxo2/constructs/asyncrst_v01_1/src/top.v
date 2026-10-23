module top (
    input [0:0] clk,
    input [0:0] rst,
    input [0:0] d,
    output reg [0:0] q
);
  always @(posedge clk or posedge rst) if (rst) q <= 1'd0; else q <= d;
endmodule
