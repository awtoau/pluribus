module c_reg_en_v95_1 (clk, en, d, q);
  input clk, en;
  input [0:0] d;
  output [0:0] q;
  reg [0:0] q;
  always @(posedge clk) if (en) q <= d;
endmodule
