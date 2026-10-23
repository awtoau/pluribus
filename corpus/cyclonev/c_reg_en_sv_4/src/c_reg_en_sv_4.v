module c_reg_en_sv_4 (input logic clk, en, input logic [3:0] d, output logic [3:0] q);
  always_ff @(posedge clk) if (en) q <= d;
endmodule
