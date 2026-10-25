module top (
    input [0:0] clk,
    input [0:0] a,
    input [0:0] b,
    output reg [0:0] y
);
  wire [0:0] x;
  genvar i;
  generate for (i = 0; i < 1; i = i + 1) begin : gb
    assign x[i] = ~(a[i] ^ b[i]);
  end endgenerate
  always @(posedge clk) y <= &x;
endmodule
