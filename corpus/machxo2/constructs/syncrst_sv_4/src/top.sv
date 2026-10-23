module top (
    input clk,
    input rst,
    input [3:0] d,
    output logic [3:0] q
);
  always_ff @(posedge clk) if (rst) q <= 4'd0; else q <= d;
endmodule
