module top (
    input [0:0] a,
    input [0:0] b,
    input [0:0] c,
    output [0:0] y
);
  genvar i;
  generate for (i = 0; i < 1; i = i + 1) begin : g
    assign y[i] = (a[i] & b[i]) ^ (a[i] | c[i]);
  end endgenerate
endmodule
