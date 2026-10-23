module top (a, b, c, y);
  input [3:0] a;
  input [3:0] b;
  input [3:0] c;
  output [3:0] y;
  LUT4 #(.init(16'h7272)) l0 (.A(a[0]), .B(b[0]), .C(c[0]), .D(1'b0), .Z(y[0]));
  LUT4 #(.init(16'h7272)) l1 (.A(a[1]), .B(b[1]), .C(c[1]), .D(1'b0), .Z(y[1]));
  LUT4 #(.init(16'h7272)) l2 (.A(a[2]), .B(b[2]), .C(c[2]), .D(1'b0), .Z(y[2]));
  LUT4 #(.init(16'h7272)) l3 (.A(a[3]), .B(b[3]), .C(c[3]), .D(1'b0), .Z(y[3]));
endmodule
