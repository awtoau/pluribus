module top(input clk, input sel, input a, input b, output q);
  reg r;
  always @(posedge clk) r <= sel ? a : b;
  assign q = r;
endmodule
