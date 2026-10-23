module top (
    input clk,
    input en,
    input [3:0] d,
    output logic [3:0] q
);
  always_ff @(posedge clk) if (en) q <= d;
endmodule
