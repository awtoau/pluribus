module top (
    input clk,
    input [3:0] a,
    input [3:0] b,
    output logic y
);
  always_ff @(posedge clk) y <= (a == b);
endmodule
