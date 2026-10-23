module top (
    input clk,
    input [7:0] a,
    input [7:0] b,
    output logic y
);
  logic signed [7:0] sa, sb;
  assign sa = a;
  assign sb = b;
  always_ff @(posedge clk) y <= (sa < sb);
endmodule
