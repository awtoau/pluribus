module top (
    input clk,
    input up,
    output logic q
);
  always_ff @(posedge clk) q <= up ? q + 1'b1 : q - 1'b1;
endmodule
