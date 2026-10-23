module top (
    input clk,
    input en,
    output logic [7:0] q
);
  always_ff @(posedge clk) if (en) q <= q + 1'b1;
endmodule
