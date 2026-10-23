module c_counter_v95_16 (clk, q);
  input clk;
  output [15:0] q;
  reg [15:0] q;
  always @(posedge clk) q <= q + 1;
endmodule
