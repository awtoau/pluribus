module top (clk, a, b, s, y);
  input clk;
  input [7:0] a;
  input [7:0] b;
  input s;
  output [7:0] y;
  reg [7:0] y;
  wire [7:0] m;
  LUT4 #(.INIT(16'hCACA)) l0 (.A(a[0]), .B(b[0]), .C(s), .D(1'b0), .Z(m[0]));
  LUT4 #(.INIT(16'hCACA)) l1 (.A(a[1]), .B(b[1]), .C(s), .D(1'b0), .Z(m[1]));
  LUT4 #(.INIT(16'hCACA)) l2 (.A(a[2]), .B(b[2]), .C(s), .D(1'b0), .Z(m[2]));
  LUT4 #(.INIT(16'hCACA)) l3 (.A(a[3]), .B(b[3]), .C(s), .D(1'b0), .Z(m[3]));
  LUT4 #(.INIT(16'hCACA)) l4 (.A(a[4]), .B(b[4]), .C(s), .D(1'b0), .Z(m[4]));
  LUT4 #(.INIT(16'hCACA)) l5 (.A(a[5]), .B(b[5]), .C(s), .D(1'b0), .Z(m[5]));
  LUT4 #(.INIT(16'hCACA)) l6 (.A(a[6]), .B(b[6]), .C(s), .D(1'b0), .Z(m[6]));
  LUT4 #(.INIT(16'hCACA)) l7 (.A(a[7]), .B(b[7]), .C(s), .D(1'b0), .Z(m[7]));
  always @(posedge clk) y <= m;
endmodule
