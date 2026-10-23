module top (
    input clk,
    input a,
    input b,
    output logic y
);
  always_ff @(posedge clk) y <= (a == b);
endmodule
