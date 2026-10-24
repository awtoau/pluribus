module top (
    input [0:0] clk,
    input [0:0] rst,
    input [3:0] d,
    output reg [3:0] q
);
  always @(posedge clk) if (rst) q <= 4'd0; else q <= d;
endmodule
