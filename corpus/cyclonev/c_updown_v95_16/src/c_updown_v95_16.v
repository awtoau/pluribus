module c_updown_v95_16 (clk, up, q);
  input clk, up;
  output [15:0] q;
  reg [15:0] q;
  always @(posedge clk) if (up) q <= q + 1; else q <= q - 1;
endmodule
