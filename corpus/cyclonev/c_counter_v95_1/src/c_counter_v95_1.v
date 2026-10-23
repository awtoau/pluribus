module c_counter_v95_1 (clk, q);
  input clk;
  output [0:0] q;
  reg [0:0] q;
  always @(posedge clk) q <= q + 1;
endmodule
