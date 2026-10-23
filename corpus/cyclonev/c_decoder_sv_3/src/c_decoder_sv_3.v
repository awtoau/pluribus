module c_decoder_sv_3 (input logic [2:0] sel, output logic [7:0] y);
  always_comb begin
    y = '0;
    y[sel] = 1'b1;
  end
endmodule
