(* multstyle = "dsp" *) module c_dsp_u18_o (input clk, input [17:0] a, b, output reg [35:0] p);
  always @(posedge clk) p <= a * b;
endmodule
