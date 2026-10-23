module top (
    input clk,
    input en,
    input [7:0] d,
    output logic [7:0] q
);
  always_ff @(posedge clk) if (en) q <= d;
endmodule
