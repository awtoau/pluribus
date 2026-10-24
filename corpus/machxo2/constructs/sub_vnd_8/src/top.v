module top (clk, a, b, y);
  input [0:0] clk;
  input [7:0] a;
  input [7:0] b;
  output [8:0] y;
  reg [8:0] y;
  wire [5:0] c;
  wire [11:0] s;
  wire nc0;
  CCU2D #(.INIT0(16'h0000), .INIT1(16'h5999), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(1'b0), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(a[0]), .B1(b[0]), .C1(1'b0), .D1(1'b0), .COUT(c[1]), .S0(nc0), .S1(s[0]));
  CCU2D #(.INIT0(16'h5999), .INIT1(16'h5999), .INJECT1_0("NO"), .INJECT1_1("NO")) u1 (.A0(a[1]), .B0(b[1]), .C0(1'b0), .D0(1'b0), .A1(a[2]), .B1(b[2]), .C1(1'b0), .D1(1'b0), .CIN(c[1]), .COUT(c[2]), .S0(s[1]), .S1(s[2]));
  CCU2D #(.INIT0(16'h5999), .INIT1(16'h5999), .INJECT1_0("NO"), .INJECT1_1("NO")) u2 (.A0(a[3]), .B0(b[3]), .C0(1'b0), .D0(1'b0), .A1(a[4]), .B1(b[4]), .C1(1'b0), .D1(1'b0), .CIN(c[2]), .COUT(c[3]), .S0(s[3]), .S1(s[4]));
  CCU2D #(.INIT0(16'h5999), .INIT1(16'h5999), .INJECT1_0("NO"), .INJECT1_1("NO")) u3 (.A0(a[5]), .B0(b[5]), .C0(1'b0), .D0(1'b0), .A1(a[6]), .B1(b[6]), .C1(1'b0), .D1(1'b0), .CIN(c[3]), .COUT(c[4]), .S0(s[5]), .S1(s[6]));
  CCU2D #(.INIT0(16'h5999), .INIT1(16'h5999), .INJECT1_0("NO"), .INJECT1_1("NO")) u4 (.A0(a[7]), .B0(b[7]), .C0(1'b0), .D0(1'b0), .A1(1'b0), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[4]), .COUT(c[5]), .S0(s[7]), .S1(s[8]));
  always @(posedge clk) y <= s[8:0];
endmodule
