module c_reg_en_sv_16 (input logic clk, en, input logic [15:0] d, output logic [15:0] q);
  always_ff @(posedge clk) if (en) q <= d;
endmodule
