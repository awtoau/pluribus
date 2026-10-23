module top (
    input clk,
    input [3:0] a,
    input [3:0] b,
    output logic y
);
  logic signed [3:0] sa, sb;
  assign sa = a;
  assign sb = b;
  always_ff @(posedge clk) y <= (sa < sb);
endmodule
