module top (
    input [0:0] clk,
    input [0:0] rst,
    input [15:0] d,
    output reg [15:0] q
);
  always @(posedge clk) if (rst) q <= 16'd0; else q <= d;
endmodule
