module top (
    input clk,
    input a,
    input b,
    output logic [1:0] y
);
  always_ff @(posedge clk) y <= {1'b0, a} + {1'b0, b};
endmodule
