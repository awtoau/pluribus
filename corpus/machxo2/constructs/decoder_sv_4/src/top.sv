module top (
    input clk,
    input en,
    input [3:0] s,
    output logic [15:0] y
);
  always_ff @(posedge clk) y <= en ? (16'd1 << s) : 16'd0;
endmodule
