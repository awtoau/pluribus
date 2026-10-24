module top (
    input [0:0] clk,
    input [3:0] a,
    input [3:0] b,
    output reg [4:0] y
);
  wire [4:0] c;
  wire [3:0] s;
  assign c[0] = 1'b0;
  genvar i;
  generate for (i = 0; i < 4; i = i + 1) begin : fa
    assign s[i] = a[i] ^ b[i] ^ c[i];
    assign c[i+1] = (a[i] & b[i]) | (c[i] & (a[i] ^ b[i]));
  end endgenerate
  always @(posedge clk) y <= {c[4], s};
endmodule
