(* multstyle = "dsp" *) module c_dsp_s9_io (input clk, input signed [8:0] a, b, output reg signed [17:0] p);
  reg signed [8:0] ra, rb;
  always @(posedge clk) begin ra <= a; rb <= b; end
  always @(posedge clk) p <= ra * rb;
endmodule
