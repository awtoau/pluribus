module top (
    input clk,
    input rst,
    input [7:0] d,
    output logic [7:0] q
);
  always_ff @(posedge clk or posedge rst) if (rst) q <= 8'd0; else q <= d;
endmodule
