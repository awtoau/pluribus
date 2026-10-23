module c_counter_sv_16 (input logic clk, output logic [15:0] q);
  always_ff @(posedge clk) q <= q + 1'b1;
endmodule
