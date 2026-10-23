module top (
    input [0:0] clk,
    input [15:0] a,
    input [15:0] b,
    input [0:0] s,
    output reg [15:0] y
);
  wire [15:0] m;
  genvar i;
  generate for (i = 0; i < 16; i = i + 1) begin : g
    assign m[i] = s ? b[i] : a[i];
  end endgenerate
  always @(posedge clk) y <= m;
endmodule
