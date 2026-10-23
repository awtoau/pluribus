module top (
    input clk,
    input [15:0] a,
    input [15:0] b,
    input s,
    output logic [15:0] y
);
  always_ff @(posedge clk) y <= s ? b : a;
endmodule
