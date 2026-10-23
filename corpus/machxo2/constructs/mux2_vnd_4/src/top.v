module top (clk, a, b, s, y);
  input clk;
  input [3:0] a;
  input [3:0] b;
  input s;
  output [3:0] y;
  reg [3:0] y;
  wire [3:0] m;
  LUT4 #(.INIT(16'hCACA)) l0 (.A(a[0]), .B(b[0]), .C(s), .D(1'b0), .Z(m[0]));
  LUT4 #(.INIT(16'hCACA)) l1 (.A(a[1]), .B(b[1]), .C(s), .D(1'b0), .Z(m[1]));
  LUT4 #(.INIT(16'hCACA)) l2 (.A(a[2]), .B(b[2]), .C(s), .D(1'b0), .Z(m[2]));
  LUT4 #(.INIT(16'hCACA)) l3 (.A(a[3]), .B(b[3]), .C(s), .D(1'b0), .Z(m[3]));
  always @(posedge clk) y <= m;
endmodule
