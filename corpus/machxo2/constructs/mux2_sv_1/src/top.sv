module top (
    input clk,
    input a,
    input b,
    input s,
    output logic y
);
  always_ff @(posedge clk) y <= s ? b : a;
endmodule
