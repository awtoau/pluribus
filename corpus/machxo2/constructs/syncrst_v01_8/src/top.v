module top (
    input [0:0] clk,
    input [0:0] rst,
    input [7:0] d,
    output reg [7:0] q
);
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d;
endmodule
