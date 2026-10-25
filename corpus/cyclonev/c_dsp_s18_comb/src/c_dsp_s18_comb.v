(* multstyle = "dsp" *) module c_dsp_s18_comb (input signed [17:0] a, b, output signed [35:0] p);
  assign p = a * b;
endmodule
