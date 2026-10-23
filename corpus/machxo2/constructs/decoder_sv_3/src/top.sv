module top (
    input clk,
    input en,
    input [2:0] s,
    output logic [7:0] y
);
  always_ff @(posedge clk) y <= en ? (8'd1 << s) : 8'd0;
endmodule
