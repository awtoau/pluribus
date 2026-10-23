module top (clk, en, s, y);
  input clk;
  input en;
  input [1:0] s;
  output [3:0] y;
  reg [3:0] y;
  wire [3:0] z;
  LUT4 #(.INIT(16'h1100)) l0 (.A(s[0]), .B(s[1]), .C(1'b0), .D(en), .Z(z[0]));
  LUT4 #(.INIT(16'h2200)) l1 (.A(s[0]), .B(s[1]), .C(1'b0), .D(en), .Z(z[1]));
  LUT4 #(.INIT(16'h4400)) l2 (.A(s[0]), .B(s[1]), .C(1'b0), .D(en), .Z(z[2]));
  LUT4 #(.INIT(16'h8800)) l3 (.A(s[0]), .B(s[1]), .C(1'b0), .D(en), .Z(z[3]));
  always @(posedge clk) y <= z;
endmodule
