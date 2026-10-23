module c_updown_sv_1 (input logic clk, input logic up, output logic [0:0] q);
  always_ff @(posedge clk) q <= up ? q + 1'b1 : q - 1'b1;
endmodule
