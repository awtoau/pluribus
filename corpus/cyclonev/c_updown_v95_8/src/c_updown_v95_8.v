module c_updown_v95_8 (clk, up, q);
  input clk, up;
  output [7:0] q;
  reg [7:0] q;
  always @(posedge clk) if (up) q <= q + 1; else q <= q - 1;
endmodule
