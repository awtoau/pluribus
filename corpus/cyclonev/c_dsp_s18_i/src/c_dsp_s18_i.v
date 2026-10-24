(* multstyle = "dsp" *) module c_dsp_s18_i (input clk, input signed [17:0] a, b, output signed [35:0] p);
  reg signed [17:0] ra, rb;
  always @(posedge clk) begin ra <= a; rb <= b; end
  assign p = ra * rb;
endmodule
