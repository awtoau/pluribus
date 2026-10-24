(* multstyle = "dsp" *) module c_dsp_s27_o (input clk, input signed [26:0] a, b, output reg signed [53:0] p);
  always @(posedge clk) p <= a * b;
endmodule
