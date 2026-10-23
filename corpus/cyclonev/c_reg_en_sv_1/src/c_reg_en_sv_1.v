module c_reg_en_sv_1 (input logic clk, en, input logic [0:0] d, output logic [0:0] q);
  always_ff @(posedge clk) if (en) q <= d;
endmodule
