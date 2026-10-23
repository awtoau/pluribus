module c_reg_en_v95_8 (clk, en, d, q);
  input clk, en;
  input [7:0] d;
  output [7:0] q;
  reg [7:0] q;
  always @(posedge clk) if (en) q <= d;
endmodule
