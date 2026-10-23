module top (
    input clk,
    input [7:0] a,
    input [7:0] b,
    input s,
    output logic [7:0] y
);
  always_ff @(posedge clk) y <= s ? b : a;
endmodule
