module top(input clk, input i0, input i1, input i2, input i3, input i4, input i5, output q);
  reg r;
  always @(posedge clk) r <= ((^{i0, i1, i2}) ^ (^{i3, i4, i5}));
  assign q = r;
endmodule
