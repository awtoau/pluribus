module top (
    input [15:0] a,
    input [15:0] b,
    input [15:0] c,
    output [15:0] y
);
  genvar i;
  generate for (i = 0; i < 16; i = i + 1) begin : g
    assign y[i] = (a[i] & b[i]) ^ (a[i] | c[i]);
  end endgenerate
endmodule
