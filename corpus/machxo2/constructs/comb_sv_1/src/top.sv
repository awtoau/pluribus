module top (
    input a,
    input b,
    input c,
    output logic y
);
  for (genvar i = 0; i < 1; i++) begin : g
    assign y[i] = (a[i] & b[i]) ^ (a[i] | c[i]);
  end
endmodule
