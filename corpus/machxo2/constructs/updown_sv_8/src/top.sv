module top (
    input clk,
    input up,
    output logic [7:0] q
);
  always_ff @(posedge clk) q <= up ? q + 1'b1 : q - 1'b1;
endmodule
