module c_reg_en_sv_8 (input logic clk, en, input logic [7:0] d, output logic [7:0] q);
  always_ff @(posedge clk) if (en) q <= d;
endmodule
