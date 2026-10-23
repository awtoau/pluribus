module top (
    input [15:0] a,
    input [15:0] b,
    input [15:0] c,
    output logic [15:0] y
);
  for (genvar i = 0; i < 16; i++) begin : g
    assign y[i] = (a[i] & b[i]) ^ (a[i] | c[i]);
  end
endmodule
