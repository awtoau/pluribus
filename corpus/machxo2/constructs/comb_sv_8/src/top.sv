module top (
    input [7:0] a,
    input [7:0] b,
    input [7:0] c,
    output logic [7:0] y
);
  for (genvar i = 0; i < 8; i++) begin : g
    assign y[i] = (a[i] & b[i]) ^ (a[i] | c[i]);
  end
endmodule
