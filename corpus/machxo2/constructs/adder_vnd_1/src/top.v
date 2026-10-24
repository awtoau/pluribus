module top (clk, a, b, y);
  input [0:0] clk;
  input [0:0] a;
  input [0:0] b;
  output [1:0] y;
  reg [1:0] y;
  wire [1:0] c;
  wire [3:0] s;
  wire nc0;
  wire y0 = a[0] ^ b[0];
  CCU2D #(.INIT0(16'h7000), .INIT1(16'h5666), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(a[0]), .B0(b[0]), .C0(1'b0), .D0(1'b0), .A1(1'b0), .B1(1'b0), .C1(1'b0), .D1(1'b0), .COUT(c[1]), .S0(nc0), .S1(s[1]));
  always @(posedge clk) y <= {s[1:1], y0};
endmodule
