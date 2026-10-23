module top (clk, en, s, y);
  input [0:0] clk;
  input [0:0] en;
  input [2:0] s;
  output [7:0] y;
  reg [7:0] y;
  wire [7:0] z;
  LUT4 #(.init(16'h0100)) l0 (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(z[0]));
  LUT4 #(.init(16'h0200)) l1 (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(z[1]));
  LUT4 #(.init(16'h0400)) l2 (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(z[2]));
  LUT4 #(.init(16'h0800)) l3 (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(z[3]));
  LUT4 #(.init(16'h1000)) l4 (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(z[4]));
  LUT4 #(.init(16'h2000)) l5 (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(z[5]));
  LUT4 #(.init(16'h4000)) l6 (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(z[6]));
  LUT4 #(.init(16'h8000)) l7 (.A(s[0]), .B(s[1]), .C(s[2]), .D(en), .Z(z[7]));
  always @(posedge clk) y <= z;
endmodule
