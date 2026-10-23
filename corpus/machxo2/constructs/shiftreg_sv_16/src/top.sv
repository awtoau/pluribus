module top (
    input clk,
    input din,
    output logic [15:0] q
);
  always_ff @(posedge clk) q <= {q[14:0], din};
endmodule
