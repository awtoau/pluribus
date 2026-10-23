module top (
    input [3:0] a,
    input [3:0] b,
    input [3:0] c,
    output logic [3:0] y
);
  for (genvar i = 0; i < 4; i++) begin : g
    assign y[i] = (a[i] & b[i]) ^ (a[i] | c[i]);
  end
endmodule
