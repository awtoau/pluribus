module core (clk, a, b, c, d, s, y);
  input clk;
  input [15:0] a;
  input [15:0] b;
  input [15:0] c;
  input [15:0] d;
  input [1:0] s;
  output [15:0] y;
  reg [15:0] y;
  always @(posedge clk) y <= s[1] ? (s[0] ? d : c) : (s[0] ? b : a);
endmodule

module top (clk, a, b, c, d, s, par);
  input clk;
  input [15:0] a;
  input [15:0] b;
  input [15:0] c;
  input [15:0] d;
  input [1:0] s;
  output par;
  reg par;
  wire [15:0] y_w;
  core u0 (.clk(clk), .a(a), .b(b), .c(c), .d(d), .s(s), .y(y_w));
  always @(posedge clk) par <= (^y_w);
endmodule
