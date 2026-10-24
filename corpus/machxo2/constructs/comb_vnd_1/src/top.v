module top (a, b, c, y);
  input [0:0] a;
  input [0:0] b;
  input [0:0] c;
  output [0:0] y;
  LUT4 #(.init(16'h7272)) l0 (.A(a[0]), .B(b[0]), .C(c[0]), .D(1'b0), .Z(y[0]));
endmodule
