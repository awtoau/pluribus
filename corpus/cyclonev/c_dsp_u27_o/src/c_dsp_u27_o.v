(* multstyle = "dsp" *) module c_dsp_u27_o (input clk, input [26:0] a, b, output reg [53:0] p);
  always @(posedge clk) p <= a * b;
endmodule
