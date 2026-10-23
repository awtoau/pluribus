module top (
    input clk,
    input [7:0] a,
    input [7:0] b,
    output logic y
);
  always_ff @(posedge clk) y <= (a == b);
endmodule
