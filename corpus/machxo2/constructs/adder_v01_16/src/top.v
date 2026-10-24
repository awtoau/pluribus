module top (
    input [0:0] clk,
    input [15:0] a,
    input [15:0] b,
    output reg [16:0] y
);
  wire [16:0] c;
  wire [15:0] s;
  assign c[0] = 1'b0;
  genvar i;
  generate for (i = 0; i < 16; i = i + 1) begin : fa
    assign s[i] = a[i] ^ b[i] ^ c[i];
    assign c[i+1] = (a[i] & b[i]) | (c[i] & (a[i] ^ b[i]));
  end endgenerate
  always @(posedge clk) y <= {c[16], s};
endmodule
