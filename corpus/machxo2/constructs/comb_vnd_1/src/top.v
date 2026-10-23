module top (a, b, c, y);
  input a;
  input b;
  input c;
  output y;
  LUT4 #(.INIT(16'h7272)) l0 (.A(a[0]), .B(b[0]), .C(c[0]), .D(1'b0), .Z(y[0]));
endmodule
