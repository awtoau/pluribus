module top (a, b, c, y);
  input [7:0] a;
  input [7:0] b;
  input [7:0] c;
  output [7:0] y;
  assign y = (a & b) ^ (a | c);
endmodule
