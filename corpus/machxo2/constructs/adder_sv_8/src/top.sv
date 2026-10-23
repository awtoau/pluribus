module top (
    input clk,
    input [7:0] a,
    input [7:0] b,
    output logic [8:0] y
);
  always_ff @(posedge clk) y <= {1'b0, a} + {1'b0, b};
endmodule
