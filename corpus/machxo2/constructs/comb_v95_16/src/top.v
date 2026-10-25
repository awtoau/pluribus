module top (a, b, c, y);
  input [15:0] a;
  input [15:0] b;
  input [15:0] c;
  output [15:0] y;
  assign y = (a & b) ^ (a | c);
endmodule
