module c_decoder_sv_1 (input logic [0:0] sel, output logic [1:0] y);
  always_comb begin
    y = '0;
    y[sel] = 1'b1;
  end
endmodule
