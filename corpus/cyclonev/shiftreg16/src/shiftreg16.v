module shiftreg16(input clk, input en, input din, output [15:0] q);
  reg [15:0] sr;
  always @(posedge clk) if (en) sr <= {sr[14:0], din};
  assign q = sr;
endmodule
