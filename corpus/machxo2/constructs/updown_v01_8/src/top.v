module top (
    input [0:0] clk,
    input [0:0] up,
    output reg [7:0] q
);
  always @(posedge clk) q <= up ? q + 1'b1 : q - 1'b1;
endmodule
