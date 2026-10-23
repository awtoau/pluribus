module top (
    input clk,
    input en,
    input [15:0] d,
    output logic [15:0] q
);
  always_ff @(posedge clk) if (en) q <= d;
endmodule
