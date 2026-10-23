module c_mux4_sv_16 (input logic [15:0] a, b, c, d, input logic [1:0] s, output logic [15:0] y);
  always_comb begin
    unique case (s)
      2'd0: y = a;
      2'd1: y = b;
      2'd2: y = c;
      2'd3: y = d;
    endcase
  end
endmodule
