module c_counter_v95_8 (clk, q);
  input clk;
  output [7:0] q;
  reg [7:0] q;
  always @(posedge clk) q <= q + 1;
endmodule
