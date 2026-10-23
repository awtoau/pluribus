module c_decoder_sv_2 (input logic [1:0] sel, output logic [3:0] y);
  always_comb begin
    y = '0;
    y[sel] = 1'b1;
  end
endmodule
