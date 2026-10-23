module top (
    input clk,
    input rst,
    input d,
    output logic q
);
  always_ff @(posedge clk or posedge rst) if (rst) q <= 1'd0; else q <= d;
endmodule
