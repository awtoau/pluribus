module c_decoder_sv_4 (input logic [3:0] sel, output logic [15:0] y);
  always_comb begin
    y = '0;
    y[sel] = 1'b1;
  end
endmodule
