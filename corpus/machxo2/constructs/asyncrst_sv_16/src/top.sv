module top (
    input clk,
    input rst,
    input [15:0] d,
    output logic [15:0] q
);
  always_ff @(posedge clk or posedge rst) if (rst) q <= 16'd0; else q <= d;
endmodule
