module top (
    input clk,
    input [15:0] a,
    input [15:0] b,
    output logic y
);
  logic signed [15:0] sa, sb;
  assign sa = a;
  assign sb = b;
  always_ff @(posedge clk) y <= (sa < sb);
endmodule
