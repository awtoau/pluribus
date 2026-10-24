module top (
    input [7:0] a,
    input [7:0] b,
    input [7:0] c,
    output [7:0] y
);
  genvar i;
  generate for (i = 0; i < 8; i = i + 1) begin : g
    assign y[i] = (a[i] & b[i]) ^ (a[i] | c[i]);
  end endgenerate
endmodule
