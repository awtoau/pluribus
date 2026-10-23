module c_updown_v95_1 (clk, up, q);
  input clk, up;
  output [0:0] q;
  reg [0:0] q;
  always @(posedge clk) if (up) q <= q + 1; else q <= q - 1;
endmodule
