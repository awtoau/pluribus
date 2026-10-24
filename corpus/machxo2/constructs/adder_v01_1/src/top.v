module top (
    input [0:0] clk,
    input [0:0] a,
    input [0:0] b,
    output reg [1:0] y
);
  wire [1:0] c;
  wire [0:0] s;
  assign c[0] = 1'b0;
  genvar i;
  generate for (i = 0; i < 1; i = i + 1) begin : fa
    assign s[i] = a[i] ^ b[i] ^ c[i];
    assign c[i+1] = (a[i] & b[i]) | (c[i] & (a[i] ^ b[i]));
  end endgenerate
  always @(posedge clk) y <= {c[1], s};
endmodule
