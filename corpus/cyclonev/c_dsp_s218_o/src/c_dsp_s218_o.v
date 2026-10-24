(* multstyle = "dsp" *) module c_dsp_s218_o (input clk, input signed [17:0] a, b, c, d, output reg signed [36:0] p);
  always @(posedge clk) p <= a * b + c * d;
endmodule
