module top(input clk, input i0, input i1, output q);
  reg r;
  always @(posedge clk) r <= (~((|i0) & (|i1)));
  assign q = r;
endmodule
