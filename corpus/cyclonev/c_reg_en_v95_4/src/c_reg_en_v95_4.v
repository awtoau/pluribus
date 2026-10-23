module c_reg_en_v95_4 (clk, en, d, q);
  input clk, en;
  input [3:0] d;
  output [3:0] q;
  reg [3:0] q;
  always @(posedge clk) if (en) q <= d;
endmodule
