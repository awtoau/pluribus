module c_counter_v95_4 (clk, q);
  input clk;
  output [3:0] q;
  reg [3:0] q;
  always @(posedge clk) q <= q + 1;
endmodule
