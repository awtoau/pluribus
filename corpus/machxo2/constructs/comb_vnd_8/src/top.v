module top (a, b, c, y);
  input [7:0] a;
  input [7:0] b;
  input [7:0] c;
  output [7:0] y;
  LUT4 #(.INIT(16'h7272)) l0 (.A(a[0]), .B(b[0]), .C(c[0]), .D(1'b0), .Z(y[0]));
  LUT4 #(.INIT(16'h7272)) l1 (.A(a[1]), .B(b[1]), .C(c[1]), .D(1'b0), .Z(y[1]));
  LUT4 #(.INIT(16'h7272)) l2 (.A(a[2]), .B(b[2]), .C(c[2]), .D(1'b0), .Z(y[2]));
  LUT4 #(.INIT(16'h7272)) l3 (.A(a[3]), .B(b[3]), .C(c[3]), .D(1'b0), .Z(y[3]));
  LUT4 #(.INIT(16'h7272)) l4 (.A(a[4]), .B(b[4]), .C(c[4]), .D(1'b0), .Z(y[4]));
  LUT4 #(.INIT(16'h7272)) l5 (.A(a[5]), .B(b[5]), .C(c[5]), .D(1'b0), .Z(y[5]));
  LUT4 #(.INIT(16'h7272)) l6 (.A(a[6]), .B(b[6]), .C(c[6]), .D(1'b0), .Z(y[6]));
  LUT4 #(.INIT(16'h7272)) l7 (.A(a[7]), .B(b[7]), .C(c[7]), .D(1'b0), .Z(y[7]));
endmodule
