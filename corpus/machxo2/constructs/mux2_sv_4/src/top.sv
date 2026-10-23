module top (
    input clk,
    input [3:0] a,
    input [3:0] b,
    input s,
    output logic [3:0] y
);
  always_ff @(posedge clk) y <= s ? b : a;
endmodule
