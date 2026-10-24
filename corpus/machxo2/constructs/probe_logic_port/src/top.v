module top (input clk, input d, output logic q);
  always @(posedge clk) q <= d;
endmodule
