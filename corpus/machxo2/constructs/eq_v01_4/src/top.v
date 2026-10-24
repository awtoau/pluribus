module top (
    input [0:0] clk,
    input [3:0] a,
    input [3:0] b,
    output reg [0:0] y
);
  wire [3:0] x;
  genvar i;
  generate for (i = 0; i < 4; i = i + 1) begin : gb
    assign x[i] = ~(a[i] ^ b[i]);
  end endgenerate
  always @(posedge clk) y <= &x;
endmodule
