module top (
    input clk,
    input en,
    input s,
    output logic [1:0] y
);
  always_ff @(posedge clk) y <= en ? (2'd1 << s) : 2'd0;
endmodule
