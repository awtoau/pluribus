module c_reg_en_v95_16 (clk, en, d, q);
  input clk, en;
  input [15:0] d;
  output [15:0] q;
  reg [15:0] q;
  always @(posedge clk) if (en) q <= d;
endmodule
