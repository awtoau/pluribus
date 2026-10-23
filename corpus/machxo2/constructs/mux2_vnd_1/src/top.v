module top (clk, a, b, s, y);
  input clk;
  input a;
  input b;
  input s;
  output y;
  reg y;
  wire m;
  LUT4 #(.INIT(16'hCACA)) l0 (.A(a[0]), .B(b[0]), .C(s), .D(1'b0), .Z(m[0]));
  always @(posedge clk) y <= m;
endmodule
