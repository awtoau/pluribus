module top (clk, a, b, y);
  input [0:0] clk;
  input [3:0] a;
  input [3:0] b;
  output [4:0] y;
  reg [4:0] y;
  wire [3:0] c;
  wire [7:0] s;
  wire nc0;
  wire y0 = a[0] ^ b[0];
  CCU2D #(.INIT0(16'h7000), .INIT1(16'h5666), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(a[0]), .B0(b[0]), .C0(1'b0), .D0(1'b0), .A1(a[1]), .B1(b[1]), .C1(1'b0), .D1(1'b0), .COUT(c[1]), .S0(nc0), .S1(s[1]));
  CCU2D #(.INIT0(16'h5666), .INIT1(16'h5666), .INJECT1_0("NO"), .INJECT1_1("NO")) u1 (.A0(a[2]), .B0(b[2]), .C0(1'b0), .D0(1'b0), .A1(a[3]), .B1(b[3]), .C1(1'b0), .D1(1'b0), .CIN(c[1]), .COUT(c[2]), .S0(s[2]), .S1(s[3]));
  CCU2D #(.INIT0(16'h5666), .INIT1(16'h5666), .INJECT1_0("NO"), .INJECT1_1("NO")) u2 (.A0(1'b0), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(1'b0), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[2]), .COUT(c[3]), .S0(s[4]), .S1(s[5]));
  always @(posedge clk) y <= {s[4:1], y0};
endmodule
