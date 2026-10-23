module top (
    input clk,
    input [15:0] a,
    input [15:0] b,
    output logic y
);
  always_ff @(posedge clk) y <= (a == b);
endmodule
