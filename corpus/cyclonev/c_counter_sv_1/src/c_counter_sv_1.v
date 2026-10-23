module c_counter_sv_1 (input logic clk, output logic [0:0] q);
  always_ff @(posedge clk) q <= q + 1'b1;
endmodule
