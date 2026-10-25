module top (a, b, c, y);
  input [3:0] a;
  input [3:0] b;
  input [3:0] c;
  output [3:0] y;
  assign y = (a & b) ^ (a | c);
endmodule
