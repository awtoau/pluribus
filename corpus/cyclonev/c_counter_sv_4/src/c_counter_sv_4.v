module c_counter_sv_4 (input logic clk, output logic [3:0] q);
  always_ff @(posedge clk) q <= q + 1'b1;
endmodule
