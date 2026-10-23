module top (
    input [0:0] clk,
    input [7:0] a,
    input [7:0] b,
    input [0:0] s,
    output reg [7:0] y
);
  wire [7:0] m;
  genvar i;
  generate for (i = 0; i < 8; i = i + 1) begin : g
    assign m[i] = s ? b[i] : a[i];
  end endgenerate
  always @(posedge clk) y <= m;
endmodule
