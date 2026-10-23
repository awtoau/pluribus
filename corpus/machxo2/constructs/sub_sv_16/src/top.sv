module top (
    input clk,
    input [15:0] a,
    input [15:0] b,
    output logic [16:0] y
);
  always_ff @(posedge clk) y <= {1'b0, a} - {1'b0, b};
endmodule
