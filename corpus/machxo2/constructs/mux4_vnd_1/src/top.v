module top (clk, a, b, c, d, s, y);
  input [0:0] clk;
  input [0:0] a;
  input [0:0] b;
  input [0:0] c;
  input [0:0] d;
  input [1:0] s;
  output [0:0] y;
  reg [0:0] y;
  wire [0:0] ma, mb, m;
  LUT4 #(.init(16'hCACA)) la0 (.A(a[0]), .B(b[0]), .C(s[0]), .D(1'b0), .Z(ma[0]));
  LUT4 #(.init(16'hCACA)) lb0 (.A(c[0]), .B(d[0]), .C(s[0]), .D(1'b0), .Z(mb[0]));
  PFUMX p0 (.ALUT(mb[0]), .BLUT(ma[0]), .C0(s[1]), .Z(m[0]));
  always @(posedge clk) y <= m;
endmodule
