module top (
    input [0:0] clk,
    input [0:0] a,
    input [0:0] b,
    input [0:0] s,
    output reg [0:0] y
);
  wire [0:0] m;
  genvar i;
  generate for (i = 0; i < 1; i = i + 1) begin : g
    assign m[i] = s ? b[i] : a[i];
  end endgenerate
  always @(posedge clk) y <= m;
endmodule
