module c_counter_sv_8 (input logic clk, output logic [7:0] q);
  always_ff @(posedge clk) q <= q + 1'b1;
endmodule
