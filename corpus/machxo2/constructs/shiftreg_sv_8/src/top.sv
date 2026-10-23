module top (
    input clk,
    input din,
    output logic [7:0] q
);
  always_ff @(posedge clk) q <= {q[6:0], din};
endmodule
