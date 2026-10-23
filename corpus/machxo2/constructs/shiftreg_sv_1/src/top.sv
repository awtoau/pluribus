module top (
    input clk,
    input din,
    output logic q
);
  always_ff @(posedge clk) q <= din;
endmodule
