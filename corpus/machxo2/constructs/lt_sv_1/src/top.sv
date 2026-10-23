module top (
    input clk,
    input a,
    input b,
    output logic y
);
  logic signed sa, sb;
  assign sa = a;
  assign sb = b;
  always_ff @(posedge clk) y <= (sa < sb);
endmodule
