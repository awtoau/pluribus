module top (
    input clk,
    input din,
    output logic [3:0] q
);
  always_ff @(posedge clk) q <= {q[2:0], din};
endmodule
