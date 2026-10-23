module top (
    input clk,
    input [3:0] a,
    input [3:0] b,
    output logic [4:0] y
);
  always_ff @(posedge clk) y <= {1'b0, a} + {1'b0, b};
endmodule
