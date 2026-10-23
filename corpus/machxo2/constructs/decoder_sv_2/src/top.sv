module top (
    input clk,
    input en,
    input [1:0] s,
    output logic [3:0] y
);
  always_ff @(posedge clk) y <= en ? (4'd1 << s) : 4'd0;
endmodule
