module top (
    input clk,
    input en,
    output logic q
);
  always_ff @(posedge clk) if (en) q <= q + 1'b1;
endmodule
