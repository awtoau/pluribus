module top (
    input [0:0] clk,
    input [7:0] a,
    input [7:0] b,
    output reg [8:0] y
);
  wire [8:0] c;
  wire [7:0] s;
  assign c[0] = 1'b0;
  genvar i;
  generate for (i = 0; i < 8; i = i + 1) begin : fa
    assign s[i] = a[i] ^ b[i] ^ c[i];
    assign c[i+1] = (a[i] & b[i]) | (c[i] & (a[i] ^ b[i]));
  end endgenerate
  always @(posedge clk) y <= {c[8], s};
endmodule
