module top (
    input clk,
    input en,
    input d,
    output logic q
);
  always_ff @(posedge clk) if (en) q <= d;
endmodule
