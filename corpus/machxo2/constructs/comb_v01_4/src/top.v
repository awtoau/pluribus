module top (
    input [3:0] a,
    input [3:0] b,
    input [3:0] c,
    output [3:0] y
);
  genvar i;
  generate for (i = 0; i < 4; i = i + 1) begin : g
    assign y[i] = (a[i] & b[i]) ^ (a[i] | c[i]);
  end endgenerate
endmodule
