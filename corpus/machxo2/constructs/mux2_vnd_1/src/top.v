module top (clk, a, b, s, y);
  input [0:0] clk;
  input [0:0] a;
  input [0:0] b;
  input [0:0] s;
  output [0:0] y;
  reg [0:0] y;
  wire [0:0] m;
  LUT4 #(.init(16'hCACA)) l0 (.A(a[0]), .B(b[0]), .C(s), .D(1'b0), .Z(m[0]));
  always @(posedge clk) y <= m;
endmodule
