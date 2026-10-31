module top(input clk, input i0, input i1, input i2, output q);
  reg r;
  always @(posedge clk) r <= ((&i0) | (&{i1, i2}));
  assign q = r;
endmodule
